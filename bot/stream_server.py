import os
import sys
import re
import asyncio
import sqlite3
import logging
from pathlib import Path
from aiohttp import web
from telethon import TelegramClient

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("TGStreamServer")

# Telegram MTProto 通用凭据
API_ID = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

# 数据库路径与配置
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "music.db")))
if not DB_PATH.exists() and (BASE_DIR.parent / "music.db").exists():
    DB_PATH = BASE_DIR.parent / "music.db"

# 优先读取系统环境变量 BOT_TOKEN (云平台注入) -> 其次读取 .env
bot_token = os.getenv("BOT_TOKEN", "").strip()
if not bot_token:
    for env_candidate in [BASE_DIR / ".env", BASE_DIR.parent / ".env"]:
        if env_candidate.exists():
            with open(env_candidate, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip().startswith("BOT_TOKEN="):
                        bot_token = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                        break
            if bot_token:
                break

if not bot_token:
    logger.error("❌ 未检测到 BOT_TOKEN 环境变量或 .env 配置！")
    sys.exit(1)

# 初始化 Telethon Client
SESSION_PATH = str(BASE_DIR / "stream_bot.session")
tg_client = TelegramClient(SESSION_PATH, API_ID, API_HASH)

# 实体缓存
CACHED_MESSAGES = {}

def get_song_info(song_id: int):
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT id, title, performer, album, duration, channel_id, message_id, file_name FROM songs WHERE id = ?", (song_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

async def handle_options(request):
    """处理跨域预检请求"""
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Origin, Content-Type, Accept",
        "Access-Control-Max-Age": "86400",
    }
    return web.Response(headers=headers)

async def stream_handler(request):
    """核心流媒体响应控制器，支持 HTTP 206 Partial Content (Range)"""
    song_id_str = request.match_info.get("song_id")
    try:
        song_id = int(song_id_str)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Invalid song id")

    song = get_song_info(song_id)
    if not song:
        return web.Response(status=404, text="Song not found in database")

    channel_id = int(song["channel_id"])
    message_id = int(song["message_id"])

    # 获取或缓存 Message 对象
    cache_key = f"{channel_id}:{message_id}"
    msg = CACHED_MESSAGES.get(cache_key)
    if not msg:
        try:
            entity = await tg_client.get_entity(channel_id)
            msg = await tg_client.get_messages(entity, ids=message_id)
            if msg and msg.media:
                CACHED_MESSAGES[cache_key] = msg
        except Exception as e:
            logger.error(f"获取频道消息失败 (ID {message_id}): {e}")
            return web.Response(status=500, text=f"Error fetching message: {e}")

    if not msg or not msg.media or not getattr(msg, "file", None):
        return web.Response(status=404, text="Media not found in Telegram message")

    file_size = msg.file.size
    mime_type = msg.file.mime_type or "audio/mpeg"
    file_name = getattr(msg.file, "name", None) or f"{song['title']}.mp3"

    # 处理 HTTP Range 请求头
    range_header = request.headers.get("Range")
    from_bytes = 0
    until_bytes = file_size - 1

    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            from_bytes = int(range_match.group(1))
            if range_match.group(2):
                until_bytes = int(range_match.group(2))

    if until_bytes >= file_size:
        until_bytes = file_size - 1

    content_length = until_bytes - from_bytes + 1

    headers = {
        "Content-Type": mime_type,
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Range, Origin, Content-Type, Accept",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "Content-Disposition": f'inline; filename="{file_name}"',
    }

    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        status_code = 206
    else:
        status_code = 200

    response = web.StreamResponse(status=status_code, headers=headers)
    await response.prepare(request)

    # 以 128KB 为 MTProto 强制对齐块大小
    chunk_size = 128 * 1024
    aligned_offset = (from_bytes // chunk_size) * chunk_size
    skip_bytes = from_bytes - aligned_offset

    bytes_sent = 0
    is_first_chunk = True

    try:
        async for chunk in tg_client.iter_download(
            msg.media,
            offset=aligned_offset,
            request_size=chunk_size
        ):
            if is_first_chunk:
                is_first_chunk = False
                if skip_bytes > 0:
                    chunk = chunk[skip_bytes:]

            if bytes_sent + len(chunk) > content_length:
                chunk = chunk[:content_length - bytes_sent]

            if chunk:
                await response.write(chunk)
                bytes_sent += len(chunk)

            if bytes_sent >= content_length:
                break
    except (ConnectionResetError, asyncio.CancelledError):
        # 客户端（浏览器）拖动进度条或切歌，正常断开前一个请求
        pass
    except Exception as e:
        logger.warning(f"流式传输中断 (Song {song_id}): {e}")

    await response.write_eof()
    return response

async def handle_info(request):
    """获取歌曲元信息接口"""
    song_id = int(request.match_info.get("song_id", 0))
    song = get_song_info(song_id)
    if not song:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"ok": True, "song": song}, headers={"Access-Control-Allow-Origin": "*"})

async def handle_health(request):
    return web.json_response({"status": "running", "service": "Lizhi Stream Service"}, headers={"Access-Control-Allow-Origin": "*"})

def init_app():
    app = web.Application()
    app.router.add_route("OPTIONS", "/stream/{song_id}", handle_options)
    app.router.add_route("GET", "/stream/{song_id}", stream_handler)
    app.router.add_route("OPTIONS", "/info/{song_id}", handle_options)
    app.router.add_route("GET", "/info/{song_id}", handle_info)
    app.router.add_route("GET", "/health", handle_health)
    return app

async def main():
    logger.info(">>> 启动 Telegram MTProto 客户端...")
    await tg_client.start(bot_token=bot_token)
    me = await tg_client.get_me()
    logger.info(f"✅ MTProto 客户端在线: @{me.username}")

    app = init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", os.getenv("STREAM_PORT", 8000)))
    site = web.TCPSite(runner, "0.0.0.0", port)
    logger.info(f"🚀 音频流媒体服务已在 0.0.0.0:{port} 启动监听！")
    await site.start()

    # 保持常驻运行
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("服务安全退出")

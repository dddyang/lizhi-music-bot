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

# Telegram MTProto 开发者凭据（优先读取专属环境变量或 .env，未提供时使用默认备用）
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "your_telegram_api_hash_here").strip()

# 数据库路径与配置
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "music.db")))
if not DB_PATH.exists() and (BASE_DIR.parent / "music.db").exists():
    DB_PATH = BASE_DIR.parent / "music.db"

# 读取配置（BOT_TOKEN 与安全通信暗号 STREAM_SECRET）
bot_token = os.getenv("BOT_TOKEN", "").strip()
stream_secret = os.getenv("STREAM_SECRET", "lizhi-sec-7f89d3a1c5b4e208").strip()

if not bot_token:
    for env_candidate in [BASE_DIR / ".env", BASE_DIR.parent / ".env"]:
        if env_candidate.exists():
            with open(env_candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s.startswith("BOT_TOKEN="):
                        bot_token = line_s.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line_s.startswith("STREAM_SECRET="):
                        stream_secret = line_s.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line_s.startswith("API_ID="):
                        try:
                            API_ID = int(line_s.split("=", 1)[1].strip().strip('"').strip("'"))
                        except ValueError:
                            pass
                    elif line_s.startswith("API_HASH="):
                        API_HASH = line_s.split("=", 1)[1].strip().strip('"').strip("'")
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

def verify_request_secret(request) -> bool:
    """安全鉴权校验：局域网或携带正确暗号才放行"""
    remote_ip = request.remote or ""
    # 局域网访问（如 127.0.0.1 或 192.168.100.x）免密便于本地维护
    if remote_ip.startswith("127.") or remote_ip.startswith("192.168.") or remote_ip == "::1":
        return True
    
    # 外部公网访问必须验证专属暗号 Header
    req_secret = request.headers.get("X-Stream-Secret", "").strip()
    return req_secret == stream_secret

async def handle_options(request):
    """处理跨域预检请求"""
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Origin, Content-Type, Accept, X-Stream-Secret",
        "Access-Control-Max-Age": "86400",
    }
    return web.Response(headers=headers)

async def stream_handler(request):
    """核心流媒体响应控制器，支持 HTTP 206 Partial Content (Range) 与安全暗号防御"""
    if not verify_request_secret(request):
        logger.warning(f"🚨 拦截到未授权的公网探测请求！来源 IP: {request.remote}")
        return web.Response(status=403, text="Forbidden: Invalid or missing stream secret")

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
        "Access-Control-Allow-Headers": "Range, Origin, Content-Type, Accept, X-Stream-Secret",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        "Content-Disposition": f'inline; filename="{file_name}"',
        # 允许 Cloudflare 边缘缓存公共音频分片（缓存 30 天，节约软路由带宽）
        "Cache-Control": "public, max-age=2592000, s-maxage=2592000, immutable",
    }

    if range_header:
        headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
        status_code = 206
    else:
        status_code = 200

    response = web.StreamResponse(status=status_code, headers=headers)
    await response.prepare(request)

    # 128KB 对齐与切片
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
        pass
    except Exception as e:
        logger.warning(f"流式传输中断 (Song {song_id}): {e}")

    await response.write_eof()
    return response

async def handle_info(request):
    if not verify_request_secret(request):
        return web.Response(status=403, text="Forbidden")
    song_id = int(request.match_info.get("song_id", 0))
    song = get_song_info(song_id)
    if not song:
        return web.json_response({"error": "not found"}, status=404)
    return web.json_response({"ok": True, "song": song}, headers={"Access-Control-Allow-Origin": "*"})

async def handle_health(request):
    if not verify_request_secret(request):
        return web.Response(status=403, text="Forbidden")
    return web.json_response({"status": "running", "service": "Lizhi Secure Stream Service"}, headers={"Access-Control-Allow-Origin": "*"})

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
    
    port = int(os.getenv("PORT", os.getenv("STREAM_PORT", 8880)))
    # 同时监听 IPv4 与 IPv6 (host=None)
    site = web.TCPSite(runner, None, port)
    logger.info(f"🚀 安全流媒体服务已在 IPv4/IPv6 双栈端口 :{port} 启动监听！")
    await site.start()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("服务安全退出")

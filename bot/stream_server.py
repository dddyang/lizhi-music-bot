# -*- coding: utf-8 -*-
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

# Telegram MTProto 开发者凭据
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "your_telegram_api_hash_here").strip()

# 数据库路径与配置
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "music.db")))
if not DB_PATH.exists() and (BASE_DIR.parent / "music.db").exists():
    DB_PATH = BASE_DIR.parent / "music.db"

# 读取配置（BOT_TOKEN）
bot_token = os.getenv("BOT_TOKEN", "").strip()

if not bot_token:
    for env_candidate in [BASE_DIR / ".env", BASE_DIR.parent / ".env"]:
        if env_candidate.exists():
            with open(env_candidate, "r", encoding="utf-8") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s.startswith("BOT_TOKEN="):
                        bot_token = line_s.split("=", 1)[1].strip().strip('"').strip("'")
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

# 消息实体缓存
CACHED_MESSAGES = {}

# 本地 NAS 挂载路径与热点索引字典
NAS_AUDIO_DIRS = [Path("/mnt/nas/音乐/李志"), Path("Z:/音乐/李志")]
NAS_VIDEO_DIRS = [Path("/mnt/nas/影视/李志"), Path("Z:/影视/李志")]
LOCAL_MEDIA_INDEX = {}

def build_local_nas_index():
    """扫描软路由内网挂载的 NAS 原盘目录，构建 0 延迟秒开文件索引"""
    LOCAL_MEDIA_INDEX.clear()
    for adir in NAS_AUDIO_DIRS:
        if adir.exists():
            for p in adir.rglob("*"):
                if p.is_file() and p.suffix.lower() in (".flac", ".mp3", ".wav", ".m4a"):
                    LOCAL_MEDIA_INDEX[p.name.lower()] = str(p)
                    LOCAL_MEDIA_INDEX[p.stem.lower()] = str(p)
            break

    for vdir in NAS_VIDEO_DIRS:
        if vdir.exists():
            for p in vdir.rglob("*.mp4"):
                LOCAL_MEDIA_INDEX[p.name.lower()] = str(p)
                LOCAL_MEDIA_INDEX[p.stem.lower()] = str(p)
            break

    logger.info(f"⚡ NAS 千兆内网直通索引已就绪: 已命中 {len(LOCAL_MEDIA_INDEX)} 个原盘音视频，吞吐速率最高可达 45MB/s！")

def find_local_nas_path(media_type: str, item: dict):
    """根据歌曲/视频信息在本地 NAS 索引中检索真实文件路径"""
    fname = item.get("file_name") or ""
    title = item.get("title") or ""

    candidates = [
        fname.lower(),
        title.lower(),
        f"{title.lower()}.flac",
        f"{title.lower()}.mp3",
        f"{title.lower()}.mp4",
    ]
    for cand in candidates:
        if cand and cand in LOCAL_MEDIA_INDEX:
            return LOCAL_MEDIA_INDEX[cand]
    return None

def get_media_info(media_type: str, item_id: int):
    """根据类型从数据库中查询音频或视频的频道定位信息"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if media_type == "video":
        c.execute("SELECT id, title, category, year, channel_id, message_id FROM videos WHERE id = ?", (item_id,))
    else:
        c.execute("SELECT id, title, performer, album, duration, channel_id, message_id, file_name FROM songs WHERE id = ?", (item_id,))
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
    """
    通用音视频流媒体切片控制器，遵循 TG-FileStreamBot 规范：
    - 支持 HTTP 206 Partial Content (Byte-Range 断点续传)
    - 支持 Safari / Chrome / iOS / Android 原生 <audio> 和 <video>
    - 允许 Cloudflare Anycast 边缘缓存公共音频分片
    """
    media_type = request.match_info.get("media_type", "audio").lower()
    if media_type not in ("audio", "video"):
        return web.Response(status=404, text="Invalid media type, expected 'audio' or 'video'")

    # 如果通过兼容路由 /stream/{song_id} 访问
    if "song_id" in request.match_info:
        item_id_str = request.match_info.get("song_id")
        media_type = "audio"
    else:
        item_id_str = request.match_info.get("item_id")

    try:
        item_id = int(item_id_str)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Invalid ID")

    item = get_media_info(media_type, item_id)
    if not item:
        return web.Response(status=404, text=f"{media_type.capitalize()} not found in database")

    # ==========================================
    # 极速黄金通道 1：软路由内网 NAS 千兆直出 (45MB/s 零延迟)
    # ==========================================
    local_path = find_local_nas_path(media_type, item)
    if local_path and os.path.exists(local_path):
        file_size = os.path.getsize(local_path)
        mime_type = "video/mp4" if media_type == "video" else ("audio/flac" if local_path.lower().endswith(".flac") else "audio/mpeg")
        file_name = os.path.basename(local_path)

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
            "Cache-Control": "public, max-age=2592000, s-maxage=2592000, immutable",
            "X-Stream-Source": "Local-NAS-Gigabit-FastTrack",
        }

        if range_header:
            headers["Content-Range"] = f"bytes {from_bytes}-{until_bytes}/{file_size}"
            status_code = 206
        else:
            status_code = 200

        response = web.StreamResponse(status=status_code, headers=headers)
        await response.prepare(request)

        if request.method == "HEAD":
            await response.write_eof()
            return response

        # 256KB 大块直读推送，充分发挥千兆局域网 45MB/s 极限性能
        chunk_size = 256 * 1024
        bytes_sent = 0
        try:
            with open(local_path, "rb") as f:
                f.seek(from_bytes)
                while bytes_sent < content_length:
                    to_read = min(chunk_size, content_length - bytes_sent)
                    buf = f.read(to_read)
                    if not buf:
                        break
                    await response.write(buf)
                    bytes_sent += len(buf)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.warning(f"NAS 直传中断 ({file_name}): {e}")

        await response.write_eof()
        return response

    # ==========================================
    # 智能备用通道 2：Telegram 云端 MTProto 切片兜底
    # ==========================================
    channel_id = int(item["channel_id"])
    message_id = int(item["message_id"])

    cache_key = f"{channel_id}:{message_id}"
    msg = CACHED_MESSAGES.get(cache_key)
    if not msg:
        try:
            entity = await tg_client.get_entity(channel_id)
            msg = await tg_client.get_messages(entity, ids=message_id)
            if msg and msg.media:
                CACHED_MESSAGES[cache_key] = msg
        except Exception as e:
            logger.error(f"获取 Telegram 频道媒体消息失败 (ID {message_id}): {e}")
            return web.Response(status=500, text=f"Error fetching message: {e}")

    if not msg or not msg.media or not getattr(msg, "file", None):
        return web.Response(status=404, text="Media not found in Telegram message")

    file_size = msg.file.size
    default_mime = "video/mp4" if media_type == "video" else "audio/mpeg"
    mime_type = msg.file.mime_type or default_mime
    file_name = getattr(msg.file, "name", None) or f"{item['title']}.{'mp4' if media_type == 'video' else 'mp3'}"

    # 处理客户端 Byte-Range 请求
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

    # 如果是 HEAD 请求（如 curl -I 或浏览器预检探测），已成功发送响应头，直接结束
    if request.method == "HEAD":
        await response.write_eof()
        return response

    # 提升至 Telegram MTProto 官方黄金分片上限 512KB (相比 128KB 吞吐量提升 4 倍)
    chunk_size = 512 * 1024
    aligned_offset = (from_bytes // chunk_size) * chunk_size
    skip_bytes = from_bytes - aligned_offset

    bytes_sent = 0

    # 异步预取双缓冲队列 (Prefetch Queue)
    # 当网络把当前块发送给手机时，后台已在并行从 Telegram 拉取下一块，抹平网络往返 RTT
    queue = asyncio.Queue(maxsize=3)
    fetch_error = None

    async def producer():
        nonlocal fetch_error
        try:
            async for raw_chunk in tg_client.iter_download(
                msg.media,
                offset=aligned_offset,
                request_size=chunk_size
            ):
                await queue.put(raw_chunk)
        except Exception as err:
            fetch_error = err
        finally:
            await queue.put(None) # 结束标志

    producer_task = asyncio.create_task(producer())

    try:
        is_first_chunk = True
        while bytes_sent < content_length:
            chunk = await queue.get()
            if chunk is None:
                break

            if is_first_chunk:
                is_first_chunk = False
                if skip_bytes > 0:
                    chunk = chunk[skip_bytes:]

            if bytes_sent + len(chunk) > content_length:
                chunk = chunk[:content_length - bytes_sent]

            if chunk:
                await response.write(chunk)
                bytes_sent += len(chunk)

            queue.task_done()
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    except Exception as e:
        logger.warning(f"流式传输中断 ({media_type} {item_id}): {e}")
    finally:
        if not producer_task.done():
            producer_task.cancel()

    await response.write_eof()
    return response

async def handle_health(request):
    return web.json_response({
        "status": "running",
        "service": "Lizhi Universal Audio/Video Stream Engine",
        "engine_mode": "Hybrid (NAS Gigabit FastTrack + Telegram MTProto Fallback)",
        "nas_indexed_media": len(LOCAL_MEDIA_INDEX)
    }, headers={"Access-Control-Allow-Origin": "*"})

def init_app():
    app = web.Application()
    # 统一双模态流媒体路由 (GET / HEAD / OPTIONS)
    app.router.add_route("OPTIONS", "/stream/{media_type}/{item_id}", handle_options)
    app.router.add_route("GET", "/stream/{media_type}/{item_id}", stream_handler)
    app.router.add_route("HEAD", "/stream/{media_type}/{item_id}", stream_handler)

    # 兼容历史音频路由 (/stream/{song_id})
    app.router.add_route("OPTIONS", "/stream/{song_id}", handle_options)
    app.router.add_route("GET", "/stream/{song_id}", stream_handler)
    app.router.add_route("HEAD", "/stream/{song_id}", stream_handler)

    # 健康探针
    app.router.add_route("GET", "/health", handle_health)
    app.router.add_route("HEAD", "/health", handle_health)
    return app

async def main():
    logger.info(">>> 构建 NAS 内网原盘极速缓存索引...")
    build_local_nas_index()

    logger.info(">>> 启动 Telegram MTProto 客户端...")
    await tg_client.start(bot_token=bot_token)
    me = await tg_client.get_me()
    logger.info(f"✅ MTProto 客户端在线: @{me.username}")

    app = init_app()
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", os.getenv("STREAM_PORT", 8880)))
    site = web.TCPSite(runner, None, port)
    logger.info(f"🚀 音影双全流媒体引擎已在 IPv4/IPv6 双栈端口 :{port} 启动监听！")
    await site.start()

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("服务安全退出")

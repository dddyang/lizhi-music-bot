import asyncio
import logging
import re
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ChatType

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase

# 配置日志格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

db = MusicDatabase(DB_PATH)

# 用于暂存同一批上传（Media Group）的专辑名称缓存
# 结构: { media_group_id: album_name }
media_group_album_cache = {}


def extract_album_name(caption: Optional[str], file_name: Optional[str]) -> Optional[str]:
    """
    智能从消息配字 (Caption) 或文件名中提取专辑名称
    支持格式示例:
      - Caption: 专辑: 梵高先生 或 #梵高先生 或 《梵高先生》
      - File: [被禁忌的游戏] 01.黑色信封.mp3
    """
    if caption:
        caption = caption.strip()
        # 1. 匹配《专辑名》
        m = re.search(r"《([^》]+)》", caption)
        if m:
            return m.group(1).strip()
        # 2. 匹配 专辑: xxx 或 专辑：xxx
        m = re.search(r"专辑[:：]\s*([^\n\r]+)", caption)
        if m:
            return m.group(1).strip()
        # 3. 匹配 #标签名（如 #梵高先生）
        m = re.search(r"#([^\s#]+)", caption)
        if m:
            return m.group(1).strip()
        # 4. 如果只有一行且简短，直接作为专辑名
        first_line = caption.splitlines()[0].strip()
        if len(first_line) <= 20 and not first_line.startswith("/"):
            return first_line

    if file_name:
        # 从文件名提取中括号 [专辑名]
        m = re.search(r"^\[([^\]]+)\]", file_name)
        if m:
            return m.group(1).strip()

    return None


async def start_listener():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.error("❌ 未检测到有效的 BOT_TOKEN，请先在 .env 文件中填入从 @BotFather 获取的 Token！")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.channel_post(F.audio)
    @dp.channel_post(F.document.mime_type.startswith("audio/"))
    async def on_channel_audio_received(message: Message):
        """当频道中有新的音频消息发布时触发"""
        chat_id = message.chat.id
        # 如果配置了指定 CHANNEL_ID，只接收该频道的更新（避免串台）
        if CHANNEL_ID and str(chat_id) != str(CHANNEL_ID):
            logger.debug(f"收到非目标频道消息 (chat_id: {chat_id})，已忽略")
            return

        audio = message.audio or message.document
        title = getattr(audio, "title", None) or getattr(audio, "file_name", "未知歌曲")
        performer = getattr(audio, "performer", None) or "李志"
        duration = getattr(audio, "duration", 0)
        file_id = audio.file_id
        file_unique_id = audio.file_unique_id
        file_name = getattr(audio, "file_name", None)

        caption = message.caption
        album = extract_album_name(caption, file_name)

        # 处理多首打包上传（Telegram Media Group）的情况
        if message.media_group_id:
            if album:
                media_group_album_cache[message.media_group_id] = album
            elif message.media_group_id in media_group_album_cache:
                album = media_group_album_cache[message.media_group_id]

        if not album:
            album = "单曲 / 未归类"

        is_new, song_id = db.add_or_update_song(
            title=title,
            performer=performer,
            album=album,
            duration=duration,
            channel_id=str(chat_id),
            message_id=message.message_id,
            file_id=file_id,
            file_unique_id=file_unique_id,
            file_name=file_name
        )

        status_text = "✨ [新增曲目]" if is_new else "🔄 [更新曲目]"
        logger.info(
            f"{status_text} ID: {song_id} | 专辑: 《{album}》 | 歌曲: {title} | 消息ID: {message.message_id}"
        )

    # 打印启动提示
    bot_info = await bot.get_me()
    logger.info("=" * 60)
    logger.info(f"🤖 机器人 @{bot_info.username} 入库监听服务已启动！")
    logger.info(f"🎯 监听频道: {CHANNEL_ID or '所有添加了该机器人的频道'}")
    logger.info("💡 使用说明:")
    logger.info("  1. 确保机器人已被添加为你频道的管理员（具有读取消息权限）")
    logger.info("  2. 在频道中上传音乐时，附言 (Caption) 写上专辑名，如: 专辑: 梵高先生 或 《梵高先生》")
    logger.info("  3. 如果多首歌一起上传，只要在第一首歌附言写上专辑名，整批都会自动归入该专辑")
    logger.info("  4. 随时可以按 Ctrl+C 停止监听")
    logger.info("=" * 60)

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(start_listener())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 监听服务已安全停止。")

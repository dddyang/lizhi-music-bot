import asyncio
import os
import re
import sys
from pathlib import Path
from PIL import Image

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile
from mutagen import File as MutagenFile

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase

TEMP_DIR = Path(__file__).resolve().parent / ".temp_audio"
AUDIO_FILE = TEMP_DIR / "tuoniao_fit.mp3"
COVER_FILE = Path(r"Z:\音乐\李志\洗心革面 跨年音乐会\Cover.jpg")
ALBUM_NAME = "洗心革面 跨年音乐会"
TITLE = "鸵鸟+墙上的向日葵+这个世界会好吗+定西"
YEAR = 2019

def make_thumbnail(cover_path: Path, thumb_path: Path):
    if not cover_path.exists():
        return None
    try:
        img = Image.open(cover_path).convert("RGB")
        img.thumbnail((320, 320), Image.Resampling.LANCZOS)
        img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        print(f"生成缩略图失败: {e}")
        return None

async def main():
    bot = Bot(token=BOT_TOKEN, session=AiohttpSession(timeout=300.0))
    db = MusicDatabase(DB_PATH)

    print(f"🚀 开始上传最后一首曲目: 《{TITLE}》 ({AUDIO_FILE.stat().st_size / (1024*1024):.1f}MB)")

    duration = 0
    try:
        tag = MutagenFile(str(AUDIO_FILE))
        if tag and tag.info:
            duration = int(tag.info.length)
    except Exception:
        pass

    thumb_file = TEMP_DIR / "tuoniao_thumb.jpg"
    thumb_path = make_thumbnail(COVER_FILE, thumb_file)
    thumb_input = FSInputFile(str(thumb_path)) if thumb_path else None

    clean_tag = re.sub(r'[\s\-_《》\(\)“”、/]+', '', ALBUM_NAME)
    year_str = f"{YEAR}年"

    caption = (
        f"🎵 歌曲：{TITLE}\n"
        f"💿 专辑：《{ALBUM_NAME}》\n"
        f"📅 发行年份：{year_str}\n"
        f"🎸 歌手：李志\n\n"
        f"#李志 #{clean_tag} #{year_str}"
    )

    audio_in = FSInputFile(str(AUDIO_FILE), filename=f"{TITLE}.mp3")

    sent_msg = None
    for attempt in range(1, 4):
        try:
            sent_msg = await bot.send_audio(
                chat_id=CHANNEL_ID,
                audio=audio_in,
                title=TITLE,
                performer="李志",
                duration=duration or None,
                caption=caption,
                thumbnail=thumb_input
            )
            break
        except TelegramRetryAfter as e:
            print(f"  ⏳ 频控等待 {e.retry_after + 1} 秒...")
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            print(f"  ⚠️ 上传重试 ({attempt}): {e}")
            await asyncio.sleep(2)

    if sent_msg:
        audio = sent_msg.audio or sent_msg.document
        db.add_or_update_song(
            title=TITLE,
            performer="李志",
            album=ALBUM_NAME,
            duration=getattr(audio, "duration", duration) or 0,
            channel_id=str(CHANNEL_ID),
            message_id=sent_msg.message_id,
            file_id=audio.file_id,
            file_unique_id=audio.file_unique_id,
            file_name="鸵鸟+墙上的向日葵+这个世界会好吗+定西.flac",
            year=YEAR
        )
        print(f"✅ 成功入库: {TITLE} (MsgID: {sent_msg.message_id})")

    if thumb_file.exists():
        thumb_file.unlink()

    # 重新生成并置顶编年史总目录
    print("📌 正在更新并置顶频道编年史总目录...")
    from create_pinned_index import post_and_pin_index
    await post_and_pin_index()

    await bot.session.close()
    print("🎉 全部任务彻底圆满收官！")

if __name__ == "__main__":
    asyncio.run(main())

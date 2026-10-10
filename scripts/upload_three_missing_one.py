import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

import imageio_ffmpeg
from PIL import Image
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile
from mutagen import File as MutagenFile

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("UploadThreeMissingOne")

SOURCE_DIR = Path(r"Z:\音乐\李志\lz...THREE MISSING ONE(叁缺壹) JAPAN Tour 2024 in Tokyo wav")
TEMP_DIR = Path(__file__).resolve().parent / ".temp_audio"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
ALBUM_NAME = "叁缺壹 (2024 Tokyo Live)"
YEAR = 2024


def clean_title(filename: str) -> str:
    stem = Path(filename).stem
    # 移除开头的序号如 01, 02
    stem = re.sub(r"^\d{1,3}[\.\s\-_]+", "", stem)
    return stem.strip()


def get_audio_duration(file_path: Path) -> int:
    try:
        tag = MutagenFile(str(file_path))
        if tag and tag.info and hasattr(tag.info, "length"):
            return int(tag.info.length)
    except Exception:
        pass
    return 0


def convert_wav_to_mp3(wav_path: Path, mp3_path: Path) -> bool:
    if mp3_path.exists() and mp3_path.stat().st_size > 0:
        return True
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i", str(wav_path),
        "-codec:a", "libmp3lame",
        "-b:a", "320k",
        str(mp3_path)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return mp3_path.exists() and mp3_path.stat().st_size > 0
    except Exception as e:
        logger.error(f"FFmpeg 转码失败: {wav_path.name}, 错误: {e}")
        return False


def create_thumbnail() -> Optional[Path]:
    thumb_path = TEMP_DIR / "three_missing_one_thumb.jpg"
    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        return thumb_path

    cover_file = SOURCE_DIR / "cover.jpg"
    if not cover_file.exists():
        cover_file = SOURCE_DIR / "Back.jpg"

    if cover_file.exists():
        try:
            img = Image.open(cover_file).convert("RGB")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            img.save(thumb_path, "JPEG", quality=90)
            return thumb_path
        except Exception as e:
            logger.warning(f"缩略图生成失败: {e}")
    return None


async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("❌ 请检查 .env 配置文件！")
        return

    db = MusicDatabase(DB_PATH)
    session = AiohttpSession(timeout=300.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    files = sorted([f for f in SOURCE_DIR.iterdir() if f.is_file() and f.suffix.lower() == ".wav"])
    print(f"🎵 找到《叁缺壹》全部曲目: 共 {len(files)} 首")

    # 1. 发送专辑海报
    cover_file = SOURCE_DIR / "cover.jpg"
    if not cover_file.exists():
        cover_file = SOURCE_DIR / "Back.jpg"

    header_text = (
        f"💿 ━━━━━━━━━━━━━━━━━━━\n"
        f"💿 专辑：《{ALBUM_NAME}》\n"
        f"📅 发行年份：{YEAR}年\n"
        f"🎸 歌手：李志\n"
        f"🎵 曲目数：共收录 14 首现场全本录音\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 **完整曲目列表：**\n"
        f"01. 关于郑州的记忆+董卓谣+春末南方的城市\n"
        f"02. 苍井空\n"
        f"03. 倒影\n"
        f"04. 黑色信封\n"
        f"05. 和你在一起\n"
        f"06. 天空之城\n"
        f"07. 鸵鸟+墙上的向日葵+鼠说\n"
        f"08. 这个世界会好吗\n"
        f"09. 梵高先生\n"
        f"10. 被禁忌的游戏+定西+一个夜晚\n"
        f"11. 大象+门+来了+热河\n"
        f"12. 寻找+忽然\n"
        f"13. 山阴路的夏天\n"
        f"14. 你离开了南京，从此没有人和我说话\n\n"
        f"#李志 #叁缺壹 #2024年 #TokyoLive"
    )

    print("📸 发送专辑门面海报...")
    if cover_file.exists():
        h_msg = await bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=FSInputFile(str(cover_file)),
            caption=header_text,
            parse_mode="Markdown"
        )
    else:
        h_msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=header_text,
            parse_mode="Markdown"
        )
    print(f"✨ 专辑门面海报已送达 (MsgID: {h_msg.message_id})")
    await asyncio.sleep(2.0)

    thumb_path = create_thumbnail()
    thumb_input = FSInputFile(str(thumb_path)) if thumb_path else None

    # 2. 依次转码并上传 14 首歌曲
    for idx, f in enumerate(files, 1):
        title = clean_title(f.name)
        print(f"\n[{idx:02d}/14] 正在处理: {title} ...")

        # 转码为 320k MP3
        mp3_name = f"{f.stem}.mp3"
        mp3_file = TEMP_DIR / mp3_name
        print(f"  ⚙️ 转码 320k MP3...")
        if not convert_wav_to_mp3(f, mp3_file):
            print(f"  ❌ 转码失败，跳过: {f.name}")
            continue

        duration = get_audio_duration(mp3_file) or get_audio_duration(f)
        size_mb = mp3_file.stat().st_size / (1024 * 1024)
        print(f"  ⬆️ 正在上传 ({size_mb:.1f}MB, 时长 {duration}s)...")

        caption = (
            f"🎵 歌曲：{title}\n"
            f"💿 专辑：《{ALBUM_NAME}》\n"
            f"📅 发行年份：{YEAR}年\n"
            f"🎸 歌手：李志\n\n"
            f"#李志 #叁缺壹 #2024年"
        )

        for attempt in range(1, 4):
            try:
                audio_input = FSInputFile(str(mp3_file), filename=f"{title}.mp3")
                msg = await bot.send_audio(
                    chat_id=CHANNEL_ID,
                    audio=audio_input,
                    title=title,
                    performer="李志",
                    duration=duration or None,
                    caption=caption,
                    thumbnail=thumb_input
                )

                audio = msg.audio or msg.document
                db.add_or_update_song(
                    title=title,
                    performer="李志",
                    album=ALBUM_NAME,
                    duration=getattr(audio, "duration", duration) or 0,
                    channel_id=str(CHANNEL_ID),
                    message_id=msg.message_id,
                    file_id=audio.file_id,
                    file_unique_id=audio.file_unique_id,
                    file_name=f.name,
                    year=YEAR
                )
                print(f"  ✅ 上传成功！(MsgID: {msg.message_id})")
                break
            except TelegramRetryAfter as e:
                print(f"  ⏳ 频控等待 {e.retry_after + 1} 秒...")
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                print(f"  ⚠️ 上传出错 ({e})，2秒后重试...")
                await asyncio.sleep(2)

        # 歌曲间隔
        await asyncio.sleep(2.5)

    print("\n🎉 《叁缺壹》全部 14 首曲目上传完成！")

    # 3. 重新生成并置顶总索引
    print("📌 重新生成置顶目录...")
    from create_pinned_index import post_and_pin_index
    await post_and_pin_index()

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

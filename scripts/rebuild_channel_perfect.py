import asyncio
import io
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple, List, Dict

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
logger = logging.getLogger("RebuildChannel")

MUSIC_ROOT = Path(r"Z:\音乐\李志")
TEMP_DIR = Path(__file__).resolve().parent / ".temp_audio"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

# 50MB 阈值 (Telegram Bot API 上传限制)
MAX_BOT_FILE_SIZE = 49 * 1024 * 1024

# 专辑元数据映射表（年份与标准化名称）
ALBUM_CONFIGS = {
    "被禁忌的游戏": {"year": 2004, "name": "被禁忌的游戏"},
    "梵高先生": {"year": 2005, "name": "梵高先生"},
    "这个世界会好吗": {"year": 2006, "name": "这个世界会好吗"},
    "我爱南京": {"year": 2009, "name": "我爱南京"},
    "二零零九年十月十六日事件": {"year": 2009, "name": "二零零九年十月十六日事件"},
    "工体东路没有人": {"year": 2009, "name": "工体东路没有人"},
    "你好 郑州": {"year": 2010, "name": "你好，郑州"},
    "义乌隔壁酒吧": {"year": 2010, "name": "义乌隔壁酒吧"},
    "杂选": {"year": 2010, "name": "杂选"},
    "《8》": {"year": 2011, "name": "8"},
    "《F》": {"year": 2011, "name": "F"},
    "杭州酒球会一身酒气": {"year": 2011, "name": "杭州酒球会一身酒气"},
    "Imagine Live": {"year": 2012, "name": "Imagine Live"},
    "挺”不插电巡演 郑州站": {"year": 2012, "name": "“挺”不插电巡演 郑州站"},
    "108个关键词": {"year": 2013, "name": "108个关键词"},
    "勾三搭四": {"year": 2014, "name": "勾三搭四"},
    "李志 1701": {"year": 2014, "name": "李志 1701"},
    "I O": {"year": 2014, "name": "I/O"},
    "动静（2015Live）": {"year": 2015, "name": "动静 (2015 Live)"},
    "看见  李志2015巡回演唱会": {"year": 2015, "name": "看见 (李志2015巡回演唱会)"},
    "李志LIVE精选": {"year": 2015, "name": "李志LIVE精选"},
    "金城兰州": {"year": 2015, "name": "金城兰州"},
    "在每一条伤心的应天大街上": {"year": 2016, "name": "在每一条伤心的应天大街上"},
    "李志北京不插电现场 2016 Live": {"year": 2016, "name": "李志北京不插电现场 2016 Live"},
    "李志、电声与管弦乐": {"year": 2016, "name": "李志、电声与管弦乐"},
    "爵士乐与不插电新编12首": {"year": 2017, "name": "爵士乐与不插电新编12首"},
    "李志、电声与管弦乐II": {"year": 2018, "name": "李志、电声与管弦乐II"},
    "Best Selection Songs 2004-2018(Vol.2)": {"year": 2018, "name": "Best Selection Songs 2004-2018 (Vol.2)"},
    "Best Selection Songs 2004-2018(Vol.3)": {"year": 2018, "name": "Best Selection Songs 2004-2018 (Vol.3)"},
    "best Selection Songs 2004-2019(Vol.1)": {"year": 2019, "name": "Best Selection Songs 2004-2019 (Vol.1)"},
    "洗心革面 跨年音乐会": {"year": 2019, "name": "洗心革面 跨年音乐会"},
    "lz...THREE MISSING ONE(叁缺壹) JAPAN Tour 2024 in Tokyo wav": {"year": 2024, "name": "叁缺壹 (2024 Tokyo Live)"},
}


def clean_title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\d{1,3}[\.\s\-_]+", "", stem)
    return stem.strip() or filename


def get_audio_info(file_path: Path, album_cfg: dict) -> Tuple[str, str, str, int, int]:
    title = clean_title_from_filename(file_path.name)
    duration = 0
    try:
        tag = MutagenFile(str(file_path), easy=True)
        if tag:
            t = tag.get("title", [None])[0]
            if t and t.strip():
                title = t.strip()
            if tag.info and hasattr(tag.info, "length"):
                duration = int(tag.info.length)
    except Exception:
        pass

    return title, album_cfg["name"], "李志", duration, album_cfg["year"]


def find_cover_image(folder_path: Path) -> Optional[Path]:
    patterns = ["cover.jpg", "Cover.jpg", "cover.png", "Cover.png", "Cove.jpg", "folder.jpg", "*.jpg", "*.png"]
    for p in patterns:
        matches = list(folder_path.glob(p))
        if matches:
            return matches[0]
    for p in patterns:
        matches = list(folder_path.glob(f"*/{p}"))
        if matches:
            return matches[0]
    return None


def get_or_create_cover(folder_path: Path, album_name: str) -> Optional[Path]:
    cover = find_cover_image(folder_path)
    if cover:
        return cover

    if "杂选" in album_name:
        zaxuan_cover = TEMP_DIR / "zaxuan_cover.jpg"
        if zaxuan_cover.exists():
            return zaxuan_cover

    if "Vol.1" in album_name:
        vol2_cover = find_cover_image(MUSIC_ROOT / "Best Selection Songs 2004-2018(Vol.2)")
        if vol2_cover:
            return vol2_cover

    return None


def get_or_create_thumbnail(album_name: str, cover_path: Optional[Path]) -> Optional[Path]:
    if not cover_path or not cover_path.exists():
        return None
    thumb_dir = TEMP_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/*?:"<>|]', "", album_name).strip() or "cover"
    thumb_path = thumb_dir / f"{safe_name}.jpg"

    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        return thumb_path

    try:
        img = Image.open(cover_path).convert("RGB")
        img.thumbnail((320, 320), Image.Resampling.LANCZOS)
        img.save(thumb_path, "JPEG", quality=85)
        return thumb_path
    except Exception as e:
        logger.warning(f"生成缩略图失败: {album_name}, {e}")
        return None


def compress_to_mp3(src_file: Path, dst_file: Path) -> bool:
    if dst_file.exists() and dst_file.stat().st_size > 0:
        return True
    cmd = [
        FFMPEG_EXE,
        "-y",
        "-i", str(src_file),
        "-codec:a", "libmp3lame",
        "-b:a", "320k",
        str(dst_file)
    ]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return dst_file.exists() and dst_file.stat().st_size > 0
    except Exception as e:
        logger.error(f"FFmpeg 转码失败: {src_file.name}, 错误: {e}")
        return False


async def clean_channel_history(bot: Bot):
    print("🧹 正在执行频道历史消息一键清理...")
    all_ids = list(range(1, 1500))
    for i in range(0, len(all_ids), 100):
        batch = all_ids[i:i + 100]
        try:
            await bot.delete_messages(chat_id=CHANNEL_ID, message_ids=batch)
        except Exception:
            pass
        await asyncio.sleep(0.3)
    print("✅ 频道历史消息清理完成！")


async def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("❌ 未检测到 BOT_TOKEN 或 CHANNEL_ID！")
        return

    session = AiohttpSession(timeout=300.0)
    bot = Bot(token=BOT_TOKEN, session=session)
    db = MusicDatabase(DB_PATH)

    # 1. 清空频道与数据库
    await clean_channel_history(bot)
    with db._get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS songs")
        conn.commit()
    db._init_db()
    print("🗑️ 数据库表已彻底重建。严格按真实专辑物理文件一一对应同步！")

    # 2. 收集并对全部 32 张专辑排序
    album_tasks = []
    for folder_name, cfg in ALBUM_CONFIGS.items():
        folder_path = MUSIC_ROOT / folder_name
        if not folder_path.exists():
            continue

        audio_files = []
        for root_dir, _, files in os.walk(folder_path):
            for f in sorted(files):
                if f.lower().endswith((".flac", ".mp3", ".m4a", ".wav", ".ogg")):
                    audio_files.append(Path(root_dir) / f)

        audio_files.sort(key=lambda x: x.name)
        if not audio_files:
            continue

        cover_img = get_or_create_cover(folder_path, cfg["name"])
        album_tasks.append({
            "folder": folder_path,
            "name": cfg["name"],
            "year": cfg["year"],
            "cover": cover_img,
            "files": audio_files
        })

    # 严格按发行年份升序排序 (2004 -> 2024)
    album_tasks.sort(key=lambda x: (x["year"], x["name"]))

    total_albums = len(album_tasks)
    total_tracks = sum(len(a["files"]) for a in album_tasks)

    print("=" * 70)
    print(f"🎸 李志全系唱片编年史物理归正同步服务")
    print(f"💿 待发布专辑: {total_albums} 张 (2004 — 2024)")
    print(f"🎵 待发布曲目: {total_tracks} 首全集 (原版原声逐首归真)")
    print("=" * 70)

    track_global_idx = 0
    uploaded_count = 0

    for a_idx, album in enumerate(album_tasks, 1):
        album_name = album["name"]
        year = album["year"]
        cover_img = album["cover"]
        files = album["files"]
        year_str = f"{year}年"

        print(f"\n" + "-" * 70)
        print(f"💿 [{a_idx:02d}/{total_albums}] 正在发布专辑：《{album_name}》 ({year_str}, 共 {len(files)} 首歌)")
        print("-" * 70)

        # 1. 生成曲目预览列表 (前 20 首)
        preview_lines = []
        for i, f in enumerate(files[:20], 1):
            t_name, _, _, dur, _ = get_audio_info(f, album)
            m, s = divmod(dur, 60)
            dur_str = f" {m:02d}:{s:02d}" if dur else ""
            preview_lines.append(f"{i:02d}. {t_name}{dur_str}")
        if len(files) > 20:
            preview_lines.append(f"... 等共 {len(files)} 首")

        tracklist_preview = "\n".join(preview_lines)
        # 清除所有破坏 markdown 实体的字符与下划线
        clean_tag = re.sub(r'[\s\-_《》\(\)“”、/]+', '', album_name)

        header_text = (
            f"💿 ━━━━━━━━━━━━━━━━━━━\n"
            f"💿 **专辑：《{album_name}》**\n"
            f"📅 发行年份：{year_str}\n"
            f"🎸 歌手：李志\n"
            f"🎵 曲目数：共收录 {len(files)} 首歌曲\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 **曲目列表：**\n"
            f"{tracklist_preview}\n\n"
            f"#李志 #{clean_tag} #{year_str}"
        )

        album_header_msg_id = None
        for attempt in range(1, 4):
            try:
                if cover_img and cover_img.exists():
                    try:
                        h_msg = await bot.send_photo(
                            chat_id=CHANNEL_ID,
                            photo=FSInputFile(str(cover_img)),
                            caption=header_text,
                            parse_mode="Markdown"
                        )
                    except Exception:
                        h_msg = await bot.send_photo(
                            chat_id=CHANNEL_ID,
                            photo=FSInputFile(str(cover_img)),
                            caption=header_text,
                            parse_mode=None
                        )
                else:
                    h_msg = await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=header_text,
                        parse_mode="Markdown"
                    )
                album_header_msg_id = h_msg.message_id
                print(f"✨ 专辑门面海报发送成功 (MsgID: {album_header_msg_id})")
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                logger.warning(f"发送专辑海报重试 ({attempt}): {e}")
                await asyncio.sleep(2)

        await asyncio.sleep(1.5)

        thumb_path = get_or_create_thumbnail(album_name, cover_img)
        thumb_input = FSInputFile(str(thumb_path)) if thumb_path else None

        # 2. 依次物理发送该专辑真实音频文件
        for f_idx, f_path in enumerate(files, 1):
            track_global_idx += 1
            title, _, performer, duration, t_year = get_audio_info(f_path, album)

            caption = (
                f"🎵 歌曲：{title}\n"
                f"💿 专辑：《{album_name}》\n"
                f"📅 发行年份：{year_str}\n"
                f"🎸 歌手：{performer}\n\n"
                f"#李志 #{clean_tag} #{year_str}"
            )

            file_size = f_path.stat().st_size
            file_to_send = f_path
            need_cleanup = False

            if file_size > MAX_BOT_FILE_SIZE:
                converted = TEMP_DIR / f"{f_path.stem}.mp3"
                print(f"  ⚙️ [{f_idx:02d}/{len(files)}] 正在转码 320k MP3 ({file_size/(1024*1024):.1f}MB): {title} ...")
                if compress_to_mp3(f_path, converted):
                    file_to_send = converted
                    need_cleanup = True
                else:
                    print(f"  ❌ 转码失败，跳过: {f_path.name}")
                    continue

            audio_in = FSInputFile(str(file_to_send), filename=f"{title}{file_to_send.suffix}")
            size_mb = file_to_send.stat().st_size / (1024 * 1024)
            print(f"  ⬆️ [{f_idx:02d}/{len(files)}] 上传中 ({size_mb:.1f}MB): {title} ...", flush=True)

            sent_msg = None
            for attempt in range(1, 4):
                try:
                    sent_msg = await bot.send_audio(
                        chat_id=CHANNEL_ID,
                        audio=audio_in,
                        title=title,
                        performer=performer,
                        duration=duration or None,
                        caption=caption,
                        thumbnail=thumb_input
                    )
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except Exception as e:
                    await asyncio.sleep(2)

            if need_cleanup and file_to_send.exists():
                try:
                    file_to_send.unlink()
                except Exception:
                    pass

            if sent_msg:
                audio = sent_msg.audio or sent_msg.document
                db.add_or_update_song(
                    title=title,
                    performer=performer,
                    album=album_name,
                    duration=getattr(audio, "duration", duration) or 0,
                    channel_id=str(CHANNEL_ID),
                    message_id=sent_msg.message_id,
                    file_id=audio.file_id,
                    file_unique_id=audio.file_unique_id,
                    file_name=f_path.name,
                    year=year
                )
                uploaded_count += 1
                pct = (track_global_idx / total_tracks) * 100
                print(f"  ✅ [{track_global_idx:03d}/{total_tracks}] ({pct:4.1f}%) 入库: {title} (MsgID: {sent_msg.message_id})")

            # 歌曲间隔
            await asyncio.sleep(1.8)

        # 专辑之间休眠 2.0 秒
        await asyncio.sleep(2.0)

    print("\n" + "=" * 70)
    print("🎉 李志全系唱片编年史真实全量发布圆满完成！")
    print(f"✨ 成功入库真实歌曲: {uploaded_count} 首")
    stats = db.get_stats()
    print(f"📊 当前曲库总计: {stats['songs']} 首歌曲，{stats['albums']} 张专辑")
    print("=" * 70)

    # 生成置顶编年史索引
    print("📌 正在生成频道置顶总目录...")
    from create_pinned_index import post_and_pin_index
    await post_and_pin_index()

    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

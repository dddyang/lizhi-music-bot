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

from PIL import Image
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from aiogram.types import FSInputFile
from mutagen import File as MutagenFile

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("AutoUploader")

MUSIC_ROOT = Path(r"Z:\音乐\李志")
TEMP_DIR = Path(__file__).resolve().parent / ".temp_audio"
FFMPEG_PATH = Path(r"D:\AI\剪映\JianyingPro\11.5.3.14501\ffmpeg.exe")

# 50MB 阈值 (Telegram Bot API 上传限制)
MAX_BOT_FILE_SIZE = 49 * 1024 * 1024

# 李志官方唱片编年史与发行年份对照表
ALBUM_YEARS = {
    "被禁忌的游戏": 2004,
    "梵高先生": 2005,
    "这个世界会好吗": 2006,
    "我爱南京": 2009,
    "二零零九年十月十六日事件": 2009,
    "工体东路没有人": 2009,
    "你好 郑州": 2010,
    "你好，郑州": 2010,
    "义乌隔壁酒吧": 2010,
    "杂选": 2010,
    "8": 2011,
    "《8》": 2011,
    "F": 2011,
    "《F》": 2011,
    "杭州酒球会一身酒气": 2011,
    "Imagine Live": 2012,
    "挺”不插电巡演 郑州站": 2012,
    "108个关键词": 2013,
    "勾三搭四": 2014,
    "李志 1701": 2014,
    "1701": 2014,
    "I O": 2014,
    "I/O": 2014,
    "动静（2015Live）": 2015,
    "看见  李志2015巡回演唱会": 2015,
    "李志LIVE精选": 2015,
    "金城兰州": 2015,
    "在每一条伤心的应天大街上": 2016,
    "李志北京不插电现场 2016 Live": 2016,
    "李志、电声与管弦乐": 2016,
    "爵士乐与不插电新编12首": 2017,
    "李志、电声与管弦乐II": 2018,
    "Best Selection Songs 2004-2018": 2018,
    "Best Selection Songs 2004-2018(Vol.2)": 2018,
    "Best Selection Songs 2004-2018(Vol.3)": 2018,
    "best Selection Songs 2004-2019(Vol.1)": 2019,
    "洗心革面 跨年音乐会": 2019,
    "lz...THREE MISSING ONE(叁缺壹) JAPAN Tour 2024 in Tokyo wav": 2024,
}


def clean_title_from_filename(filename: str) -> str:
    """如果文件没有内嵌标签，从文件名智能提取歌名"""
    stem = Path(filename).stem
    stem = re.sub(r"^\d{1,3}[\.\s\-_]+", "", stem)
    return stem.strip() or filename


def get_audio_info(file_path: Path, album_folder: str) -> Tuple[str, str, str, int, Optional[int]]:
    """提取音频的标题、专辑、歌手、时长、发行年份"""
    title, album, performer, duration, year = None, None, "李志", 0, None
    try:
        tag = MutagenFile(str(file_path), easy=True)
        if tag:
            title = tag.get("title", [None])[0]
            album = tag.get("album", [None])[0]
            performer = tag.get("artist", [None])[0] or "李志"
            raw_date = tag.get("date", [None])[0] or tag.get("year", [None])[0]
            if raw_date:
                m = re.search(r"\b(19\d\d|20\d\d)\b", str(raw_date))
                if m:
                    year = int(m.group(1))
            if tag.info and hasattr(tag.info, "length"):
                duration = int(tag.info.length)
    except Exception:
        pass

    if not title:
        title = clean_title_from_filename(file_path.name)
    if not album or album.strip().lower() in ["", "none", "unknown"]:
        album = album_folder.strip().strip("《》")

    if not year:
        clean_alb = album.strip().strip("《》")
        year = ALBUM_YEARS.get(clean_alb) or ALBUM_YEARS.get(album_folder.strip().strip("《》")) or 2010

    return title.strip(), album.strip(), performer.strip(), duration, year


def get_raw_cover_image(album_dir: Path) -> Optional[Path]:
    """从专辑目录查找原始大尺寸封面图片"""
    for pattern in ["cover.jpg", "Cover.jpg", "cover.png", "Cover.png", "folder.jpg", "*.jpg", "*.png"]:
        matches = list(album_dir.glob(pattern))
        if matches:
            return matches[0]
    return None


def get_or_create_thumbnail(album_dir: Path, audio_file: Path) -> Optional[Path]:
    """生成 Telegram 标准音频缩略图 (320x320 JPEG)"""
    thumb_dir = TEMP_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/*?:"<>|]', "", album_dir.name).strip() or "cover"
    thumb_path = thumb_dir / f"{safe_name}.jpg"

    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        return thumb_path

    raw_cover = get_raw_cover_image(album_dir)
    img = None
    if raw_cover:
        try:
            img = Image.open(raw_cover)
        except Exception:
            pass

    # 尝试从音频内嵌标签读取
    if img is None:
        try:
            m_file = MutagenFile(str(audio_file))
            if m_file:
                if hasattr(m_file, "pictures") and m_file.pictures:
                    img = Image.open(io.BytesIO(m_file.pictures[0].data))
                elif hasattr(m_file, "tags") and m_file.tags:
                    for tag_key in m_file.tags.keys():
                        if tag_key.startswith("APIC:"):
                            img = Image.open(io.BytesIO(m_file.tags[tag_key].data))
                            break
        except Exception:
            pass

    if img:
        try:
            img = img.convert("RGB")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            img.save(thumb_path, "JPEG", quality=85)
            return thumb_path
        except Exception as e:
            logger.warning(f"生成缩略图失败: {album_dir.name}, err: {e}")

    return None


def compress_to_mp3(src_file: Path, dst_file: Path) -> bool:
    """使用本地 ffmpeg 将超过 50MB 的超大文件转为 320k 高音质 MP3"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(FFMPEG_PATH),
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


async def upload_all():
    if not BOT_TOKEN:
        print("❌ 未检测到 BOT_TOKEN，请检查 .env 文件！")
        return
    if not CHANNEL_ID:
        print("❌ 未检测到 CHANNEL_ID，请检查 .env 文件！")
        return
    if not MUSIC_ROOT.exists():
        print(f"❌ 音乐目录不存在: {MUSIC_ROOT}")
        return

    db = MusicDatabase(DB_PATH)
    session = AiohttpSession(timeout=300.0)
    bot = Bot(token=BOT_TOKEN, session=session)

    # 1. 扫描全部专辑目录
    album_groups = []
    for album_dir in sorted(MUSIC_ROOT.iterdir()):
        if not album_dir.is_dir():
            continue
        audio_files = sorted([
            f for f in album_dir.iterdir()
            if f.is_file() and f.suffix.lower() in [".flac", ".mp3", ".m4a", ".wav", ".ogg"]
        ])
        if not audio_files:
            continue

        # 抽样第1首获取专辑名与年份
        _, sample_album, _, _, sample_year = get_audio_info(audio_files[0], album_dir.name)
        album_groups.append({
            "dir": album_dir,
            "album_name": sample_album,
            "year": sample_year,
            "files": audio_files
        })

    # 按年份年代升序排序（从2004早期到2024巡演，打造唯美时光之旅）
    album_groups.sort(key=lambda x: (x["year"] or 9999, x["album_name"]))

    total_albums = len(album_groups)
    total_tracks = sum(len(g["files"]) for g in album_groups)

    print("=" * 70)
    print(f"🎸 李志音乐全量同步服务 (按专辑聚合版)")
    print(f"🎯 目标频道: {CHANNEL_ID}")
    print(f"💿 待同步专辑: {total_albums} 张")
    print(f"🎵 待同步曲目: {total_tracks} 首 (按 2004-2024 年代顺序列队)")
    print("=" * 70)

    track_global_idx = 0
    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    album_nav_links = []

    for a_idx, group in enumerate(album_groups, 1):
        album_name = group["album_name"]
        year = group["year"]
        album_dir = group["dir"]
        files = group["files"]
        year_str = f"{year}年" if year else "经典年份"

        print(f"\n" + "-" * 70)
        print(f"💿 [{a_idx:02d}/{total_albums}] 正在处理专辑：《{album_name}》 ({year_str}, 共 {len(files)} 首歌)")
        print("-" * 70)

        # 检查该专辑是否已经全部上传过
        all_already_in_db = all(
            db.has_song(get_audio_info(f, album_dir.name)[0], album_name)
            for f in files
        )

        album_header_msg_id = None

        # 发送该专辑的「门面大海报 / 专栏公告卡片」
        if not all_already_in_db:
            # 格式化曲目清单列表预览 (前 15 首)
            track_preview_lines = []
            for i, f in enumerate(files[:15], 1):
                t_name, _, _, dur, _ = get_audio_info(f, album_dir.name)
                m, s = divmod(dur, 60)
                dur_str = f"{m:02d}:{s:02d}" if dur else ""
                track_preview_lines.append(f"{i:02d}. {t_name} {dur_str}")
            if len(files) > 15:
                track_preview_lines.append(f"... 等共 {len(files)} 首")

            tracklist_preview = "\n".join(track_preview_lines)

            header_text = (
                f"💿 ━━━━━━━━━━━━━━━━━━━\n"
                f"💿 专辑：《{album_name}》\n"
                f"📅 发行年份：{year_str}\n"
                f"🎸 歌手：李志\n"
                f"🎵 曲目数：共收录 {len(files)} 首\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📋 **曲目列表：**\n"
                f"{tracklist_preview}\n\n"
                f"#李志 #{album_name.replace(' ', '_').replace('《', '').replace('》', '')} #{year_str}"
            )

            raw_cover = get_raw_cover_image(album_dir)
            try:
                if raw_cover:
                    # 发送专辑大封面图
                    h_msg = await bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=FSInputFile(str(raw_cover)),
                        caption=header_text,
                        parse_mode="Markdown"
                    )
                else:
                    h_msg = await bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=header_text,
                        parse_mode="Markdown"
                    )
                album_header_msg_id = h_msg.message_id
                print(f"✨ 专辑专区门面海报已送达 (MsgID: {album_header_msg_id})")
                await asyncio.sleep(2.0)
            except Exception as e:
                logger.warning(f"发送专辑海报出错: {e}")

        # 依次发送该专辑的曲目
        for f_idx, file_path in enumerate(files, 1):
            track_global_idx += 1
            title, _, performer, duration, t_year = get_audio_info(file_path, album_dir.name)
            file_size = file_path.stat().st_size

            # 断点续传检查
            if db.has_song(title, album_name):
                skipped_count += 1
                print(f" [{track_global_idx:03d}/{total_tracks}] ⏩ 已收录跳过: 《{album_name}》 - {title}")
                continue

            file_to_send = file_path
            need_cleanup = False

            # > 49MB 自动转码
            if file_size > MAX_BOT_FILE_SIZE:
                print(f" [{track_global_idx:03d}/{total_tracks}] ⚙️ 文件较大 ({file_size / (1024*1024):.1f}MB)，转码 320k MP3...")
                converted_file = TEMP_DIR / f"{file_path.stem}.mp3"
                if compress_to_mp3(file_path, converted_file):
                    file_to_send = converted_file
                    need_cleanup = True
                else:
                    print(f" [{track_global_idx:03d}/{total_tracks}] ❌ 转码失败，跳过: {file_path.name}")
                    failed_count += 1
                    continue

            success = False
            clean_tag = album_name.replace(' ', '_').replace('《', '').replace('》', '')
            caption = (
                f"🎵 歌曲：{title}\n"
                f"💿 专辑：《{album_name}》\n"
                f"📅 发行年份：{year_str}\n"
                f"🎸 歌手：{performer}\n\n"
                f"#李志 #{clean_tag} #{year_str}"
            )

            thumb_path = get_or_create_thumbnail(album_dir, file_path)
            thumb_input = FSInputFile(str(thumb_path)) if thumb_path else None

            print(f" [{track_global_idx:03d}/{total_tracks}] ⬆️ 上传 ({file_size / (1024*1024):.1f}MB): [{f_idx:02d}/{len(files)}] {title} ...", flush=True)

            for attempt in range(1, 4):
                try:
                    audio_input = FSInputFile(str(file_to_send), filename=f"{title}{file_to_send.suffix}")
                    msg = await bot.send_audio(
                        chat_id=CHANNEL_ID,
                        audio=audio_input,
                        title=title,
                        performer=performer,
                        duration=duration or None,
                        caption=caption,
                        thumbnail=thumb_input
                    )

                    audio = msg.audio or msg.document
                    db.add_or_update_song(
                        title=title,
                        performer=performer,
                        album=album_name,
                        duration=getattr(audio, "duration", duration) or 0,
                        channel_id=str(CHANNEL_ID),
                        message_id=msg.message_id,
                        file_id=audio.file_id,
                        file_unique_id=audio.file_unique_id,
                        file_name=file_path.name,
                        year=year
                    )

                    uploaded_count += 1
                    pct = (track_global_idx / total_tracks) * 100
                    print(f" [{track_global_idx:03d}/{total_tracks}] ({pct:4.1f}%) ✅ 成功入库: {title} (MsgID: {msg.message_id})")
                    success = True
                    break

                except TelegramRetryAfter as e:
                    wait_sec = e.retry_after + 1
                    print(f"⏳ 触发 Telegram 频控，自动休息 {wait_sec} 秒后重试...")
                    await asyncio.sleep(wait_sec)
                except Exception as e:
                    print(f"⚠️ 第 {attempt} 次上传出错 ({e})，2秒后重试...")
                    await asyncio.sleep(2)

            if not success:
                failed_count += 1
                print(f"❌ 上传失败: 《{album_name}》 - {title}")

            if need_cleanup and file_to_send.exists():
                try:
                    file_to_send.unlink()
                except Exception:
                    pass

            # 歌曲之间平稳间隔 2.5 秒
            await asyncio.sleep(2.5)

        # 专辑之间缓冲 3 秒
        await asyncio.sleep(3.0)

    print("\n" + "=" * 70)
    print("🎉 李志全套曲库自动化同步流程圆满完成！")
    print(f"✨ 成功上传歌曲: {uploaded_count} 首")
    print(f"⏩ 跳过已存在: {skipped_count} 首")
    stats = db.get_stats()
    print(f"📊 当前曲库总计: {stats['songs']} 首歌曲，{stats['albums']} 张专辑")
    print("=" * 70)

    await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(upload_all())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 用户手动中止上传。再次运行脚本可从断点继续！")

import asyncio
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile, LinkPreviewOptions
import mutagen
from mutagen.mp3 import MP3

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase
from lyrics_bank import get_lyrics

ALBUM_DIR = Path(r"Z:\音乐\李志\我们也爱南京")
COVER_PATH = ALBUM_DIR / "Cover.jpg"
ALBUM_NAME = "我们也爱南京"
YEAR = 2011
YEAR_STR = f"{YEAR}年"


async def main():
    bot = Bot(token=BOT_TOKEN)
    db = MusicDatabase(DB_PATH)

    files = sorted(ALBUM_DIR.glob("*.mp3"))
    print(f"🎵 找到 {len(files)} 首待上传曲目...")

    # 1. 提取各曲目时长和标题
    track_info = []
    preview_lines = []
    for idx, f in enumerate(files, 1):
        try:
            audio = MP3(f)
            dur = int(audio.info.length)
        except Exception:
            dur = 0
        
        # 提取标题
        title = f.stem
        if title[:3].replace(".", "").isdigit():
            title = title[4:].strip()
            
        m, s = divmod(dur, 60)
        dur_str = f" {m:02d}:{s:02d}" if dur else ""
        preview_lines.append(f"{idx:02d}. {title}{dur_str}")
        track_info.append((f, title, dur))

    tracklist_preview = "\n".join(preview_lines)
    clean_tag = re.sub(r'[\s\-_《》\(\)“”、/]+', '', ALBUM_NAME)

    header_text = (
        f"💿 ━━━━━━━━━━━━━━━━━━━\n"
        f"💿 **专辑：《{ALBUM_NAME}》**\n"
        f"📅 发行年份：{YEAR_STR}\n"
        f"🎸 歌手：李志\n"
        f"🎵 曲目数：共收录 {len(files)} 首歌曲\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 **曲目列表：**\n"
        f"{tracklist_preview}\n\n"
        f"#李志 #{clean_tag} #{YEAR_STR}"
    )

    # 2. 发送专辑门面海报
    print("正在发送《我们也爱南京》门面海报...")
    cover_msg_id = None
    while True:
        try:
            msg = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=FSInputFile(str(COVER_PATH)),
                caption=header_text,
                parse_mode="Markdown"
            )
            cover_msg_id = msg.message_id
            print(f"✅ 专辑门面海报发送成功 (MsgID: {cover_msg_id})")
            break
        except TelegramRetryAfter as e:
            print(f"⚠️ 频控限速，等待 {e.retry_after} 秒...")
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            print(f"⚠️ 降级纯文本发送海报 ({e})...")
            msg = await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=FSInputFile(str(COVER_PATH)),
                caption=header_text,
                parse_mode=None
            )
            cover_msg_id = msg.message_id
            print(f"✅ 专辑门面海报发送成功 (MsgID: {cover_msg_id})")
            break

    await asyncio.sleep(2)

    # 3. 逐首上传音频文件并入库
    thumb_input = FSInputFile(str(COVER_PATH)) if COVER_PATH.exists() else None

    for idx, (f_path, title, duration) in enumerate(track_info, 1):
        caption = (
            f"🎵 歌曲：{title}\n"
            f"💿 专辑：《{ALBUM_NAME}》\n"
            f"📅 发行年份：{YEAR_STR}\n"
            f"🎸 歌手：李志\n\n"
            f"#李志 #{clean_tag} #{YEAR_STR}"
        )

        print(f"[{idx}/{len(track_info)}] 正在上传: {f_path.name} ({f_path.stat().st_size/1024/1024:.2f} MB)...")
        while True:
            try:
                audio_msg = await bot.send_audio(
                    chat_id=CHANNEL_ID,
                    audio=FSInputFile(str(f_path)),
                    title=title,
                    performer="李志",
                    duration=duration or None,
                    caption=caption,
                    thumbnail=thumb_input
                )
                
                # 入库 SQLite
                lyrics = get_lyrics(title)
                db.upsert_song(
                    title=title,
                    performer="李志",
                    album=ALBUM_NAME,
                    year=YEAR,
                    duration=duration,
                    channel_id=CHANNEL_ID,
                    message_id=audio_msg.message_id,
                    file_id=audio_msg.audio.file_id,
                    file_unique_id=audio_msg.audio.file_unique_id,
                    file_name=f_path.name,
                    lyrics=lyrics
                )
                print(f"[{idx}/{len(track_info)}] ✅ 上传并入库成功 (MsgID: {audio_msg.message_id})")
                break
            except TelegramRetryAfter as e:
                print(f"⚠️ 频控限速，等待 {e.retry_after} 秒...")
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                print(f"❌ 上传失败 ({e})，3 秒后重试...")
                await asyncio.sleep(3)

        await asyncio.sleep(2)

    # 4. 重新生成并置顶全频道编年史索引导航
    print("\n正在更新置顶索引导航...")
    import sqlite3
    conn = sqlite3.connect("music.db")
    c = conn.cursor()
    c.execute("""
        SELECT album, year, MIN(message_id) as first_mid, count(*) as count 
        FROM songs 
        GROUP BY album 
        ORDER BY year ASC, 
                 CASE WHEN album = '洗心革面 跨年音乐会' THEN 0 ELSE 1 END,
                 album ASC
    """)
    rows = c.fetchall()

    lines = [
        "🎸 **李志音乐全集 · 唱片编年史索引导航**",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💡 *点击下方任意专辑名，可直达该专辑专区收听：*",
        ""
    ]

    for album, yr, mid, count in rows:
        target_mid = max(1, mid - 1)
        link = f"https://t.me/libimusic/{target_mid}"
        yr_str = f"{yr}年" if yr else "经典"
        clean_n = album.replace("[", "").replace("]", "")
        lines.append(f"• [{yr_str} 《{clean_n}》 ({count}首)]({link})")

    lines.append("")
    lines.append("🤖 **点播机器人**：[点击启动点播机器人](https://t.me/libi_music_bot)")
    lines.append("🔍 支持全库中英文、拼音缩写模糊搜索（如 `fgxs`、`郑州`）")

    full_index_text = "\n".join(lines)
    link_preview_opt = LinkPreviewOptions(is_disabled=True)

    # 发送新置顶消息到频道底部并置顶
    new_index_msg = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=full_index_text,
        parse_mode="Markdown",
        link_preview_options=link_preview_opt
    )
    await bot.pin_chat_message(chat_id=CHANNEL_ID, message_id=new_index_msg.message_id)
    print(f"✅ 全新置顶索引导航已生成并置顶于频道底部 (MsgID: {new_index_msg.message_id})！")

    conn.close()
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())

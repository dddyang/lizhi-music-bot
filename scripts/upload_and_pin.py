import asyncio
import re
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import FSInputFile, LinkPreviewOptions
from mutagen.mp3 import MP3

from config import BOT_TOKEN, CHANNEL_ID, DB_PATH
from database import MusicDatabase
from lyrics_bank import get_lyrics

ALBUM_DIR = Path(r"Z:\音乐\李志\我们也爱南京")
COVER_PATH = ALBUM_DIR / "Cover.jpg"
ALBUM_NAME = "我们也爱南京"
YEAR = 2011
YEAR_STR = f"{YEAR}年"
OLD_PINNED_MID = 1343

async def upload_album_and_repin():
    bot = Bot(token=BOT_TOKEN)
    db = MusicDatabase(DB_PATH)

    files = sorted(ALBUM_DIR.glob("*.mp3"))
    print(f"🎵 找到 {len(files)} 首待上传曲目...")

    # 1. 提取曲目信息
    track_info = []
    preview_lines = []
    for idx, f in enumerate(files, 1):
        try:
            audio = MP3(f)
            dur = int(audio.info.length)
        except Exception:
            dur = 0

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

    # 2. 发送专辑门面海报 (新封面)
    print("正在发送《我们也爱南京》官方真实门面海报...")
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

    await asyncio.sleep(3)

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
        audio_msg = None
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
                break
            except TelegramRetryAfter as e:
                print(f"⚠️ 频控限速，等待 {e.retry_after} 秒...")
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                print(f"❌ 上传异常 ({e})，等待 5 秒重试...")
                await asyncio.sleep(5)

        # 音频发送成功后，单独执行入库
        try:
            lyrics = get_lyrics(title)
            is_new, song_id = db.add_or_update_song(
                title=title,
                performer="李志",
                album=ALBUM_NAME,
                duration=duration,
                channel_id=str(CHANNEL_ID),
                message_id=audio_msg.message_id,
                file_id=audio_msg.audio.file_id,
                file_unique_id=audio_msg.audio.file_unique_id,
                file_name=f_path.name,
                year=YEAR,
                lyrics=lyrics
            )
            print(f"[{idx}/{len(track_info)}] ✅ 上传并入库成功 (MsgID: {audio_msg.message_id}, DB ID: {song_id})")
        except Exception as e:
            print(f"⚠️ 数据库入库记录异常: {e}")

        await asyncio.sleep(3)

    print("\n🎉 《我们也爱南京》全套曲目上传完毕！开始生成并置顶最新索引导航（置顶消息放最后）...")

    # 4. 生成最新的全频道编年史索引导航
    conn = sqlite3.connect(DB_PATH)
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

    for album, year, mid, count in rows:
        target_mid = max(1, mid - 1)
        link = f"https://t.me/libimusic/{target_mid}"
        year_str = f"{year}年" if year else "经典"
        clean_name = album.replace("[", "").replace("]", "")
        lines.append(f"• [{year_str} 《{clean_name}》 ({count}首)]({link})")

    lines.append("")
    lines.append("🤖 **点播机器人**：[点击启动点播机器人](https://t.me/libi_music_bot)")
    lines.append("🔍 支持全库中英文、拼音缩写模糊搜索（如 `fgxs`、`郑州`）")

    full_text = "\n".join(lines)
    link_preview_opt = LinkPreviewOptions(is_disabled=True)

    # 5. 删除/取消旧置顶消息 (1343)，并在最后发送全新索引并置顶
    try:
        print(f"正在清理旧置顶索引消息 (MsgID: {OLD_PINNED_MID})...")
        await bot.delete_message(chat_id=CHANNEL_ID, message_id=OLD_PINNED_MID)
        print("✅ 旧置顶索引消息已删除！")
    except Exception as e:
        print(f"处理旧置顶消息提示 ({e})")

    await asyncio.sleep(1)

    print("正在频道最底部发送全新编年史索引导航并置顶...")
    new_index_msg = await bot.send_message(
        chat_id=CHANNEL_ID,
        text=full_text,
        parse_mode="Markdown",
        link_preview_options=link_preview_opt
    )
    await bot.pin_chat_message(chat_id=CHANNEL_ID, message_id=new_index_msg.message_id)
    print(f"✅ 全新置顶索引已发送并成功置顶 (MsgID: {new_index_msg.message_id})，位于频道最后！")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(upload_album_and_repin())

import asyncio
import re
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from config import BOT_TOKEN, CHANNEL_ID


async def update_album_captions(bot: Bot, conn: sqlite3.Connection, album_name: str, new_year: int, cover_mid: int):
    c = conn.cursor()
    c.execute(
        "SELECT message_id, title, performer, duration FROM songs WHERE album = ? ORDER BY message_id",
        (album_name,)
    )
    tracks = c.fetchall()
    year_str = f"{new_year}年"
    clean_tag = re.sub(r'[\s\-_《》\(\)“”、/]+', '', album_name)

    # 1. 更新专辑封面 / Header Message
    preview_lines = []
    for idx, (_, title, _, dur) in enumerate(tracks, 1):
        dur_str = f"{dur//60:02d}:{dur%60:02d}" if dur else ""
        preview_lines.append(f"{idx:02d}. {title} {dur_str}")
    tracklist_preview = "\n".join(preview_lines)

    header_text = (
        f"💿 ━━━━━━━━━━━━━━━━━━━\n"
        f"💿 **专辑：《{album_name}》**\n"
        f"📅 发行年份：{year_str}\n"
        f"🎸 歌手：李志\n"
        f"🎵 曲目数：共收录 {len(tracks)} 首歌曲\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 **曲目列表：**\n"
        f"{tracklist_preview}\n\n"
        f"#李志 #{clean_tag} #{year_str}"
    )

    print(f"正在更新专辑 [{album_name}] 封面文案 (MsgID: {cover_mid}) 为 {year_str}...")
    while True:
        try:
            await bot.edit_message_caption(
                chat_id=CHANNEL_ID,
                message_id=cover_mid,
                caption=header_text,
                parse_mode="Markdown"
            )
            print(f"✅ 封面 MsgID {cover_mid} 更新成功！")
            break
        except TelegramRetryAfter as e:
            print(f"⚠️ Telegram 频控，等待 {e.retry_after} 秒...")
            await asyncio.sleep(e.retry_after + 1)
        except Exception as e:
            print(f"⚠️ 封面更新降级无 Markdown 重试 ({e})...")
            try:
                await bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=cover_mid,
                    caption=header_text,
                    parse_mode=None
                )
                print(f"✅ 封面 MsgID {cover_mid} (无格式) 更新成功！")
            except Exception as e2:
                print(f"❌ 封面更新失败: {e2}")
            break

    await asyncio.sleep(0.5)

    # 2. 逐一更新单曲文案
    for idx, (mid, title, performer, _) in enumerate(tracks, 1):
        caption = (
            f"🎵 歌曲：{title}\n"
            f"💿 专辑：《{album_name}》\n"
            f"📅 发行年份：{year_str}\n"
            f"🎸 歌手：{performer}\n\n"
            f"#李志 #{clean_tag} #{year_str}"
        )

        while True:
            try:
                await bot.edit_message_caption(
                    chat_id=CHANNEL_ID,
                    message_id=mid,
                    caption=caption,
                    parse_mode=None
                )
                print(f"[{idx}/{len(tracks)}] ✅ 单曲 MsgID {mid} ({title[:15]}...) 年份已更新为 {year_str}")
                break
            except TelegramRetryAfter as e:
                print(f"⚠️ 频控限速，等待 {e.retry_after} 秒...")
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:
                print(f"[{idx}/{len(tracks)}] ❌ 单曲 MsgID {mid} 更新失败: {e}")
                break

        await asyncio.sleep(0.3)


async def main():
    bot = Bot(token=BOT_TOKEN)
    conn = sqlite3.connect("music.db")

    # 更新 Vol.2 (2020年)
    await update_album_captions(
        bot=bot,
        conn=conn,
        album_name="Best Selection Songs 2004-2018 (Vol.2)",
        new_year=2020,
        cover_mid=1211
    )

    # 更新 Vol.3 (2021年)
    await update_album_captions(
        bot=bot,
        conn=conn,
        album_name="Best Selection Songs 2004-2018 (Vol.3)",
        new_year=2021,
        cover_mid=1232
    )

    conn.close()
    await bot.session.close()
    print("\n🎉 全部两张专辑封面及曲目消息已成功更新为最新官方年份！")


if __name__ == "__main__":
    asyncio.run(main())

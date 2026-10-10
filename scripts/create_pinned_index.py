import asyncio
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from aiogram import Bot
from aiogram.types import LinkPreviewOptions
from config import BOT_TOKEN, CHANNEL_ID

async def post_and_pin_index():
    bot = Bot(token=BOT_TOKEN)
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

    target_mid = 1402
    try:
        print(f"正在原地更新置顶索引导航 (MsgID: {target_mid})，并彻底关闭上方网页预览图...")
        await bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=target_mid,
            text=full_text,
            parse_mode="Markdown",
            link_preview_options=link_preview_opt
        )
        print(f"✅ 原地更新成功 (MsgID: {target_mid})，预览图已成功移除！")
    except Exception as e:
        print(f"原地编辑失败 ({e})，正在发送新消息并置顶...")
        msg = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=full_text,
            parse_mode="Markdown",
            link_preview_options=link_preview_opt
        )
        await bot.pin_chat_message(chat_id=CHANNEL_ID, message_id=msg.message_id)
        print(f"✅ 新消息发送并置顶成功 (MsgID: {msg.message_id})！")

    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(post_and_pin_index())


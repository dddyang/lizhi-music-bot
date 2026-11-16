# -*- coding: utf-8 -*-
"""智能文本搜索、群聊 Inline Query 与频道新曲实时自动入库监听"""

import logging
import re

from aiogram import Bot, F, Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from constants import get_album_tag
from hub import db, render_hub
from ui.cards import escape_md, truncate_title

logger = logging.getLogger("LiZhiMusicBot.Search")
router = Router(name="search_inline")


@router.channel_post(F.audio)
async def handle_channel_audio_post(message: Message):
    audio = message.audio
    if not audio:
        return

    title = audio.title or audio.file_name or "未知曲目"
    performer = audio.performer or "李志"
    album = "单曲 / 未归类"
    year = None
    if message.caption:
        album_match = re.search(r'💿\s*(?:\*\*)?专辑(?:\*\*)?[：:]\s*(?:`|《)?([^`》\n]+)(?:`|》)?', message.caption)
        if album_match:
            album = album_match.group(1).strip()
        year_match = re.search(r'📅\s*(?:\*\*)?演出年份(?:\*\*)?[：:]\s*(\d{4})', message.caption)
        if not year_match:
            year_match = re.search(r'(\d{4})\s*年', message.caption)
        if year_match:
            year = int(year_match.group(1))

    is_new, song_id = db.add_or_update_song(
        title=title,
        performer=performer,
        album=album,
        duration=audio.duration or 0,
        channel_id=str(message.chat.id),
        message_id=message.message_id,
        file_id=audio.file_id,
        file_unique_id=audio.file_unique_id,
        file_name=audio.file_name,
        year=year
    )
    status_txt = "新增收录" if is_new else "更新记录"
    logger.info(f"📻 [频道自动同步] {status_txt}: 《{title}》 - 专辑: 《{album}》 (ID: {song_id})")


@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery):
    q = inline_query.query.strip()
    results = []

    if q:
        video_matches = db.search_videos(q, limit=6)
    else:
        video_matches = db.search_videos("跨年", limit=2) + db.search_videos("吉隆坡", limit=2)

    for v in video_matches:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        dur_str = v.get("duration_str") or "完整实况"
        size_mb = v.get("size_mb", 0.0)
        size_str = f"{size_mb:.1f} MB" if size_mb else "高清流媒体"
        video_link = f"https://t.me/libimusic/{v['message_id']}"

        card_text = (
            f"🎬 **李志现场高清原画视频 ·《{escape_md(v['title'])}》**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📅 演出年份：`{v.get('year', '经典')}年`\n"
            f"📂 视频分类：`{escape_md(v.get('category', '官方现场'))}`\n"
            f"⏳ 现场时长：`{dur_str}`\n"
            f"💾 视频规格：`{size_str}` (免下载在线秒播)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"▶️ [点击直接在官方频道观看原画大片]({video_link})\n"
            f"🎸 随身硬核点播：@libi_music_bot"
        )

        results.append(
            InlineQueryResultArticle(
                id=f"vid_{v['id']}",
                title=f"🎬 影音原画：{year_str}{v['title']}",
                description=f"📂 {v['category']} | ⏳ {dur_str} | 💾 {size_str}",
                input_message_content=InputTextMessageContent(
                    message_text=card_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                ),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="▶️ 观看高清原画大片", url=video_link),
                    InlineKeyboardButton(text="🎸 点播更多李志", url="https://t.me/libi_music_bot")
                ]])
            )
        )

    song_matches = db.search_songs(q, limit=16) if q else db.get_random_songs(limit=8)
    for s in song_matches:
        year_str = f" [{s['year']}年]" if s.get("year") else ""
        tag = get_album_tag(s["album"])
        tag_str = f" {tag}" if tag else ""
        quality_badge = db.get_song_quality_tag(s)

        results.append(
            InlineQueryResultCachedAudio(
                id=f"aud_{s['id']}",
                audio_file_id=s["file_id"],
                caption=f"🎵 {s['title']} - 《{s['album']}》{year_str}{tag_str} `{quality_badge}` | 李志",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🎸 开启李志随身点播站", url="https://t.me/libi_music_bot")
                ]])
            )
        )

    cache_duration = 30 if q else 10
    await inline_query.answer(results, cache_time=cache_duration, is_personal=False)


@router.message(F.chat.type == "private", F.text)
async def handle_search(message: Message, bot: Bot):
    """兜底文本搜索路由：匹配歌名、拼音、歌词与原画大片"""
    user_id = message.from_user.id
    query_text = message.text.strip()
    if query_text.startswith("/"):
        return

    safe_query = escape_md(query_text)
    video_results = db.search_videos(query_text, limit=4)
    song_results = db.search_songs(query_text, limit=8)

    builder = InlineKeyboardBuilder()
    if not video_results and not song_results:
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        fail_text = (
            f"🔍 抱歉，曲库与影音库中未找到与「`{safe_query}`」相关的内容。\n"
            f"你可以尝试输入歌名、视频标题关键字或拼音缩写（如 `跨年`、`fgxs`、`夜话`、`郑州`、`tkzc`）。"
        )
        await render_hub(bot, message.chat.id, user_id, fail_text, builder.as_markup())
        return

    for v in video_results:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        builder.row(
            InlineKeyboardButton(
                text=f"🎬 {year_str}{truncate_title(v['title'], 28)}",
                callback_data=f"vdetail:{v['id']}::0"
            )
        )

    lyric_hits_shown = []
    for s in song_results:
        year_str = f"[{s['year']}年] " if s.get("year") else ""
        tag = get_album_tag(s["album"])
        tag_str = f" {tag}" if tag else ""
        s_title = truncate_title(s["title"], 26)

        prefix = "🎵"
        if s.get("lyric_snippet"):
            prefix = "📝 🎵"
            lyric_hits_shown.append(f"• **《{s['title']}》**：_{s['lyric_snippet']}_")

        builder.row(
            InlineKeyboardButton(
                text=f"{prefix} {year_str}{s_title} - 《{s['album']}》{tag_str}",
                callback_data=f"play:{s['id']}"
            )
        )

    builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))

    stats_parts = []
    if video_results:
        stats_parts.append(f"`{len(video_results)}` 部影音视频")
    if song_results:
        stats_parts.append(f"`{len(song_results)}` 首单曲")

    reply_lines = [
        f"🔍 找到与「`{safe_query}`」相关的 {' 和 '.join(stats_parts)}：",
        "━━━━━━━━━━━━━━━━━━━"
    ]
    if lyric_hits_shown:
        reply_lines.append("📝 **歌词逆向命中发现**：")
        reply_lines.extend(lyric_hits_shown[:3])
        reply_lines.append("━━━━━━━━━━━━━━━━━━━")
    reply_lines.append("💡 影音视频支持一键原画播放，单曲点击即刻点播：")
    await render_hub(bot, message.chat.id, user_id, "\n".join(reply_lines), builder.as_markup())

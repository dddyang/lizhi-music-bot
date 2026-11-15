# -*- coding: utf-8 -*-
"""音乐点播核心：分类浏览、随缘一曲、原地切歌、歌词折叠与版本切换"""

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaAudio
from aiogram.utils.keyboard import InlineKeyboardBuilder

from constants import (
    BOOTLEG_AND_FAN_ALBUMS,
    CAT_LABELS,
    CAT_TITLES,
    JAPAN_ALBUMS,
    OFFICIAL_LIVE_ALBUMS,
    STUDIO_ALBUMS,
    get_album_desc,
    get_album_tag,
)
from hub import (
    SEND_ALL_COOLDOWN,
    _safe_delete,
    _safe_delete_msg,
    db,
    get_active_hub_mid,
    get_user_last_cat,
    render_hub,
    set_active_hub_mid,
    set_user_last_cat,
)
from mood_quotes import get_song_exact_quote
from ui.cards import (
    build_albums_markup_by_filter,
    build_lyrics_caption,
    build_song_caption,
    format_duration,
    get_song_control_markup,
    get_versions_markup,
)

logger = logging.getLogger("LiZhiMusicBot.Music")
router = Router(name="music")


@router.callback_query(F.data == "random:track")
async def cb_random_track(query: CallbackQuery, bot: Bot):
    song = db.get_random_song()
    if not song:
        await query.answer("曲库为空", show_alert=True)
        return

    quote = get_song_exact_quote(song["title"], song.get("lyrics"))
    year_str = f" [{song['year']}年]" if song.get("year") else ""
    tag = get_album_tag(song["album"])
    tag_str = f" {tag}" if tag else ""
    channel_url = f"https://t.me/libimusic/{song['message_id']}" if song.get("message_id") else "https://t.me/libimusic"

    text = (
        "🎲 **随缘一曲 · 逼哥盲盒**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"🎵 **《{song['title']}》**\n"
        f"💿 收录于：**《{song['album']}》**{year_str}{tag_str}\n\n"
        f"💬 _「{quote}」_\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 缘分到了就听这首，点击下方按钮即刻聆听："
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="▶️ 立即点播这首歌", callback_data=f"play:{song['id']}"),
        InlineKeyboardButton(text="🎲 再换一首", callback_data="random:track")
    )
    builder.row(
        InlineKeyboardButton(text="🎧 在频道中沉浸播放本专辑", url=channel_url),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(query: CallbackQuery, bot: Bot):
    cat = query.data.split("cat:", 1)[1]
    set_user_last_cat(query.from_user.id, cat)
    title_text = CAT_TITLES.get(cat, "💿 **请选择你想收听的专辑：**")
    markup = build_albums_markup_by_filter(cat)
    await render_hub(bot, query.message.chat.id, query.from_user.id, title_text, markup, query=query)


@router.callback_query(F.data.startswith("album:"))
async def cb_album_detail(query: CallbackQuery, bot: Bot):
    album_name = query.data.split("album:", 1)[1]
    tracks = db.get_songs_by_album(album_name)
    if not tracks:
        await query.answer("未找到该专辑曲目", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    first_track = tracks[0]
    channel_url = f"https://t.me/libimusic/{first_track['message_id']}" if first_track.get("message_id") else "https://t.me/libimusic"
    builder.row(
        InlineKeyboardButton(text="🎧 在频道中沉浸顺序连播", url=channel_url),
        InlineKeyboardButton(text=f"📦 私聊连播全部{len(tracks)}首", callback_data=f"send_all:{album_name}")
    )

    for idx, t in enumerate(tracks, 1):
        dur_str = f" ({format_duration(t['duration'])})" if t["duration"] else ""
        builder.button(text=f"{idx:02d}. {t['title']}{dur_str}", callback_data=f"play:{t['id']}")
    builder.adjust(1)

    last_cat = get_user_last_cat(query.from_user.id)
    if last_cat not in ("studio", "live", "japan", "bootleg", "chronology"):
        if album_name in JAPAN_ALBUMS:
            last_cat = "japan"
        elif album_name in STUDIO_ALBUMS:
            last_cat = "studio"
        elif album_name in OFFICIAL_LIVE_ALBUMS:
            last_cat = "live"
        elif album_name in BOOTLEG_AND_FAN_ALBUMS:
            last_cat = "bootleg"
        else:
            last_cat = "chronology"

    back_label = f"🔙 返回{CAT_LABELS.get(last_cat, '专辑分类')}"
    builder.row(
        InlineKeyboardButton(text=back_label, callback_data=f"cat:{last_cat}"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )

    total_sec = sum(t["duration"] for t in tracks)
    year = tracks[0]["year"] if tracks and tracks[0].get("year") else ""
    year_str = f"📅 发行年份：{year}年\n" if year else ""
    tag = get_album_tag(album_name)
    tag_str = f" `{tag}`" if tag else ""
    desc_str = get_album_desc(album_name)

    text = (
        f"💿 **专辑：《{album_name}》**{tag_str}\n"
        f"{year_str}"
        f"🎸 歌手：李志\n"
        f"🎵 共收录 {len(tracks)} 首歌曲 | ⏳ 总时长约 {format_duration(total_sec)}\n"
        f"{desc_str}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 支持一键连续点播整专，或点击单曲独立收听："
    )
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)


async def switch_song_inplace(bot: Bot, query: CallbackQuery, song: dict, album_name: str):
    """核心播放调度：始终维持当前唯一音频控制台"""
    user_id = query.from_user.id
    song_id = song["id"]
    _, _, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)
    caption = build_song_caption(song, album_name, cur_idx, total_cnt)
    markup = get_song_control_markup(song_id, album_name, lyrics_expanded=False)

    is_audio = getattr(query.message, "audio", None) is not None if query.message else False
    if is_audio:
        try:
            media = InputMediaAudio(
                media=song["file_id"],
                caption=caption,
                parse_mode="Markdown",
                title=song["title"],
                performer=song.get("performer", "李志"),
                duration=song.get("duration", 0)
            )
            await query.message.edit_media(media=media, reply_markup=markup)
            set_active_hub_mid(user_id, query.message.chat.id, query.message.message_id)
            await query.answer(f"▶️ 已切至: {song['title']}")
            return
        except TelegramAPIError as e:
            logger.warning(f"edit_media 原地切换失败 ({e})，尝试更新 caption...")
            try:
                await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
                set_active_hub_mid(user_id, query.message.chat.id, query.message.message_id)
                await query.answer(f"▶️ 已切至: {song['title']}")
                return
            except TelegramBadRequest:
                pass

    await _safe_delete_msg(query.message)
    old_mid = get_active_hub_mid(user_id)
    if old_mid and (not query.message or old_mid != query.message.message_id):
        await _safe_delete(bot, query.message.chat.id, old_mid)

    await query.answer(f"正在为你播放: {song['title']}")
    try:
        new_msg = await bot.send_audio(
            chat_id=query.message.chat.id,
            audio=song["file_id"],
            caption=caption,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except TelegramAPIError as e:
        logger.warning(f"send_audio 失败 ({e})，使用 copy_message 兜底...")
        new_msg = await bot.copy_message(
            chat_id=query.message.chat.id,
            from_chat_id=song["channel_id"],
            message_id=song["message_id"],
            reply_markup=markup
        )
    set_active_hub_mid(user_id, query.message.chat.id, new_msg.message_id)


@router.callback_query(F.data.startswith("play:"))
async def cb_play_song(query: CallbackQuery, bot: Bot):
    song_id = int(query.data.split("play:", 1)[1])
    song = db.get_song_by_id(song_id)
    if not song:
        await query.answer("该歌曲不存在或已被移除", show_alert=True)
        return
    await switch_song_inplace(bot, query, song, song["album"])


@router.callback_query(F.data.startswith("play_inplace:"))
async def cb_play_inplace(query: CallbackQuery, bot: Bot):
    parts = query.data.split(":", 2)
    song_id = int(parts[1])
    album_name = parts[2] if len(parts) > 2 else ""
    song = db.get_song_by_id(song_id)
    if not song:
        await query.answer("歌曲不存在", show_alert=True)
        return
    await switch_song_inplace(bot, query, song, album_name or song["album"])


@router.callback_query(F.data.startswith("lyric_toggle:"))
async def cb_lyric_toggle(query: CallbackQuery):
    parts = query.data.split(":")
    song_id = int(parts[1])
    action = parts[-1]
    album_name = parts[2] if len(parts) >= 4 else ""

    song = db.get_song_by_id(song_id)
    if not song:
        await query.answer("歌曲信息未找到", show_alert=True)
        return
    album_name = album_name or song["album"]

    if action == "expand":
        lyric_text = db.get_song_lyrics(song)
        if not lyric_text:
            await query.answer("暂未找到该曲目的文字歌词", show_alert=True)
            return

        caption = build_lyrics_caption(song, album_name, lyric_text)
        markup = get_song_control_markup(song_id, album_name, lyrics_expanded=True)
        try:
            await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
            await query.answer("📝 歌词已展开")
        except TelegramBadRequest as e:
            logger.warning(f"edit_caption 展开歌词失败: {e}")
            await query.answer("展开歌词失败")
    else:
        _, _, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)
        caption = build_song_caption(song, album_name, cur_idx, total_cnt)
        markup = get_song_control_markup(song_id, album_name, lyrics_expanded=False)
        try:
            await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
            await query.answer("🔼 歌词已折叠收起")
        except TelegramBadRequest as e:
            logger.warning(f"edit_caption 折叠歌词失败: {e}")
            await query.answer()


@router.callback_query(F.data.startswith("versions_menu:"))
async def cb_versions_menu(query: CallbackQuery):
    parts = query.data.split(":", 2)
    song_id = int(parts[1])
    album_name = parts[2] if len(parts) > 2 else ""

    core_title, versions = db.get_other_versions(song_id)
    if not versions:
        await query.answer("未找到该歌曲的其他现场版本", show_alert=True)
        return

    markup = get_versions_markup(song_id, album_name, versions)
    try:
        await query.message.edit_reply_markup(reply_markup=markup)
        await query.answer(f"🔄 为你找到《{core_title}》共 {len(versions)} 个现场版本")
    except TelegramBadRequest as e:
        logger.warning(f"edit_reply_markup 切换版本菜单失败: {e}")
        await query.answer()


@router.callback_query(F.data.startswith("send_all:"))
async def cb_send_all(query: CallbackQuery, bot: Bot):
    user_id = query.from_user.id
    now_time = asyncio.get_running_loop().time()
    if user_id in SEND_ALL_COOLDOWN and (now_time - SEND_ALL_COOLDOWN[user_id]) < 25:
        await query.answer("⚠️ 正在推送中，请间隔 25 秒后再试！", show_alert=True)
        return
    SEND_ALL_COOLDOWN[user_id] = now_time

    album_name = query.data.split("send_all:", 1)[1]
    tracks = db.get_songs_by_album(album_name)
    if not tracks:
        await query.answer("专辑曲目为空", show_alert=True)
        return

    await query.answer(f"开始连续点播《{album_name}》共 {len(tracks)} 首歌曲...", show_alert=False)
    await query.message.answer(f"📦 **正在为你打包连续点播《{album_name}》全部 {len(tracks)} 首曲目，请稍候...**", parse_mode="Markdown")

    success_count = 0
    for t in tracks:
        ctrl_markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 展开歌词", callback_data=f"lyric_toggle:{t['id']}:{album_name}:expand")
        ]])
        try:
            await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=t["channel_id"],
                message_id=t["message_id"],
                reply_markup=ctrl_markup
            )
            success_count += 1
            await asyncio.sleep(0.3)
        except TelegramAPIError as e:
            logger.error(f"发送单曲失败: {t['title']}, err: {e}")

    await query.message.answer(
        f"🎉 **专辑《{album_name}》全部 {success_count}/{len(tracks)} 首歌曲已送达！**\n祝你聆听愉快 🎸",
        parse_mode="Markdown"
    )

# -*- coding: utf-8 -*-
"""通用基础指令、城市地标与年代时光机交互路由"""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from constants import ERA_MAPPING
from hub import WELCOME_BANNER, db, render_hub, set_active_hub_mid
from ui.cards import (
    get_city_menu_view,
    get_era_menu_view,
    get_main_menu_markup,
    get_search_guide_view,
    get_welcome_text,
    home_only_markup,
    truncate_title,
)

router = Router(name="common")
router.message.filter(F.chat.type == "private")


@router.message(Command("start", "menu"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    text = get_welcome_text(db.get_stats(), db.get_video_stats())
    markup = get_main_menu_markup()

    if WELCOME_BANNER.exists():
        new_msg = await message.answer_photo(
            photo=FSInputFile(WELCOME_BANNER),
            caption=text,
            reply_markup=markup,
            parse_mode="Markdown"
        )
    else:
        new_msg = await message.answer(
            text=text,
            reply_markup=markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    set_active_hub_mid(user_id, message.chat.id, new_msg.message_id)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(query: CallbackQuery, bot: Bot):
    text = get_welcome_text(db.get_stats(), db.get_video_stats())
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, get_main_menu_markup(), query=query, prefer_photo=True)


@router.message(Command("search", "help"))
async def cmd_search_guide(message: Message, bot: Bot):
    bot_me = await bot.get_me()
    text, markup = get_search_guide_view(bot_me.username)
    await render_hub(bot, message.chat.id, message.from_user.id, text, markup)


@router.callback_query(F.data == "search_guide")
async def cb_search_guide(query: CallbackQuery, bot: Bot):
    bot_me = await bot.get_me()
    text, markup = get_search_guide_view(bot_me.username)
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.message(Command("sync"))
async def handle_sync_command(message: Message, bot: Bot):
    stats = db.get_stats()
    v_stats = db.get_video_stats()
    sync_text = (
        f"🔄 **曲库与影音自动同步状态：**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📡 **频道自动监听**：✅ 实时开启中（发布新音频或视频毫秒级入库）\n"
        f"💿 **收录唱片全集**：`{stats.get('albums', 0)}` 张\n"
        f"🎵 **收录歌曲总数**：`{stats.get('songs', 0)}` 首\n"
        f"🎬 **收录高清影音**：`{v_stats.get('videos', 0)}` 部\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 音影双全，已完美同步至高清影院与硬核点播站！"
    )
    await render_hub(bot, message.chat.id, message.from_user.id, sync_text, home_only_markup())


# ==================== 城市地标专区 ====================
@router.message(Command("city"))
async def cmd_city_menu(message: Message, bot: Bot):
    text, markup = get_city_menu_view()
    await render_hub(bot, message.chat.id, message.from_user.id, text, markup)


@router.callback_query(F.data == "menu:city")
async def cb_city_menu(query: CallbackQuery, bot: Bot):
    text, markup = get_city_menu_view()
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.callback_query(F.data.startswith("city:"))
async def cb_city_detail(query: CallbackQuery, bot: Bot):
    city = query.data.split("city:", 1)[1]
    songs = db.get_songs_by_city(city)
    if not songs:
        await query.answer("该城市暂无收录单曲", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for s in songs[:15]:
        year_str = f"[{s['year']}年] " if s.get("year") else ""
        builder.button(text=f"🎵 {year_str}{truncate_title(s['title'], 26)}", callback_data=f"play:{s['id']}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔙 返回城市列表", callback_data="menu:city"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )

    text = (
        f"🏙️ **李志城市地标 ·【{city}】精选曲目 ({len(songs)}首)**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"点击下方曲目即可直接点播收听："
    )
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)


# ==================== 年代时光机专区 ====================
@router.message(Command("era"))
async def cmd_era_menu(message: Message, bot: Bot):
    text, markup = get_era_menu_view()
    await render_hub(bot, message.chat.id, message.from_user.id, text, markup)


@router.callback_query(F.data == "menu:era")
async def cb_era_menu(query: CallbackQuery, bot: Bot):
    text, markup = get_era_menu_view()
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.callback_query(F.data.startswith("era:"))
async def cb_era_detail(query: CallbackQuery, bot: Bot):
    era_key = query.data.split("era:", 1)[1]
    era_info = ERA_MAPPING.get(era_key)
    if not era_info:
        await query.answer("时代未找到", show_alert=True)
        return

    target_names = set(era_info["albums"])
    matched_albums = [a for a in db.get_all_albums() if a["album"] in target_names]

    builder = InlineKeyboardBuilder()
    for a in matched_albums:
        year_str = f"[{a['year']}年] " if a.get("year") else ""
        builder.button(text=f"💿 {year_str}《{a['album']}》({a['track_count']}首)", callback_data=f"album:{a['album']}")
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔙 返回时光机列表", callback_data="menu:era"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )

    text = (
        f"⏳ **{era_info['title']}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📖 _{era_info['desc']}_\n\n"
        f"💿 收录唱片共 `{len(matched_albums)}` 张，点击即可展开专辑曲目："
    )
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)


@router.callback_query(F.data == "noop")
async def cb_noop(query: CallbackQuery):
    await query.answer()

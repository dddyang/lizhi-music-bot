# -*- coding: utf-8 -*-
"""通用基础指令与主菜单交互路由（极简轻量版）"""

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

from hub import WELCOME_BANNER, db, render_hub, set_active_hub_mid
from ui.cards import (
    get_main_menu_markup,
    get_search_guide_view,
    get_welcome_text,
    home_only_markup,
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


@router.callback_query(F.data == "noop")
async def cb_noop(query: CallbackQuery):
    await query.answer()

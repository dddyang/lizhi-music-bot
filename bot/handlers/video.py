# -*- coding: utf-8 -*-
"""74 部高清原画影音专区路由模块"""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from hub import db, render_hub
from ui.cards import (
    build_video_category_markup,
    build_video_detail_card,
    format_video_size,
    get_video_archive_view,
)

logger = logging.getLogger("LiZhiMusicBot.Video")
router = Router(name="video")
router.message.filter(F.chat.type == "private")


@router.message(Command("video"))
async def cmd_video_menu(message: Message, bot: Bot):
    text, markup = get_video_archive_view()
    await render_hub(bot, message.chat.id, message.from_user.id, text, markup)


@router.callback_query(F.data == "menu:video")
async def cb_video_menu(query: CallbackQuery, bot: Bot):
    text, markup = get_video_archive_view()
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.callback_query(F.data.startswith("vcat:"))
async def cb_video_cat(query: CallbackQuery, bot: Bot):
    parts = query.data.split(":")
    category = parts[1]
    offset = int(parts[2]) if len(parts) > 2 else 0
    text, markup = build_video_category_markup(category, offset=offset)
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.callback_query(F.data.startswith("vdetail:"))
async def cb_video_detail(query: CallbackQuery, bot: Bot):
    parts = query.data.split(":")
    video_id = int(parts[1])
    back_cat = parts[2] if len(parts) > 2 and parts[2] else None
    back_offset = int(parts[3]) if len(parts) > 3 and parts[3] else 0
    v = db.get_video_by_id(video_id)
    if not v:
        await query.answer("视频未找到", show_alert=True)
        return
    text, markup = build_video_detail_card(v, back_cat=back_cat, back_offset=back_offset)
    await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)


@router.callback_query(F.data.startswith("vpush:"))
async def cb_video_push(query: CallbackQuery, bot: Bot):
    video_id = int(query.data.split("vpush:", 1)[1])
    v = db.get_video_by_id(video_id)
    if not v:
        await query.answer("视频信息未找到", show_alert=True)
        return

    await query.answer(f"正在为你推送：《{v['title']}》...")
    channel_link = f"https://t.me/libimusic/{v['message_id']}"
    ctrl_markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🍿 直达频道全屏观看", url=channel_link)
    ]])

    try:
        await bot.copy_message(
            chat_id=query.message.chat.id,
            from_chat_id=v["channel_id"],
            message_id=v["message_id"],
            reply_markup=ctrl_markup
        )
    except TelegramAPIError as e:
        logger.warning(f"copy_message 视频失败 ({e})，引导用户使用频道直达链接...")
        fail_msg = (
            f"🎬 **《{v['title']}》**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ **提示**：该视频规格为 `{format_video_size(v)}`，超出 Telegram 私聊直接转播上限。\n"
            f"请点击下方按钮直接在频道中享受 1080P 原画免下载播放！"
        )
        await query.message.answer(fail_msg, reply_markup=ctrl_markup, parse_mode="Markdown")

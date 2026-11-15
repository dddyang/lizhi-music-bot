# -*- coding: utf-8 -*-
"""全局单一消息总线引擎、数据库实例与用户持久化会话管理"""

import logging
from pathlib import Path
from typing import Dict, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup

from config import DB_PATH
from database import MusicDatabase

logger = logging.getLogger("LiZhiMusicBot.Hub")

# 全局唯一数据库实例与资源路径
db = MusicDatabase(DB_PATH)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
WELCOME_BANNER = ASSETS_DIR / "welcome_banner.jpg"

# 双层架构会话状态（内存级极速命中 + SQLite 持久化兜底）
USER_ACTIVE_HUB: Dict[int, int] = {}      # user_id -> 当前唯一常驻控制台消息 ID
USER_LAST_CAT: Dict[int, str] = {}        # user_id -> 最后浏览的专辑分类
SEND_ALL_COOLDOWN: Dict[int, float] = {}  # user_id -> 连续点播防刷冷却时间戳


def get_active_hub_mid(user_id: int) -> Optional[int]:
    """获取用户常驻消息 ID（优先内存缓存，未命中查 SQLite 持久化）"""
    if user_id in USER_ACTIVE_HUB:
        return USER_ACTIVE_HUB[user_id]
    try:
        sess = db.get_user_session(user_id)
        if sess and sess.get("message_id"):
            mid = sess["message_id"]
            USER_ACTIVE_HUB[user_id] = mid
            return mid
    except Exception as e:
        logger.warning(f"获取持久化会话失败 (user={user_id}): {e}")
    return None


def set_active_hub_mid(user_id: int, chat_id: int, message_id: int, last_cat: Optional[str] = None):
    """同步更新内存缓存与 SQLite 持久化会话"""
    USER_ACTIVE_HUB[user_id] = message_id
    if last_cat:
        USER_LAST_CAT[user_id] = last_cat
    try:
        db.set_user_session(user_id, chat_id, message_id, last_cat)
    except Exception as e:
        logger.warning(f"持久化保存会话失败 (user={user_id}): {e}")


def get_user_last_cat(user_id: int) -> str:
    """获取用户最后浏览的唱片分类"""
    if user_id in USER_LAST_CAT:
        return USER_LAST_CAT[user_id]
    try:
        sess = db.get_user_session(user_id)
        if sess and sess.get("last_category"):
            cat = sess["last_category"]
            USER_LAST_CAT[user_id] = cat
            return cat
    except Exception as e:
        logger.warning(f"获取持久化分类失败 (user={user_id}): {e}")
    return "chronology"


def set_user_last_cat(user_id: int, last_cat: str):
    """记录并持久化用户最后浏览分类"""
    USER_LAST_CAT[user_id] = last_cat
    try:
        db.update_user_last_cat(user_id, last_cat)
    except Exception as e:
        logger.warning(f"持久化保存分类记忆失败 (user={user_id}): {e}")


async def _safe_delete(bot: Bot, chat_id: int, message_id: int):
    """安全删除指定消息（仅忽略已不存在或超期等常规 Telegram 异常）"""
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def _safe_delete_msg(message):
    """安全删除消息对象"""
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def render_hub(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    query: Optional[CallbackQuery] = None,
    prefer_photo: bool = False
):
    """
    核心单消息引擎：保证整个机器人会话始终在唯一一条消息框内流畅流转。
    优先原地 edit；若跨媒体类型或字长受限，自动平滑替换旧消息。
    """
    if query and query.message:
        is_audio = getattr(query.message, "audio", None) is not None
        has_photo = getattr(query.message, "photo", None) is not None

        if prefer_photo and not has_photo and not is_audio and WELCOME_BANNER.exists():
            await _safe_delete_msg(query.message)
        elif not is_audio:
            try:
                if has_photo:
                    await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)
                set_active_hub_mid(user_id, chat_id, query.message.message_id)
                await query.answer()
                return
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    await query.answer()
                    return
                try:
                    await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                    set_active_hub_mid(user_id, chat_id, query.message.message_id)
                    await query.answer()
                    return
                except TelegramBadRequest:
                    await _safe_delete_msg(query.message)
        else:
            await _safe_delete_msg(query.message)

    old_mid = get_active_hub_mid(user_id)
    if old_mid and (not query or not query.message or query.message.message_id != old_mid):
        await _safe_delete(bot, chat_id, old_mid)

    if prefer_photo and WELCOME_BANNER.exists():
        new_msg = await bot.send_photo(
            chat_id=chat_id,
            photo=FSInputFile(WELCOME_BANNER),
            caption=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        new_msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    set_active_hub_mid(user_id, chat_id, new_msg.message_id)
    if query:
        await query.answer()

# -*- coding: utf-8 -*-
"""1701 讨论室 - 入群乐迷常识验证与反垃圾拦截处理器"""

import asyncio
import logging
import random
from typing import Any, Dict

from aiogram import Bot, F, Router
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, JOIN_TRANSITION
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import json
from pathlib import Path

logger = logging.getLogger("LiZhiMusicBot.Verify")
router = Router(name="group_verify")

# 动态加载题库：优先读取本地私有题库 quiz_bank.json，缺失时回退到公开模板
QUIZ_FILE = Path(__file__).resolve().parent.parent / "quiz_bank.json"
QUIZ_EXAMPLE_FILE = Path(__file__).resolve().parent.parent / "quiz_bank.json.example"


def load_quiz_bank() -> list:
    target = QUIZ_FILE if QUIZ_FILE.exists() else QUIZ_EXAMPLE_FILE
    if target.exists():
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            logger.error(f"加载题库文件失败 ({target}): {e}")
    return [
        {
            "id": 1,
            "question": "李志排练房代号是？",
            "options": ["1701", "9527", "2046", "1984"],
            "correct": "1701"
        }
    ]


QUIZ_BANK = load_quiz_bank()

# 禁言状态：只读，无法发送文字、媒体、链接等
RESTRICTED_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False
)

# 正常状态：解除禁言
UNRESTRICTED_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True
)

# 内存待验证池：user_id -> {"chat_id": int, "msg_id": int, "correct_opt": str, "task": asyncio.Task}
PENDING_VERIFICATIONS: Dict[int, Dict[str, Any]] = {}


async def _timeout_worker(bot: Bot, chat_id: int, user_id: int, msg_id: int):
    """60 秒超时未答题自动移出群聊并清理消息"""
    try:
        await asyncio.sleep(60)
        if user_id in PENDING_VERIFICATIONS:
            logger.info(f"⏰ 用户 {user_id} 入群验证超时，正在移出群聊...")
            PENDING_VERIFICATIONS.pop(user_id, None)
            try:
                # kick (ban + unban 使其离开但未来仍可重新申请)
                await bot.ban_chat_member(chat_id, user_id)
                await bot.unban_chat_member(chat_id, user_id)
            except Exception as e:
                logger.warning(f"移出超时用户 {user_id} 失败 (请确认机器人有管理员踢人权限): {e}")

            try:
                await bot.delete_message(chat_id, msg_id)
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def handle_new_member(bot: Bot, chat_id: int, user):
    """处理新成员入群的核心发题流程"""
    if user.is_bot:
        return

    # 防重复触发（某些客户端同时发 chat_member 和 service message）
    if user.id in PENDING_VERIFICATIONS:
        return

    # 1. 临时禁言
    try:
        await bot.restrict_chat_member(chat_id=chat_id, user_id=user.id, permissions=RESTRICTED_PERMS)
        logger.info(f"🔒 已对新入群成员 {user.full_name} ({user.id}) 执行临时禁言")
    except Exception as e:
        logger.warning(f"⚠️ 对用户 {user.id} 禁言失败 (请确保机器人已赋予管理员禁言权限): {e}")

    # 2. 随机抽题并打乱选项
    quiz = random.choice(QUIZ_BANK)
    options = quiz["options"][:]
    random.shuffle(options)
    correct_opt = quiz["correct"]

    # 3. 构造 4 个选项按钮 (两行两列)
    builder = InlineKeyboardBuilder()
    for opt in options:
        # callback 格式：vfy:{user_id}:{opt}
        # opt 可能有中文，限制在 30 字符内，符合 Telegram 64 字节限制
        builder.button(text=opt, callback_data=f"vfy:{user.id}:{opt}")
    builder.adjust(2, 2)

    # 4. 发送验证题卡片
    mention = f"@{user.username}" if user.username else f"[{user.full_name}](tg://user?id={user.id})"
    text = (
        f"👋 欢迎 {mention} 来到 **1701 讨论室**！\n\n"
        f"请在 **60 秒** 内回答以下乐迷常识题完成验证，答错或超时将自动移出群聊：\n\n"
        f"❓ **{quiz['question']}**"
    )

    try:
        verify_msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )

        # 5. 挂入超时定时器
        task = asyncio.create_task(_timeout_worker(bot, chat_id, user.id, verify_msg.message_id))
        PENDING_VERIFICATIONS[user.id] = {
            "chat_id": chat_id,
            "msg_id": verify_msg.message_id,
            "correct_opt": correct_opt,
            "task": task
        }
    except Exception as e:
        logger.error(f"❌ 发送入群验证卡片失败: {e}")


# 触发方式 1: 官方推荐的 ChatMemberUpdated 状态跃迁
@router.chat_member(ChatMemberUpdatedFilter(JOIN_TRANSITION))
async def on_user_joined_chat_member(event: ChatMemberUpdated, bot: Bot):
    if event.chat.type not in ("group", "supergroup"):
        return
    await handle_new_member(bot, event.chat.id, event.new_chat_member.user)


# 触发方式 2: 服务消息 F.new_chat_members 双保险
@router.message(F.new_chat_members)
async def on_user_joined_message(message: Message, bot: Bot):
    if message.chat.type not in ("group", "supergroup"):
        return
    for member in message.new_chat_members:
        await handle_new_member(bot, message.chat.id, member)


# 处理选项按钮点击
@router.callback_query(F.data.startswith("vfy:"))
async def on_verify_callback(query: CallbackQuery, bot: Bot):
    # 数据格式：vfy:{target_user_id}:{chosen_opt}
    parts = query.data.split(":", 2)
    if len(parts) < 3:
        await query.answer("无效请求", show_alert=True)
        return

    target_user_id = int(parts[1])
    chosen_opt = parts[2]
    clicker_user_id = query.from_user.id

    # 1. 身份防冒充与防误触
    if clicker_user_id != target_user_id:
        await query.answer("这不是给你的验证题哦，请勿捣乱～", show_alert=True)
        return

    # 2. 检查验证状态
    record = PENDING_VERIFICATIONS.get(target_user_id)
    if not record:
        await query.answer("验证已过期或已处理！", show_alert=True)
        return

    chat_id = record["chat_id"]
    msg_id = record["msg_id"]
    correct_opt = record["correct_opt"]
    task: asyncio.Task = record["task"]

    # 取消超时定时器并从待验证池移除
    if task and not task.done():
        task.cancel()
    PENDING_VERIFICATIONS.pop(target_user_id, None)

    # 3. 判定正误
    if chosen_opt == correct_opt:
        # 解除禁言
        try:
            await bot.restrict_chat_member(chat_id=chat_id, user_id=target_user_id, permissions=UNRESTRICTED_PERMS)
            logger.info(f"✅ 用户 {query.from_user.full_name} ({target_user_id}) 验证通过，已解除禁言")
        except Exception as e:
            logger.warning(f"解除禁言失败: {e}")

        # 弹窗提示
        await query.answer("回答正确，验证通过！", show_alert=False)

        # 优雅通过文案
        mention = f"@{query.from_user.username}" if query.from_user.username else f"[{query.from_user.full_name}](tg://user?id={query.from_user.id})"
        pass_text = f"🎉 验证通过！欢迎 {mention} 加入 1701 讨论室，祝你听歌愉快～"

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=pass_text,
                reply_markup=None,
                parse_mode="Markdown"
            )
        except Exception:
            pass

        # 5 秒后自动清理验证消息，不留群聊垃圾
        await asyncio.sleep(5)
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    else:
        # 答错处理
        await query.answer("❌ 回答错误，验证未能通过！", show_alert=True)
        logger.info(f"🚫 用户 {query.from_user.full_name} ({target_user_id}) 选错答案: {chosen_opt} (正解: {correct_opt})，正在移出...")

        try:
            await bot.ban_chat_member(chat_id, target_user_id)
            await bot.unban_chat_member(chat_id, target_user_id)
        except Exception as e:
            logger.warning(f"移出未通过用户失败: {e}")

        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

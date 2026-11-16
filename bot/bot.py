# -*- coding: utf-8 -*-
"""李志全系音乐与高清影音电报机器人 - 模块化轻量主入口"""

import asyncio
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonCommands

from config import BOT_TOKEN
from handlers import register_all_routers

LOG_FILE = Path(__file__).resolve().parent / "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8")
    ]
)
logger = logging.getLogger("LiZhiMusicBot")


async def configure_bot_ui(bot: Bot) -> None:
    """配置 Telegram 客户端左下角菜单按钮与快捷指令列表"""
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("✅ 已同步 Telegram 客户端左下角为原生命令菜单 (MenuButtonCommands)")
    except Exception as e:
        logger.warning(f"设置 MenuButton 失败: {e}")

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 主控制台与点播中心"),
            BotCommand(command="video", description="🎬 74部高清原画影音专区"),
            BotCommand(command="city", description="🏙️ 城市地标点播专区"),
            BotCommand(command="era", description="⏳ 20年创作年代时光机"),
            BotCommand(command="search", description="🔍 搜歌搜视频指南"),
            BotCommand(command="sync", description="🔄 曲库与影音同步状态")
        ])
    except Exception as e:
        logger.warning(f"设置快捷指令菜单失败: {e}")


async def start_bot() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.error("❌ 请在 .env 中正确配置 BOT_TOKEN 后再启动机器人！")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    register_all_routers(dp)

    await configure_bot_ui(bot)

    bot_info = await bot.get_me()
    logger.info("=" * 60)
    logger.info(f"🚀 模块化轻量版单消息点播机器人 @{bot_info.username} 已上线运行！")
    logger.info("=" * 60)

    while True:
        try:
            # 显式允许 chat_member 状态更新，确保入群监听 100% 命中
            allowed_updates = dp.resolve_used_update_types()
            if "chat_member" not in allowed_updates:
                allowed_updates.append("chat_member")
            await dp.start_polling(bot, allowed_updates=allowed_updates)
        except (KeyboardInterrupt, SystemExit):
            break
        except Exception as e:
            logger.warning(f"⚠️ 网络抖动或连接异常: {e}，5秒后自动重连...")
            await asyncio.sleep(5)

    await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(start_bot())
    except (KeyboardInterrupt, SystemExit):
        logger.info("🛑 机器人已安全退出。")

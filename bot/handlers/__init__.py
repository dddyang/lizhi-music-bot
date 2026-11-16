# -*- coding: utf-8 -*-
"""统一路由汇总装配器"""

from aiogram import Dispatcher

from .common import router as common_router
from .music import router as music_router
from .search_inline import router as search_inline_router
from .verify import router as verify_router
from .video import router as video_router


def register_all_routers(dp: Dispatcher) -> None:
    """
    严格按优先级顺序注册路由器：
    1. verify_router (群组入群常识验证与反垃圾拦截，最高优先级)
    2. common_router (斜杠命令 /start, /city, /era, /search 等)
    3. video_router (/video 及 vcat:/vdetail:/vpush: 回调)
    4. music_router (专辑、随缘、切歌、歌词等核心回调)
    5. search_inline_router (包含全局 F.text 文本兜底搜索，必须最后注册！)
    """
    dp.include_router(verify_router)
    dp.include_router(common_router)
    dp.include_router(video_router)
    dp.include_router(music_router)
    dp.include_router(search_inline_router)

import asyncio
import logging
import random
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultCachedAudio,
    FSInputFile,
    BotCommand
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, DB_PATH, CHANNEL_ID
from database import MusicDatabase
from lyrics_bank import get_lyrics
from mood_quotes import get_random_quote, MOOD_CHANNELS, NLP_SUMMARY_TEXT

LOG_FILE = Path(__file__).resolve().parent / "bot.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    ]
)
logger = logging.getLogger("LiZhiMusicBot")

db = MusicDatabase(DB_PATH)
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
WELCOME_BANNER = ASSETS_DIR / "welcome_banner.jpg"

# 全局用户状态（内存）
MOOD_HISTORY: Dict[int, List[int]] = {}   # user_id -> 最近播放过的 song_id 列表（电台去重）
USER_LAST_CAT: Dict[int, str] = {}        # user_id -> 最后浏览的专辑分类（记忆返回）

# 1. 经典录音室创作专辑 (共9张，维基权威考据)
STUDIO_ALBUMS = {
    "被禁忌的游戏", "梵高先生", "这个世界会好吗", "我爱南京",
    "你好，郑州", "F", "李志 1701", "8",
    "在每一条伤心的应天大街上"
}

# 2. 官方现场演出专辑 (共14张)
OFFICIAL_LIVE_ALBUMS = {
    "二零零九年十月十六日事件", "工体东路没有人", "我们也爱南京",
    "Imagine Live", "勾三搭四", "108个关键词", "I/O",
    "动静 (2015 Live)", "看见 (李志2015巡回演唱会)",
    "李志北京不插电现场 2016 Live", "李志、电声与管弦乐",
    "爵士乐与不插电新编12首", "李志、电声与管弦乐II", "叁缺壹 (2024 Tokyo Live)"
}

# 3. 海外限定精选、巡演专场录音与乐迷合辑 (共10张)
SELECTION_AND_TOUR_ALBUMS = {
    "Best Selection Songs 2004-2019 (Vol.1)",
    "Best Selection Songs 2004-2018 (Vol.2)",
    "Best Selection Songs 2004-2018 (Vol.3)",
    "义乌隔壁酒吧", "杭州酒球会一身酒气", "“挺”不插电巡演 郑州站",
    "金城兰州", "洗心革面 跨年音乐会", "杂选", "李志LIVE精选"
}

# 版本性质说明标签
UNOFFICIAL_ALBUM_TAGS = {
    "Best Selection Songs 2004-2019 (Vol.1)": {
        "tag": "[日本限定精选]",
        "desc": "⚠️ **版本性质**：`[日本限定精选辑]`（2019年日本波丽佳音出版，录音室名曲新编高品质归档）"
    },
    "Best Selection Songs 2004-2018 (Vol.2)": {
        "tag": "[日本限定精选]",
        "desc": "⚠️ **版本性质**：`[日本限定精选辑]`（2020年日本波丽佳音出版，现象级代表作海外限定精选）"
    },
    "Best Selection Songs 2004-2018 (Vol.3)": {
        "tag": "[日本限定精选]",
        "desc": "⚠️ **版本性质**：`[日本限定精选辑]`（《装蒜》Live 精选海外复刻版）"
    },
    "义乌隔壁酒吧": {
        "tag": "[民间现场录音]",
        "desc": "⚠️ **版本性质**：`[民间现场录音]`（2009年“动物凶猛”巡演义乌收官战乐迷 Bootleg，含醉酒绝唱版《梵高先生》）"
    },
    "杭州酒球会一身酒气": {
        "tag": "[民间现场录音]",
        "desc": "⚠️ **版本性质**：`[民间现场录音]`（李志在杭州酒球会 Livehouse 专场演出的乐迷现场录音 Bootleg）"
    },
    "“挺”不插电巡演 郑州站": {
        "tag": "[民间现场录音]",
        "desc": "⚠️ **版本性质**：`[民间现场录音]`（2014年“挺”全国巡演郑州站民间现场录音，非官方正式唱片）"
    },
    "洗心革面 跨年音乐会": {
        "tag": "[民间现场录音]",
        "desc": "⚠️ **版本性质**：`[民间现场录音]`（2018-2019 欧拉跨年音乐会独家直播提取版，非官方实体唱片）"
    },
    "金城兰州": {
        "tag": "[民间现场录音]",
        "desc": "⚠️ **版本性质**：`[民间现场录音]`（兰州巡演现场翻唱低苦艾《兰州兰州》的单曲提取音频）"
    },
    "杂选": {
        "tag": "[乐迷合辑]",
        "desc": "⚠️ **版本性质**：`[乐迷合辑]`（早期贴吧乐迷自发整理的网络散落单曲、Demo 与未发行版本合辑）"
    },
    "李志LIVE精选": {
        "tag": "[乐迷合辑]",
        "desc": "⚠️ **版本性质**：`[乐迷合辑]`（乐迷剪辑汇总的历年巡演高光片段，含西安定西独白、成都《江城子》等）"
    }
}

def get_album_tag(album_name: str) -> str:
    info = UNOFFICIAL_ALBUM_TAGS.get(album_name)
    return info["tag"] if info else ""

def get_album_desc(album_name: str) -> str:
    info = UNOFFICIAL_ALBUM_TAGS.get(album_name)
    return f"\n{info['desc']}\n" if info else ""

def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"

def escape_md(text: str) -> str:
    """安全转义 Markdown 实体保留字符，防止 Telegram 消息发送失败"""
    if not text:
        return ""
    return re.sub(r'([_*`\[])', r'\\\1', str(text))


def get_welcome_text(stats: dict) -> str:
    songs_cnt = stats.get("songs", 0)
    albums_cnt = stats.get("albums", 0)
    return (
        f"🎸 **李志音乐点播站 · Li Zhi Music Station**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎙️ **音乐人**：李志\n"
        f"💿 **专辑收录**：`{albums_cnt}` 张全集 (2004 — 2024 编年史)\n"
        f"🎵 **曲目收录**：`{songs_cnt}` 首 (爱好者整理 · 高保真曲库)\n"
        f"📻 **音乐频道**：[点击进入李志音乐分享频道](https://t.me/libimusic)\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 **快捷功能导览：**\n"
        f"• 💽 **录音室专辑**：9 张经典经典录音室创作全集\n"
        f"• 🎸 **官方现场Live**：14 张跨年、交响与巡演现场全本\n"
        f"• 🗂️ **精选与合辑**：海外限定精选、巡演录音与散落Demo\n"
        f"• 📅 **唱片编年史**：按 2004~2024 时间轴浏览全 33 张唱片\n"
        f"• 🎲 **随缘一曲**：随机推荐一首心动单曲\n"
        f"• 🔍 **歌词/拼音搜索**：直接发送歌名或拼音缩写（如 `fgxs`、`郑州`）"
    )


def get_main_menu_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    # 第一行：录音室 vs 官方现场
    builder.row(
        InlineKeyboardButton(text="💿 录音室专辑 (9张)", callback_data="cat:studio"),
        InlineKeyboardButton(text="🎸 官方现场Live (14张)", callback_data="cat:live")
    )
    # 第二行：精选/合辑 vs 唱片编年史
    builder.row(
        InlineKeyboardButton(text="🗂️ 精选与合辑专区 (10张)", callback_data="cat:selection"),
        InlineKeyboardButton(text="📅 唱片编年史 (全33张)", callback_data="cat:chronology")
    )
    # 第三行：心境场景电台 vs 每日歌词日签
    builder.row(
        InlineKeyboardButton(text="🎧 心境场景电台", callback_data="menu:mood"),
        InlineKeyboardButton(text="📜 每日歌词日签", callback_data="menu:quote")
    )
    # 第四行：随缘一曲 vs 词频大数据报告
    builder.row(
        InlineKeyboardButton(text="🎲 随缘一曲", callback_data="random_song"),
        InlineKeyboardButton(text="📊 歌词大数据报告", callback_data="menu:stats")
    )
    # 第五行：音乐分享频道
    builder.row(
        InlineKeyboardButton(text="📢 音乐分享频道", url="https://t.me/libimusic")
    )
    return builder.as_markup()


def build_albums_markup_by_filter(filter_type: str) -> InlineKeyboardMarkup:
    all_albums = db.get_all_albums()
    builder = InlineKeyboardBuilder()

    if filter_type == "studio":
        filtered = [a for a in all_albums if a["album"] in STUDIO_ALBUMS]
    elif filter_type == "live":
        filtered = [a for a in all_albums if a["album"] in OFFICIAL_LIVE_ALBUMS]
    elif filter_type == "selection":
        filtered = [a for a in all_albums if a["album"] in SELECTION_AND_TOUR_ALBUMS]
    else:  # chronology / all
        filtered = all_albums

    for item in filtered:
        album_name = item["album"]
        count = item["track_count"]
        year = item.get("year")
        year_str = f"[{year}年] " if year else ""
        tag = get_album_tag(album_name)
        tag_str = f" {tag}" if tag else ""
        clean_display = f"{year_str}《{album_name}》{tag_str} ({count}首)"
        builder.button(text=clean_display, callback_data=f"album:{album_name}")

    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )
    return builder.as_markup()



def get_song_control_markup(song_id: int, album_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📝 查看歌词", callback_data=f"lyrics:{song_id}"),
        InlineKeyboardButton(text="💿 查看专辑", callback_data=f"album:{album_name}")
    )
    builder.row(
        InlineKeyboardButton(text="🎲 随缘下一首", callback_data="random_song")
    )
    return builder.as_markup()


async def start_bot():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.error("❌ 请在 .env 中正确配置 BOT_TOKEN 后再启动机器人！")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start", "menu"))
    async def cmd_start(message: Message):
        stats = db.get_stats()
        text = get_welcome_text(stats)
        markup = get_main_menu_markup()
        if WELCOME_BANNER.exists():
            await message.answer_photo(
                photo=FSInputFile(WELCOME_BANNER),
                caption=text,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                text=text,
                reply_markup=markup,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

    @dp.message(Command("random"))
    async def cmd_random(message: Message):
        song = db.get_random_song()
        if not song:
            await message.answer("曲库为空或正在同步中")
            return
        year_str = f" [{song['year']}年]" if song.get("year") else ""
        tag = get_album_tag(song["album"])
        tag_str = f" {tag}" if tag else ""
        markup = get_song_control_markup(song["id"], song["album"])
        try:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=song["channel_id"],
                message_id=song["message_id"],
                reply_markup=markup
            )
        except Exception:
            await bot.send_audio(
                chat_id=message.chat.id,
                audio=song["file_id"],
                caption=f"🎲 随缘一曲：{song['title']} - 《{song['album']}》{year_str}{tag_str}",
                reply_markup=markup
            )

    @dp.message(Command("search", "help"))
    async def cmd_search_guide(message: Message):
        bot_me = await bot.get_me()
        guide = (
            f"🔍 **李志曲库智能检索指南：**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"你无需点击复杂菜单，直接在当前对话框中发送文字即可！\n\n"
            f"📌 **支持的搜索方式：**\n"
            f"1. **歌名全称或关键字**：如 `关于郑州的记忆`、`梵高`、`天空之城`\n"
            f"2. **拼音首字母缩写**：如 `fgxs` (梵高先生)、`zz` (关于郑州的记忆)、`tkzc` (天空之城)、`syldxt` (山阴路的夏天)\n"
            f"3. **专辑名称**：如 `应天大街`、`1701`、`叁缺壹`\n"
            f"4. **全局行内分享**：在任意聊天框输入 `@{bot_me.username} 歌名` 实时搜索并卡片发送给好友！"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        await message.answer(guide, reply_markup=builder.as_markup(), parse_mode="Markdown")


    async def show_quote_card(target, is_callback: bool = False):
        q = get_random_quote()
        matched = db.search_songs(q["title"], limit=1)
        song = matched[0] if matched else None
        
        card = (
            f"📜 **李志歌词日签 · Daily Lyric Card**\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"「 **{escape_md(q['quote'])}** 」\n\n"
            f"🎵 **出处**：《{q['title']}》\n"
            f"💿 **专辑**：《{q['album']}》 ({q['year']}年)\n"
            f"🎸 **词曲**：李志\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 李志音乐点播站 [@libi\_music\_bot](https://t.me/libi_music_bot)"
        )
        builder = InlineKeyboardBuilder()
        if song:
            builder.button(text="🎵 播放这首单曲", callback_data=f"play:{song['id']}")
        builder.button(text="🎲 换一句日签", callback_data="menu:quote")
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        builder.adjust(1)

        if is_callback:
            try:
                await target.message.edit_text(card, reply_markup=builder.as_markup(), parse_mode="Markdown")
            except Exception:
                try:
                    await target.message.edit_caption(caption=card, reply_markup=builder.as_markup(), parse_mode="Markdown")
                except Exception:
                    await target.message.answer(card, reply_markup=builder.as_markup(), parse_mode="Markdown")
            await target.answer()
        else:
            await target.answer(card, reply_markup=builder.as_markup(), parse_mode="Markdown")

    @dp.message(Command("quote"))
    async def cmd_quote(message: Message):
        await show_quote_card(message, is_callback=False)

    @dp.callback_query(F.data == "menu:quote")
    async def cb_quote(query: CallbackQuery):
        await show_quote_card(query, is_callback=True)

    @dp.message(Command("stats"))
    async def cmd_stats(message: Message):
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        await message.answer(NLP_SUMMARY_TEXT, reply_markup=builder.as_markup(), parse_mode="Markdown")

    @dp.callback_query(F.data == "menu:stats")
    async def cb_stats(query: CallbackQuery):
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        try:
            await query.message.edit_text(NLP_SUMMARY_TEXT, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            try:
                await query.message.edit_caption(caption=NLP_SUMMARY_TEXT, reply_markup=builder.as_markup(), parse_mode="Markdown")
            except Exception:
                await query.message.answer(NLP_SUMMARY_TEXT, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await query.answer()

    @dp.message(Command("radio"))
    async def cmd_radio(message: Message):
        builder = InlineKeyboardBuilder()
        for key, mood in MOOD_CHANNELS.items():
            builder.button(text=mood["title"], callback_data=f"mood:{key}")
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        builder.adjust(1)
        text = (
            "🎧 **李志心境与场景电台 · Mood & City Radio**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "根据你当前的心境或身处的空间，挑选专属主题频道：\n\n"
            "• 🌧️ **深夜 Emo**：失眠宿醉、深夜独处的精神庇护所\n"
            "• 🎸 **现场摇滚**：大汗淋漓、热血沸腾的现场狂欢\n"
            "• ☕ **极简民谣**：一把吉他、清澈质朴的清晨漫步\n"
            "• 🎻 **管弦跨界**：史诗交响新编与室内乐美学\n"
            "• 🚆 **城市漫游**：南京、郑州、兰州、成都等音乐地标"
        )
        await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")

    @dp.callback_query(F.data == "menu:mood")
    async def cb_mood_menu(query: CallbackQuery):
        builder = InlineKeyboardBuilder()
        for key, mood in MOOD_CHANNELS.items():
            builder.button(text=mood["title"], callback_data=f"mood:{key}")
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        builder.adjust(1)
        text = (
            "🎧 **李志心境与场景电台 · Mood & City Radio**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "根据你当前的心境或身处的空间，挑选专属主题频道：\n\n"
            "• 🌧️ **深夜 Emo**：失眠宿醉、深夜独处的精神庇护所\n"
            "• 🎸 **现场摇滚**：大汗淋漓、热血沸腾的现场狂欢\n"
            "• ☕ **极简民谣**：一把吉他、清澈质朴的清晨慢步\n"
            "• 🎻 **管弦跨界**：史诗交响新编与室内乐美学\n"
            "• 🚆 **城市漫游**：南京、郑州、兰州、成都等音乐地标"
        )
        try:
            await query.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            try:
                await query.message.edit_caption(caption=text, reply_markup=builder.as_markup(), parse_mode="Markdown")
            except Exception:
                await query.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await query.answer()

    @dp.callback_query(F.data.startswith("mood:"))
    async def cb_mood_play(query: CallbackQuery):
        key = query.data.split("mood:", 1)[1]
        mood = MOOD_CHANNELS.get(key)
        if not mood:
            await query.answer("主题未找到", show_alert=True)
            return

        candidates = []
        for kw in mood["keywords"]:
            found = db.search_songs(kw, limit=5)
            candidates.extend(found)

        # 电台去重：过滤掉该用户最近 10 首听过的歌
        user_id = query.from_user.id
        recent_ids = MOOD_HISTORY.get(user_id, [])
        fresh = [s for s in candidates if s and s["id"] not in recent_ids]
        if not fresh:
            # 全部听完一轮，重置历史再选取
            fresh = [s for s in candidates if s]
            MOOD_HISTORY[user_id] = []

        song = random.choice(fresh) if fresh else db.get_random_song()
        if not song:
            await query.answer("电台暂时没有匹配曲目", show_alert=True)
            return

        # 更新去重历史（保留最近 10 首）
        history = MOOD_HISTORY.get(user_id, [])
        history.append(song["id"])
        MOOD_HISTORY[user_id] = history[-10:]

        year_str = f" [{song['year']}年]" if song.get("year") else ""
        tag = get_album_tag(song["album"])
        tag_str = f" {tag}" if tag else ""

        await query.answer(f"🎧 切换【{mood['title']}】：{song['title']}")

        builder = InlineKeyboardBuilder()
        builder.row(
            InlineKeyboardButton(text="📝 查看歌词", callback_data=f"lyrics:{song['id']}"),
            InlineKeyboardButton(text="🎲 该场景下一首", callback_data=f"mood:{key}")
        )
        builder.row(
            InlineKeyboardButton(text="🔙 返回电台列表", callback_data="menu:mood"),
            InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
        )

        caption = (
            f"🎧 **【{mood['title']}】主题电台**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🎵 **{escape_md(song['title'])}** - 《{escape_md(song['album'])}》{year_str}{tag_str}\n"
            f"💬 _{mood['desc']}_\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💡 李志音乐点播站 [@libi\\_music\\_bot](https://t.me/libi_music_bot)"
        )

        try:
            # 优先 copy_message（不传非法 caption，保持音频原貌）
            await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=song["channel_id"],
                message_id=song["message_id"],
                reply_markup=builder.as_markup()
            )
            # 再附送电台主题卡片
            await query.message.answer(caption, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            # fallback: 直接用 file_id 独立发送并附带 caption
            await bot.send_audio(
                chat_id=query.message.chat.id,
                audio=song["file_id"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )

    @dp.callback_query(F.data == "main_menu")
    async def cb_main_menu(query: CallbackQuery):
        stats = db.get_stats()
        text = get_welcome_text(stats)
        try:
            await query.message.edit_text(
                text=text,
                reply_markup=get_main_menu_markup(),
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        except Exception:
            try:
                await query.message.edit_caption(
                    caption=text,
                    reply_markup=get_main_menu_markup(),
                    parse_mode="Markdown"
                )
            except Exception:
                await query.message.answer(
                    text=text,
                    reply_markup=get_main_menu_markup(),
                    parse_mode="Markdown",
                    disable_web_page_preview=True
                )
        await query.answer()

    @dp.callback_query(F.data.startswith("cat:"))
    async def cb_category(query: CallbackQuery):
        cat = query.data.split("cat:", 1)[1]
        USER_LAST_CAT[query.from_user.id] = cat   # 记住用户当前浏览的分类
        titles = {
            "studio": "💿 **李志经典录音室创作专辑列表 (共9张)：**",
            "live": "🎸 **李志官方现场Live专辑列表 (共14张)：**",
            "selection": "🗂️ **李志海外精选、巡演专场与乐迷合辑 (共10张)：**",
            "chronology": "📅 **李志唱片编年史 (2004 — 2024 全集33张)：**"
        }
        title_text = titles.get(cat, "💿 **请选择你想收听的专辑：**")
        markup = build_albums_markup_by_filter(cat)


        try:
            await query.message.edit_caption(caption=title_text, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            try:
                await query.message.edit_text(title_text, reply_markup=markup, parse_mode="Markdown")
            except Exception:
                await query.message.answer(title_text, reply_markup=markup, parse_mode="Markdown")
        await query.answer()

    @dp.callback_query(F.data.startswith("album:"))
    async def cb_album_detail(query: CallbackQuery):
        album_name = query.data.split("album:", 1)[1]
        tracks = db.get_songs_by_album(album_name)
        if not tracks:
            await query.answer("未找到该专辑曲目", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        for idx, t in enumerate(tracks, 1):
            dur_str = f" ({format_duration(t['duration'])})" if t['duration'] else ""
            builder.button(
                text=f"{idx:02d}. {t['title']}{dur_str}",
                callback_data=f"play:{t['id']}"
            )
        builder.adjust(1)

        # 底部操作栏：返回到用户上一次浏览的分类（而非固定跳编年史）
        last_cat = USER_LAST_CAT.get(query.from_user.id, "chronology")
        cat_labels = {
            "studio": "💿 录音室专辑",
            "live": "🎸 官方现场Live",
            "selection": "🗂️ 精选与合辑",
            "chronology": "📅 编年史",
        }
        back_label = f"🔙 返回{cat_labels.get(last_cat, '专辑分类')}"
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
            f"💡 点击上方曲目即可直接播放："
        )

        try:
            await query.message.edit_caption(caption=text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            try:
                await query.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
            except Exception:
                await query.message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await query.answer()

    @dp.callback_query(F.data.startswith("play:"))
    async def cb_play_song(query: CallbackQuery):
        song_id = int(query.data.split("play:", 1)[1])
        song = db.get_song_by_id(song_id)
        if not song:
            await query.answer("该歌曲不存在或已被移除", show_alert=True)
            return

        await query.answer(f"正在为你播放: {song['title']}")
        markup = get_song_control_markup(song_id, song["album"])

        try:
            # 优先使用 copy_message，带控制键盘
            await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=song["channel_id"],
                message_id=song["message_id"],
                reply_markup=markup
            )
        except Exception as e:
            logger.warning(f"copy_message 失败 ({e})，尝试使用 file_id 发送...")
            year_str = f" [{song['year']}年]" if song.get("year") else ""
            tag = get_album_tag(song["album"])
            tag_str = f" {tag}" if tag else ""
            caption = f"🎵 {song['title']} - 《{song['album']}》{year_str}{tag_str}\n🎸 歌手：李志"
            await bot.send_audio(
                chat_id=query.message.chat.id,
                audio=song["file_id"],
                caption=caption,
                reply_markup=markup
            )

    SEND_ALL_COOLDOWN = {}

    @dp.callback_query(F.data.startswith("send_all:"))
    async def cb_send_all(query: CallbackQuery):
        user_id = query.from_user.id
        now_time = asyncio.get_event_loop().time()
        if user_id in SEND_ALL_COOLDOWN and (now_time - SEND_ALL_COOLDOWN[user_id]) < 30:
            await query.answer("⚠️ 正在推送中或操作过于频繁，请间隔 30 秒后再试！", show_alert=True)
            return
        SEND_ALL_COOLDOWN[user_id] = now_time

        album_name = query.data.split("send_all:", 1)[1]
        tracks = db.get_songs_by_album(album_name)
        if not tracks:
            await query.answer("专辑曲目为空", show_alert=True)
            return

        await query.answer(f"开始推送《{album_name}》共 {len(tracks)} 首歌曲...", show_alert=False)
        await query.message.answer(f"📦 **正在为你打包推送专辑《{album_name}》全部 {len(tracks)} 首歌曲，请稍候...**", parse_mode="Markdown")

        success_count = 0
        for idx, t in enumerate(tracks, 1):
            ctrl_markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📝 查看歌词", callback_data=f"lyrics:{t['id']}")
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
            except Exception as e:
                logger.error(f"发送单曲失败: {t['title']}, err: {e}")

        await query.message.answer(
            f"🎉 **专辑《{album_name}》全部 {success_count}/{len(tracks)} 首歌曲已送达！**\n"
            f"祝你收听愉快 🎸",
            parse_mode="Markdown"
        )

    @dp.callback_query(F.data.startswith("lyrics:"))
    async def cb_lyrics(query: CallbackQuery):
        song_id = int(query.data.split("lyrics:", 1)[1])
        song = db.get_song_by_id(song_id)
        if not song:
            await query.answer("歌曲信息未找到", show_alert=True)
            return

        title = song["title"]
        album = song["album"]
        year = song["year"]
        year_str = f" ({year}年)" if year else ""
        tag = get_album_tag(album)
        tag_str = f" `{tag}`" if tag else ""

        # 优先在内置经典歌词库中查找
        lyric_text = get_lyrics(title)
        if not lyric_text and song.get("lyrics"):
            lyric_text = song["lyrics"]

        if not lyric_text:
            await query.answer("暂未找到该歌曲的完整文字歌词", show_alert=True)
            return

        # 防御 Telegram 4096 字符上限限制
        if len(lyric_text) > 3600:
            lyric_text = lyric_text[:3600] + "\n\n...(歌词篇幅较长，请配合音频收听完整版)..."


        await query.answer()
        builder = InlineKeyboardBuilder()
        builder.button(text="🎵 再次播放", callback_data=f"play:{song_id}")
        builder.button(text="🎲 随缘一曲", callback_data="random_song")
        builder.adjust(2)

        lyric_card = (
            f"📝 **《{escape_md(title)}》· 歌词**\n"
            f"💿 专辑：《{escape_md(album)}》{year_str}{tag_str}\n"
            f"🎸 词曲 / 演唱：李志\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{escape_md(lyric_text)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 李志音乐点播站 [@libi\\_music\\_bot](https://t.me/libi_music_bot)"
        )
        await query.message.answer(lyric_card, reply_markup=builder.as_markup(), parse_mode="Markdown")

    @dp.callback_query(F.data == "random_song")
    async def cb_random_song(query: CallbackQuery):
        song = db.get_random_song()
        if not song:
            await query.answer("曲库为空或正在同步中", show_alert=True)
            return

        year_str = f" [{song['year']}年]" if song.get("year") else ""
        tag = get_album_tag(song["album"])
        tag_str = f" {tag}" if tag else ""
        await query.answer(f"🎲 为你随机挑选: {song['title']}{year_str}{tag_str}")

        markup = get_song_control_markup(song["id"], song["album"])
        try:
            await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=song["channel_id"],
                message_id=song["message_id"],
                reply_markup=markup
            )
        except Exception:
            await bot.send_audio(
                chat_id=query.message.chat.id,
                audio=song["file_id"],
                caption=f"🎲 随缘一曲：{song['title']} - 《{song['album']}》{year_str}{tag_str}",
                reply_markup=markup
            )

    @dp.callback_query(F.data == "search_guide")
    async def cb_search_guide(query: CallbackQuery):
        guide = (
            f"🔍 **李志曲库智能检索指南：**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"你无需点击复杂菜单，直接在当前对话框中给我发送文字即可！\n\n"
            f"📌 **支持的搜索方式：**\n"
            f"1. **歌名全称或关键字**：如 `关于郑州的记忆`、`梵高`、`天空之城`\n"
            f"2. **拼音首字母缩写**：如 `fgxs` (梵高先生)、`zz` (关于郑州的记忆)、`tkzc` (天空之城)、`syldxt` (山阴路的夏天)\n"
            f"3. **专辑名称**：如 `应天大街`、`1701`、`叁缺壹`\n"
            f"4. **全局行内分享**：在任意聊天框输入 `@{(await bot.get_me()).username} 歌名` 实时搜索并卡片发送给好友！"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        try:
            await query.message.edit_caption(caption=guide, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            try:
                await query.message.edit_text(guide, reply_markup=builder.as_markup(), parse_mode="Markdown")
            except Exception:
                await query.message.answer(guide, reply_markup=builder.as_markup(), parse_mode="Markdown")
        await query.answer()

    @dp.message(F.text)
    async def handle_search(message: Message):
        query_text = message.text.strip()
        if query_text.startswith("/"):
            return

        safe_query = escape_md(query_text)
        results = db.search_songs(query_text, limit=12)
        if not results:
            await message.answer(
                f"🔍 抱歉，曲库中未找到与「`{safe_query}`」相关的歌曲或专辑。\n"
                f"你可以尝试输入歌名关键字或拼音缩写（如 `fgxs`、`zz`、`tkzc`）。",
                parse_mode="Markdown"
            )
            return

        builder = InlineKeyboardBuilder()
        for s in results:
            year_str = f"[{s['year']}年] " if s.get("year") else ""
            tag = get_album_tag(s['album'])
            tag_str = f" {tag}" if tag else ""
            builder.button(
                text=f"{year_str}{s['title']} - 《{s['album']}》{tag_str}",
                callback_data=f"play:{s['id']}"
            )
        builder.adjust(1)
        builder.row(
            InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
        )
        await message.answer(
            f"🔍 找到以下包含「`{safe_query}`」的曲目，点击即可直接收听：",
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )


    @dp.inline_query()
    async def handle_inline_query(inline_query: InlineQuery):
        q = inline_query.query.strip()
        results = db.search_songs(q, limit=20) if q else db.get_random_songs(limit=10)
        articles = []
        for s in results:
            year_str = f" [{s['year']}年]" if s.get("year") else ""
            tag = get_album_tag(s['album'])
            tag_str = f" {tag}" if tag else ""
            articles.append(
                InlineQueryResultCachedAudio(
                    id=str(s["id"]),
                    audio_file_id=s["file_id"],
                    caption=f"🎵 {s['title']} - 《{s['album']}》{year_str}{tag_str} | 李志"
                )
            )
        cache_duration = 60 if q else 10
        await inline_query.answer(articles, cache_time=cache_duration, is_personal=True)

    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="🏠 主菜单与曲库浏览"),
            BotCommand(command="quote", description="📜 每日歌词日签"),
            BotCommand(command="radio", description="🎧 心境与场景电台"),
            BotCommand(command="random", description="🎲 随缘一曲 (随机听歌)"),
            BotCommand(command="stats", description="📊 歌词词频大数据"),
            BotCommand(command="search", description="🔍 搜歌指南 (拼音/歌名)")
        ])
    except Exception as e:
        logger.warning(f"设置快捷指令菜单失败: {e}")

    bot_info = await bot.get_me()
    logger.info("=" * 60)
    logger.info(f"🚀 Telegram 音乐点播机器人 @{bot_info.username} 已上线运行！")
    logger.info("=" * 60)

    while True:
        try:
            await dp.start_polling(bot)
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

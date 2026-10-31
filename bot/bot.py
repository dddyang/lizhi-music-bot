import asyncio
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultCachedAudio,
    InlineQueryResultArticle,
    InputTextMessageContent,
    InputMediaAudio,
    FSInputFile,
    BotCommand
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, DB_PATH, CHANNEL_ID
from database import MusicDatabase
from lyrics_bank import get_lyrics
from mood_quotes import get_song_exact_quote

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

# 全局常驻单消息核心管理器（双层架构：内存级极速命中 + SQLite 数据库持久化兜底）
USER_ACTIVE_HUB: Dict[int, int] = {}      # user_id -> 当前唯一常驻控制台消息 ID (内存缓存)
USER_LAST_CAT: Dict[int, str] = {}        # user_id -> 最后浏览的专辑分类（内存缓存）
SEND_ALL_COOLDOWN: Dict[int, float] = {}  # user_id -> 连续点播防刷限制

def get_active_hub_mid(user_id: int) -> Optional[int]:
    """获取用户常驻消息ID（优先内存缓存，未命中查 SQLite 持久化，防服务重启断层）"""
    if user_id in USER_ACTIVE_HUB:
        return USER_ACTIVE_HUB[user_id]
    try:
        sess = db.get_user_session(user_id)
        if sess and sess.get("message_id"):
            mid = sess["message_id"]
            USER_ACTIVE_HUB[user_id] = mid
            return mid
    except Exception as e:
        logger.warning(f"获取持久化会话失败: {e}")
    return None

def set_active_hub_mid(user_id: int, chat_id: int, message_id: int, last_cat: Optional[str] = None):
    """同步更新内存缓存与 SQLite 持久化会话"""
    USER_ACTIVE_HUB[user_id] = message_id
    if last_cat:
        USER_LAST_CAT[user_id] = last_cat
    try:
        db.set_user_session(user_id, chat_id, message_id, last_cat)
    except Exception as e:
        logger.warning(f"持久化保存会话失败: {e}")

def get_user_last_cat(user_id: int) -> str:
    """获取用户最后浏览的唱片分类（优先内存，未命中查数据库）"""
    if user_id in USER_LAST_CAT:
        return USER_LAST_CAT[user_id]
    try:
        sess = db.get_user_session(user_id)
        if sess and sess.get("last_category"):
            cat = sess["last_category"]
            USER_LAST_CAT[user_id] = cat
            return cat
    except Exception as e:
        logger.warning(f"获取持久化分类失败: {e}")
    return "chronology"

def set_user_last_cat(user_id: int, last_cat: str):
    """记录用户最后浏览分类"""
    USER_LAST_CAT[user_id] = last_cat
    try:
        db.update_user_last_cat(user_id, last_cat)
    except Exception as e:
        logger.warning(f"持久化保存分类记忆失败: {e}")

# 1. 经典录音室创作专辑 (共9张)
STUDIO_ALBUMS = {
    "被禁忌的游戏", "梵高先生", "这个世界会好吗", "我爱南京",
    "你好，郑州", "F", "李志 1701", "8",
    "在每一条伤心的应天大街上"
}

# 2. 官方现场演出专辑 (共15张，海外现场移入日本/吉隆坡专区)
OFFICIAL_LIVE_ALBUMS = {
    "二零零九年十月十六日事件", "工体东路没有人", "我们也爱南京",
    "Imagine Live", "勾三搭四", "108个关键词", "I/O",
    "动静 (2015 Live)", "看见 (李志2015巡回演唱会)",
    "李志北京不插电现场 2016 Live", "李志、电声与管弦乐",
    "爵士乐与不插电新编12首", "李志、电声与管弦乐II",
    "2025 叁缺壹 吉隆坡站", "2025 叁缺壹 吉隆坡现场全场实况"
}

# 3. 日本官方唱片与东京现场 (共4张：波丽佳音限定三部曲 + 2024东京Zepp现场)
JAPAN_ALBUMS = {
    "Best Selection Songs 2004-2019 (Vol.1)",
    "Best Selection Songs 2004-2018 (Vol.2)",
    "Best Selection Songs 2004-2018 (Vol.3)",
    "叁缺壹 (2024 Tokyo Live)"
}

# 4. 民间巡演专场现场与乐迷合辑 (共7张 Bootleg)
BOOTLEG_AND_FAN_ALBUMS = {
    "义乌隔壁酒吧", "杭州酒球会一身酒气", "“挺”不插电巡演 郑州站",
    "金城兰州", "洗心革面 跨年音乐会", "杂选", "李志LIVE精选"
}

# 兼容历史分类别名
SELECTION_AND_TOUR_ALBUMS = JAPAN_ALBUMS | BOOTLEG_AND_FAN_ALBUMS

# 5. 年代创作时光机映射
ERA_MAPPING = {
    "era_04_08": {
        "title": "🌱 2004 — 2008：残酷青春与孤勇民谣期 (3盘)",
        "desc": "一把木吉他、出租屋与南京街头的残酷独白，包含《被禁忌的游戏》《梵高先生》《这个世界会好吗》三大底本。",
        "albums": ["被禁忌的游戏", "梵高先生", "这个世界会好吗"]
    },
    "era_09_11": {
        "title": "🎸 2009 — 2011：南京史诗与乐队成型期 (10盘)",
        "desc": "《我爱南京》双碟奠定人文地标，工体东路狂欢与动物凶猛巡演，编制全面走向成熟。",
        "albums": ["我爱南京", "二零零九年十月十六日事件", "工体东路没有人", "你好，郑州", "义乌隔壁酒吧", "F", "我们也爱南京", "杭州酒球会一身酒气", "Imagine Live", "杂选"]
    },
    "era_12_15": {
        "title": "🔥 2012 — 2015：工体看见与全国巡演巅峰期 (8盘)",
        "desc": "从 Livehouse 走向万人体育馆巡演，金曲奖入围作《1701》、跨年现场狂欢《iO》《勾三搭四》与《看见》。",
        "albums": ["“挺”不插电巡演 郑州站", "108个关键词", "李志 1701", "I/O", "勾三搭四", "看见 (李志2015巡回演唱会)", "动静 (2015 Live)", "金城兰州"]
    },
    "era_16_18": {
        "title": "🎻 2016 — 2018：电声管弦与跨界美学探索期 (7盘)",
        "desc": "大编制电声与管弦乐跨界交响，爵士乐不插电新编，数万人跨年巅峰现场。",
        "albums": ["8", "在每一条伤心的应天大街上", "李志北京不插电现场 2016 Live", "李志、电声与管弦乐", "爵士乐与不插电新编12首", "李志、电声与管弦乐II", "李志LIVE精选"]
    },
    "era_19_25": {
        "title": "🌏 2019 — 2025：洗心革面跨年与海外吉隆坡回归 (7盘)",
        "desc": "洗心革面最后跨年夜、日本波丽佳音限定重制三部曲，以及 2024 东京、2025 叁缺壹吉隆坡万人演唱会全场重聚！",
        "albums": ["洗心革面 跨年音乐会", "Best Selection Songs 2004-2019 (Vol.1)", "Best Selection Songs 2004-2018 (Vol.2)", "Best Selection Songs 2004-2018 (Vol.3)", "叁缺壹 (2024 Tokyo Live)", "2025 叁缺壹 吉隆坡现场全场实况", "2025 叁缺壹 吉隆坡站"]
    }
}

CITIES = ["南京", "郑州", "兰州", "杭州", "北京", "成都", "定西"]

UNOFFICIAL_ALBUM_TAGS = {
    "Best Selection Songs 2004-2019 (Vol.1)": {"tag": "[日本限定精选]", "desc": "🇯🇵 **唱片性质**：`[日本波丽佳音正规出版]`（2019年《叙事歌》限定精选，名曲高保真母带归档）"},
    "Best Selection Songs 2004-2018 (Vol.2)": {"tag": "[日本限定精选]", "desc": "🇯🇵 **唱片性质**：`[日本波丽佳音正规出版]`（2020年《倒影》限定精选，海外母带重制版）"},
    "Best Selection Songs 2004-2018 (Vol.3)": {"tag": "[日本限定精选]", "desc": "🇯🇵 **唱片性质**：`[日本波丽佳音正规出版]`（2021年《装蒜》Live精选，海外黑胶/CD限定发售）"},
    "叁缺壹 (2024 Tokyo Live)": {"tag": "[日本东京现场]", "desc": "🇯🇵 **演出实况**：`[2024 东京 Zepp Haneda 现场]`（日本限定复出首演高保真母带录音）"},
    "义乌隔壁酒吧": {"tag": "[民间现场录音]", "desc": "⚠️ **版本性质**：`[民间现场录音]`（2009年巡演收官战乐迷 Bootleg，含绝唱版《梵高先生》）"},
    "杭州酒球会一身酒气": {"tag": "[民间现场录音]", "desc": "⚠️ **版本性质**：`[民间现场录音]`（杭州酒球会 Livehouse 专场乐迷现场录音 Bootleg）"},
    "“挺”不插电巡演 郑州站": {"tag": "[民间现场录音]", "desc": "⚠️ **版本性质**：`[民间现场录音]`（2014年巡演民间录音，非官方实体唱片）"},
    "洗心革面 跨年音乐会": {"tag": "[民间现场录音]", "desc": "⚠️ **版本性质**：`[民间现场录音]`（2018-2019 欧拉跨年独家直播提取版）"},
    "金城兰州": {"tag": "[民间现场录音]", "desc": "⚠️ **版本性质**：`[民间现场录音]`（翻唱低苦艾《兰州兰州》现场提取）"},
    "杂选": {"tag": "[乐迷合辑]", "desc": "⚠️ **版本性质**：`[乐迷合辑]`（早期散落单曲、Demo 与未发行版本合辑）"},
    "李志LIVE精选": {"tag": "[乐迷合辑]", "desc": "⚠️ **版本性质**：`[乐迷合辑]`（历年巡演高光片段剪辑合集）"}
}

VIDEO_CAT_ICONS = {
    "历年跨年与演唱会现场": "🎪",
    "叁叁肆巡演官方纪录片": "🚗",
    "逼哥夜话与深度对谈": "🎙️",
    "精选专访与珍贵纪录片": "🎥",
    "经典现场单曲精选": "🎸",
}

def get_album_tag(album_name: str) -> str:
    info = UNOFFICIAL_ALBUM_TAGS.get(album_name)
    return info["tag"] if info else ""

def get_album_desc(album_name: str) -> str:
    info = UNOFFICIAL_ALBUM_TAGS.get(album_name)
    return f"\n{info['desc']}\n" if info else ""

def format_duration(seconds: int) -> str:
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def format_size(bytes_size: int) -> str:
    if not bytes_size:
        return "未知规格"
    mb = bytes_size / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"

def escape_md(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_*`\[])', r'\\\1', str(text))


# ==================== 单一消息总线引擎 (Single-Message Hub Engine) ====================
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
    极客核心引擎：保证整个机器人会话从始至终在唯一一条消息框内流动！
    优先原地 edit；如果跨越媒体类型无法原地 edit，自动删除上一条旧消息并呈现新控制台。
    即使后台服务发生重启或网络重连，SQLite 持久化会话也能确保旧消息被精确识别并平滑接管，杜绝多条消息。
    """
    # 1. 如果有 CallbackQuery 且当前消息是纯文本或 Caption，原地更新
    if query and query.message:
        is_audio = getattr(query.message, "audio", None) is not None
        has_photo = getattr(query.message, "photo", None) is not None

        # 如果要求展示海报，但当前消息不是图片消息，删除旧消息重新发带图控制台
        if prefer_photo and not has_photo and not is_audio and WELCOME_BANNER.exists():
            try:
                await query.message.delete()
            except Exception:
                pass
        elif not is_audio:
            # 优先尝试原地更新
            try:
                if has_photo:
                    await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                else:
                    await query.message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)
                set_active_hub_mid(user_id, chat_id, query.message.message_id)
                await query.answer()
                return
            except Exception:
                try:
                    await query.message.edit_caption(caption=text, reply_markup=reply_markup, parse_mode="Markdown")
                    set_active_hub_mid(user_id, chat_id, query.message.message_id)
                    await query.answer()
                    return
                except Exception:
                    # 原地编辑失败（如超出1024字长限制），删除旧消息以便下方重新发送
                    try:
                        await query.message.delete()
                    except Exception:
                        pass

        if is_audio:
            # 如果当前消息是音频消息，用户要求“返回主菜单/返回专辑”等文字界面：
            # 为了不产生第 2 条消息，将原音频消息删除，并在原位呈现控制台
            try:
                await query.message.delete()
            except Exception:
                pass

    # 2. 如果之前记录过旧消息 ID（持久化恢复），清理旧消息以保持聊天框内永远只有一条
    old_mid = get_active_hub_mid(user_id)
    if old_mid and (not query or query.message.message_id != old_mid):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_mid)
        except Exception:
            pass

    # 3. 发送新的控制台消息并持久化记录 ID（支持海报图首发）
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


def get_welcome_text(stats: dict, v_stats: dict) -> str:
    songs_cnt = stats.get("songs", 0)
    albums_cnt = stats.get("albums", 0)
    videos_cnt = v_stats.get("videos", 0)
    return (
        f"🎸 **李志硬核随身点播站 · Li Zhi Music Station**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎙️ **音乐人**：李志\n"
        f"💿 **唱片收录**：`{albums_cnt}` 张全集 (2004 — 2025 编年史)\n"
        f"🎵 **曲目收录**：`{songs_cnt}` 首 (高保真音轨 · 双轨纯净歌词)\n"
        f"🎬 **影音专区**：`{videos_cnt}` 部 (全场跨年/巡演纪录片/逼哥夜话)\n"
        f"📻 **官方频道**：[点击进入李志音乐分享频道](https://t.me/libimusic)\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 **快捷点播导览 (所有功能单消息内流转)：**\n"
        f"• 🔍 **智能点播**：直接发送歌名、视频名或拼音缩写（如 `关于郑州`、`fgxs`、`夜话`、`跨年`）\n"
        f"• 💿 **五大专辑分类**：录音室全集、官方现场Live、日本唱片与东京现场、民间现场合辑与编年史总览\n"
        f"• 🏙️ **城市地标**：一键收听南京、郑州、兰州、成都等音乐地标金曲\n"
        f"• ⏳ **年代时光机**：按 2004~2025 创作阶段分类聆听时代演变\n"
        f"• 🎬 **原画影音**：74 部原画视频免下载流媒体秒级在线观看"
    )


def get_main_menu_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 智能搜歌搜视频指南 (拼音/歌名/大片)", callback_data="search_guide")
    )
    builder.row(
        InlineKeyboardButton(text="🎲 随缘一曲 · 听听逼哥 (随机盲盒)", callback_data="random:track")
    )
    builder.row(
        InlineKeyboardButton(text="💿 经典录音室全集 (9张)", callback_data="cat:studio"),
        InlineKeyboardButton(text="🎸 官方现场Live (15张)", callback_data="cat:live")
    )
    builder.row(
        InlineKeyboardButton(text="🇯🇵 日本唱片与东京现场 (4张)", callback_data="cat:japan"),
        InlineKeyboardButton(text="🗂️ 民间现场与合辑 (7张)", callback_data="cat:bootleg")
    )
    builder.row(
        InlineKeyboardButton(text="📅 35张全集编年史", callback_data="cat:chronology"),
        InlineKeyboardButton(text="⏳ 20年创作年代时光机", callback_data="menu:era")
    )
    builder.row(
        InlineKeyboardButton(text="🏙️ 城市地标点播专区", callback_data="menu:city"),
        InlineKeyboardButton(text="🎬 74部高清原画影音专区", callback_data="menu:video")
    )
    builder.row(
        InlineKeyboardButton(text="📢 官方音乐频道 @libimusic", url="https://t.me/libimusic")
    )
    return builder.as_markup()


def build_albums_markup_by_filter(filter_type: str) -> InlineKeyboardMarkup:
    all_albums = db.get_all_albums()
    builder = InlineKeyboardBuilder()

    if filter_type == "studio":
        filtered = [a for a in all_albums if a["album"] in STUDIO_ALBUMS]
    elif filter_type == "live":
        filtered = [a for a in all_albums if a["album"] in OFFICIAL_LIVE_ALBUMS]
    elif filter_type == "japan":
        filtered = [a for a in all_albums if a["album"] in JAPAN_ALBUMS]
    elif filter_type == "bootleg":
        filtered = [a for a in all_albums if a["album"] in BOOTLEG_AND_FAN_ALBUMS]
    elif filter_type == "selection":
        # 兼容旧回调按钮
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


def build_song_caption(song: dict, album_name: str, cur_idx: int = 0, total_cnt: int = 0) -> str:
    """构建单曲播放标准状态下的 Caption（呈现硬核母带规格徽章，单消息内沉浸播放）"""
    title = song["title"]
    year = song.get("year")
    year_str = f" [{year}年]" if year else ""
    tag = get_album_tag(album_name)
    tag_str = f" `{tag}`" if tag else ""
    idx_str = f" ({cur_idx}/{total_cnt})" if total_cnt else ""
    quality_badge = db.get_song_quality_tag(song)

    return (
        f"🎵 **{escape_md(title)}**{idx_str}\n"
        f"💿 专辑：《{escape_md(album_name)}》{year_str}{tag_str}\n"
        f"🎛️ 音质规格：`{quality_badge}`\n"
        f"🎸 词曲 / 演唱：李志\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 点击下方按钮可在当前消息内自由切歌、展开歌词与切换现场版本"
    )


def build_lyrics_caption(song: dict, album_name: str, lyric_text: str) -> str:
    """构建展开歌词状态下的 Caption（严格防御 1024 字符限制，支持无缝折叠）"""
    title = song["title"]
    tag = get_album_tag(album_name)
    tag_str = f" `{tag}`" if tag else ""

    header = f"📝 **《{escape_md(title)}》· 纯净歌词**{tag_str}\n━━━━━━━━━━━━━━━━━━━\n\n"
    footer = "\n\n━━━━━━━━━━━━━━━━━━━\n💡 点击下方【🔼 收起歌词】可折叠收起"

    max_lyric_len = 1000 - len(header) - len(footer)
    clean_lyrics = lyric_text.strip()
    if len(clean_lyrics) > max_lyric_len:
        clean_lyrics = clean_lyrics[:max_lyric_len - 30] + "\n...(篇幅较长已精简折叠，配合音频收听)..."

    return f"{header}{escape_md(clean_lyrics)}{footer}"


def get_song_control_markup(song_id: int, album_name: str, lyrics_expanded: bool = False) -> InlineKeyboardMarkup:
    """生成随身播放器专业控制台键盘（支持在当前消息内切歌与折叠歌词）"""
    builder = InlineKeyboardBuilder()

    song = db.get_song_by_id(song_id)
    prev_song, next_song, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)

    # 1. 切歌导航行（原地切换下一首/上一首）
    nav_row = []
    if prev_song:
        nav_row.append(InlineKeyboardButton(text="⏮️ 上一首", callback_data=f"play_inplace:{prev_song['id']}:{album_name}"))
    else:
        nav_row.append(InlineKeyboardButton(text="⏮️ 已是首首", callback_data="noop"))

    pos_label = f"🎵 {cur_idx}/{total_cnt}" if total_cnt else "🎵 播放中"
    nav_row.append(InlineKeyboardButton(text=pos_label, callback_data=f"album:{album_name}"))

    if next_song:
        nav_row.append(InlineKeyboardButton(text="下一首 ⏭️", callback_data=f"play_inplace:{next_song['id']}:{album_name}"))
    else:
        nav_row.append(InlineKeyboardButton(text="已是末首 ⏭️", callback_data="noop"))
    builder.row(*nav_row)

    # 2. 歌词按钮（展开 / 收起 动态切换）与整专连播
    if lyrics_expanded:
        lyric_btn = InlineKeyboardButton(text="🔼 收起歌词", callback_data=f"lyric_toggle:{song_id}:{album_name}:collapse")
    else:
        lyric_btn = InlineKeyboardButton(text="📝 展开歌词", callback_data=f"lyric_toggle:{song_id}:{album_name}:expand")

    builder.row(
        lyric_btn,
        InlineKeyboardButton(text="📦 连续听整张", callback_data=f"send_all:{album_name}")
    )

    # 3. 同名现场版本切换
    core_title, other_versions = db.get_other_versions(song_id)
    if other_versions:
        builder.row(
            InlineKeyboardButton(text=f"🔄 切换其他现场版本 ({len(other_versions)}个)", callback_data=f"versions_menu:{song_id}:{album_name}")
        )

    # 4. 音影互通联动
    if song:
        rel_video = db.get_related_video_for_song(song["title"])
        if rel_video:
            video_link = f"https://t.me/libimusic/{rel_video['message_id']}"
            builder.row(
                InlineKeyboardButton(text=f"🎬 观看现场高清原画视频: {rel_video['title'][:14]}..", url=video_link)
            )

    # 5. 底部返回
    builder.row(
        InlineKeyboardButton(text="💿 返回专辑曲目", callback_data=f"album:{album_name}"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )
    return builder.as_markup()


def get_versions_markup(current_song_id: int, album_name: str, versions: List[Dict]) -> InlineKeyboardMarkup:
    """在当前消息内原地弹出同名版本列表键盘"""
    builder = InlineKeyboardBuilder()
    for v in versions[:16]:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        v_title = v['title']
        if len(v_title) > 26:
            v_title = v_title[:24] + ".."
        builder.button(
            text=f"🎵 {year_str}{v_title} - 《{v['album']}》",
            callback_data=f"play_inplace:{v['id']}:{v['album']}"
        )
    builder.adjust(1)
    builder.row(
        InlineKeyboardButton(text="🔙 取消，返回播放控制台", callback_data=f"play_inplace:{current_song_id}:{album_name}")
    )
    return builder.as_markup()


# 影音模块辅助
def get_video_menu_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    categories = db.get_all_video_categories()
    for cat_name, cnt in categories:
        icon = VIDEO_CAT_ICONS.get(cat_name, "🎬")
        builder.row(
            InlineKeyboardButton(text=f"{icon} {cat_name} ({cnt}部)", callback_data=f"vcat:{cat_name}:0")
        )
    builder.row(
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )
    return builder.as_markup()


def build_video_category_markup(category: str, offset: int = 0, page_size: int = 6) -> Tuple[str, InlineKeyboardMarkup]:
    videos, total = db.get_videos_by_category(category, limit=page_size, offset=offset)
    builder = InlineKeyboardBuilder()

    for v in videos:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        title = v['title']
        if len(title) > 28:
            title = title[:26] + ".."
        btn_text = f"🎬 {year_str}{title}"
        builder.row(
            InlineKeyboardButton(text=btn_text, callback_data=f"vdetail:{v['id']}:{category}:{offset}")
        )

    nav_buttons = []
    current_page = (offset // page_size) + 1
    total_pages = max(1, (total + page_size - 1) // page_size)

    if offset > 0:
        prev_offset = max(0, offset - page_size)
        nav_buttons.append(InlineKeyboardButton(text="⬅️ 上一页", callback_data=f"vcat:{category}:{prev_offset}"))

    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="noop"))

    if offset + page_size < total:
        next_offset = offset + page_size
        nav_buttons.append(InlineKeyboardButton(text="下一页 ➡️", callback_data=f"vcat:{category}:{next_offset}"))

    builder.row(*nav_buttons)
    builder.row(
        InlineKeyboardButton(text="🔙 返回影音专区", callback_data="menu:video"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )

    icon = VIDEO_CAT_ICONS.get(category, "🎬")
    text = (
        f"{icon} **李志影音专区 · {category}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"共收录 `{total}` 部珍贵影音（第 `{current_page}/{total_pages}` 页）\n"
        f"💡 点击下方视频名称查看详情与播放："
    )
    return text, builder.as_markup()


def build_video_detail_card(v: dict, back_cat: Optional[str] = None, back_offset: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    title = v["title"]
    category = v.get("category", "影音视频")
    year = v.get("year")
    year_str = f"📅 **演出年份**：{year} 年\n" if year else ""
    dur = v.get("duration", 0)
    dur_str = f"⏳ **视频时长**：约 {format_duration(dur)}\n" if dur else ""
    size = v.get("file_size", 0)
    size_str = f"💾 **文件规格**：约 {format_size(size)}\n" if size else ""
    channel_link = f"https://t.me/libimusic/{v['message_id']}"

    text = (
        f"🎬 **《{title}》**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📂 **收录专区**：{category}\n"
        f"{year_str}"
        f"{dur_str}"
        f"{size_str}"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💡 **观看方式提示：**\n"
        f"• 点击【🍿 在频道中直接观看】可立即在 Telegram 内置原画播放器中全屏流畅播放\n"
        f"• 点击【▶️ 推送到私聊播放】将由机器人将视频转推至当前对话框"
    )

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🍿 在频道中直接观看", url=channel_link),
        InlineKeyboardButton(text="▶️ 推送到私聊播放", callback_data=f"vpush:{v['id']}")
    )

    back_row = []
    if back_cat:
        back_row.append(InlineKeyboardButton(text="🔙 返回列表", callback_data=f"vcat:{back_cat}:{back_offset}"))
    else:
        back_row.append(InlineKeyboardButton(text="🔙 返回影音专区", callback_data="menu:video"))
    back_row.append(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
    builder.row(*back_row)

    return text, builder.as_markup()


# ==================== 机器人主程序与事件调度 ====================
async def start_bot():
    if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
        logger.error("❌ 请在 .env 中正确配置 BOT_TOKEN 后再启动机器人！")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(Command("start", "menu"))
    async def cmd_start(message: Message):
        global USER_ACTIVE_HUB
        user_id = message.from_user.id
        stats = db.get_stats()
        v_stats = db.get_video_stats()
        text = get_welcome_text(stats, v_stats)
        markup = get_main_menu_markup()

        # 如果允许，尝试删除用户输入的 /start 命令消息，保证聊天框极致整洁
        try:
            await message.delete()
        except Exception:
            pass

        # 清理旧常驻消息（如果存在）
        old_mid = get_active_hub_mid(user_id)
        if old_mid:
            try:
                await bot.delete_message(chat_id=message.chat.id, message_id=old_mid)
            except Exception:
                pass

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

    @dp.message(Command("video"))
    async def cmd_video_menu(message: Message):
        global USER_ACTIVE_HUB
        user_id = message.from_user.id
        try:
            await message.delete()
        except Exception:
            pass
        text = (
            "🎬 **李志高清影音专区 · Li Zhi Video Archive**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "全量收录 74 部李志原画现场、巡演纪录片与对谈实录：\n\n"
            "• 🎪 **历年跨年现场**：2008~2019 跨年全场与工体/欧拉演出实况\n"
            "• 🚗 **叁叁肆巡演片**：山东、安徽、陕北等各省巡演深度纪录\n"
            "• 🎙️ **逼哥夜话对谈**：深夜开讲、真性情聊天全收录\n"
            "• 🎥 **专访与纪录片**：十三月、十三邀、看见巡演全景\n"
            "• 🎸 **经典现场单曲**：跨年与巡演震撼单曲原画剪辑\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 请选择你想观看的专题分类："
        )
        await render_hub(bot, message.chat.id, user_id, text, get_video_menu_markup())

    @dp.callback_query(F.data == "menu:video")
    async def cb_video_menu(query: CallbackQuery):
        text = (
            "🎬 **李志高清影音专区 · Li Zhi Video Archive**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "全量收录 74 部李志原画现场、巡演纪录片与对谈实录：\n\n"
            "• 🎪 **历年跨年现场**：2008~2019 跨年全场与工体/欧拉演出实况\n"
            "• 🚗 **叁叁肆巡演片**：山东、安徽、陕北等各省巡演深度纪录\n"
            "• 🎙️ **逼哥夜话对谈**：深夜开讲、真性情聊天全收录\n"
            "• 🎥 **专访与纪录片**：十三月、十三邀、看见巡演全景\n"
            "• 🎸 **经典现场单曲**：跨年与巡演震撼单曲原画剪辑\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "💡 请选择你想观看的专题分类："
        )
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, get_video_menu_markup(), query=query)

    @dp.callback_query(F.data.startswith("vcat:"))
    async def cb_video_cat(query: CallbackQuery):
        parts = query.data.split(":")
        category = parts[1]
        offset = int(parts[2]) if len(parts) > 2 else 0
        text, markup = build_video_category_markup(category, offset=offset)
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, markup, query=query)

    @dp.callback_query(F.data.startswith("vdetail:"))
    async def cb_video_detail(query: CallbackQuery):
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

    @dp.callback_query(F.data.startswith("vpush:"))
    async def cb_video_push(query: CallbackQuery):
        video_id = int(query.data.split("vpush:", 1)[1])
        v = db.get_video_by_id(video_id)
        if not v:
            await query.answer("视频信息未找到", show_alert=True)
            return

        await query.answer(f"正在为你推送：《{v['title']}》...")
        channel_link = f"https://t.me/libimusic/{v['message_id']}"
        ctrl_markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🍿 直达频道全屏观看", url=channel_link)
            ]
        ])

        try:
            await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=v["channel_id"],
                message_id=v["message_id"],
                reply_markup=ctrl_markup
            )
        except Exception as e:
            logger.warning(f"copy_message 视频失败 ({e})，引导用户使用频道直达链接...")
            fail_msg = (
                f"🎬 **《{v['title']}》**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ **提示**：该视频规格为 `{format_size(v['file_size'])}`，超出 Telegram 私聊直接转播上限。\n"
                f"请点击下方按钮直接在频道中享受 1080P 原画免下载播放！"
            )
            await query.message.answer(fail_msg, reply_markup=ctrl_markup, parse_mode="Markdown")

    @dp.callback_query(F.data == "noop")
    async def cb_noop(query: CallbackQuery):
        await query.answer()

    @dp.message(Command("search", "help"))
    async def cmd_search_guide(message: Message):
        user_id = message.from_user.id
        try:
            await message.delete()
        except Exception:
            pass
        bot_me = await bot.get_me()
        guide = (
            f"🔍 **李志曲库与影音智能检索指南：**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"你无需点击复杂菜单，直接在当前对话框中发送文字即可！\n\n"
            f"📌 **支持的搜索方式：**\n"
            f"1. **歌名全称或关键字**：如 `关于郑州的记忆`、`梵高`、`天空之城`\n"
            f"2. **拼音首字母缩写**：如 `fgxs` (梵高先生)、`zz` (关于郑州的记忆)、`tkzc` (天空之城)\n"
            f"3. **影音视频检索**：如 `跨年`、`洗心革面`、`夜话`、`山东`、`吉隆坡`、`叁叁肆`\n"
            f"4. **城市地标点播**：如 `南京`、`郑州`、`兰州`、`成都`、`北京`\n"
            f"5. **全局行内分享**：在任意聊天框输入 `@{bot_me.username} 歌名` 实时搜索并卡片发送给好友！"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        await render_hub(bot, message.chat.id, user_id, guide, builder.as_markup())

    @dp.callback_query(F.data == "search_guide")
    async def cb_search_guide(query: CallbackQuery):
        bot_me = await bot.get_me()
        guide = (
            f"🔍 **李志曲库与影音智能检索指南：**\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"你无需点击复杂菜单，直接在当前对话框中发送文字即可！\n\n"
            f"📌 **支持的搜索方式：**\n"
            f"1. **歌名全称或关键字**：如 `关于郑州的记忆`、`梵高`、`天空之城`\n"
            f"2. **拼音首字母缩写**：如 `fgxs` (梵高先生)、`zz` (关于郑州的记忆)、`tkzc` (天空之城)\n"
            f"3. **影音视频检索**：如 `跨年`、`洗心革面`、`夜话`、`山东`、`吉隆坡`、`叁叁肆`\n"
            f"4. **城市地标点播**：如 `南京`、`郑州`、`兰州`、`成都`、`北京`\n"
            f"5. **全局行内分享**：在任意聊天框输入 `@{bot_me.username} 歌名` 实时搜索并卡片发送给好友！"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        await render_hub(bot, query.message.chat.id, query.from_user.id, guide, builder.as_markup(), query=query)

    # 城市地标点播
    @dp.message(Command("city"))
    async def cmd_city_menu(message: Message):
        user_id = message.from_user.id
        try:
            await message.delete()
        except Exception:
            pass
        builder = InlineKeyboardBuilder()
        for c in CITIES:
            songs = db.get_songs_by_city(c)
            builder.button(text=f"🏙️ {c} ({len(songs)}首)", callback_data=f"city:{c}")
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
        text = (
            "🏙️ **李志城市地标点播专区 · City Landmark Music**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "李志的音乐里刻满了城市的温度与记忆。\n"
            "请挑选你想聆听的城市地标金曲："
        )
        await render_hub(bot, message.chat.id, user_id, text, builder.as_markup())

    @dp.callback_query(F.data == "menu:city")
    async def cb_city_menu(query: CallbackQuery):
        builder = InlineKeyboardBuilder()
        for c in CITIES:
            songs = db.get_songs_by_city(c)
            builder.button(text=f"🏙️ {c} ({len(songs)}首)", callback_data=f"city:{c}")
        builder.adjust(2)
        builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
        text = (
            "🏙️ **李志城市地标点播专区 · City Landmark Music**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "李志的音乐里刻满了城市的温度与记忆。\n"
            "请挑选你想聆听的城市地标金曲："
        )
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)

    @dp.callback_query(F.data.startswith("city:"))
    async def cb_city_detail(query: CallbackQuery):
        city = query.data.split("city:", 1)[1]
        songs = db.get_songs_by_city(city)
        if not songs:
            await query.answer("该城市暂无收录单曲", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        for s in songs[:15]:
            year_str = f"[{s['year']}年] " if s.get("year") else ""
            title = s['title']
            if len(title) > 26:
                title = title[:24] + ".."
            builder.button(text=f"🎵 {year_str}{title}", callback_data=f"play:{s['id']}")
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

    # 年代时光机
    @dp.message(Command("era"))
    async def cmd_era_menu(message: Message):
        user_id = message.from_user.id
        try:
            await message.delete()
        except Exception:
            pass
        builder = InlineKeyboardBuilder()
        for k, v in ERA_MAPPING.items():
            builder.button(text=v["title"], callback_data=f"era:{k}")
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
        text = (
            "⏳ **李志 20 年创作年代时光机 · Time Machine**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "回溯李志 2004 — 2025 年 20 年音乐探索历程。\n"
            "请选择你想穿梭的创作年代："
        )
        await render_hub(bot, message.chat.id, user_id, text, builder.as_markup())

    @dp.callback_query(F.data == "menu:era")
    async def cb_era_menu(query: CallbackQuery):
        builder = InlineKeyboardBuilder()
        for k, v in ERA_MAPPING.items():
            builder.button(text=v["title"], callback_data=f"era:{k}")
        builder.adjust(1)
        builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
        text = (
            "⏳ **李志 20 年创作年代时光机 · Time Machine**\n"
            "━━━━━━━━━━━━━━━━━━━\n"
            "回溯李志 2004 — 2025 年 20 年音乐探索历程。\n"
            "请选择你想穿梭的创作年代："
        )
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)

    @dp.callback_query(F.data.startswith("era:"))
    async def cb_era_detail(query: CallbackQuery):
        era_key = query.data.split("era:", 1)[1]
        era_info = ERA_MAPPING.get(era_key)
        if not era_info:
            await query.answer("时代未找到", show_alert=True)
            return

        all_albums = db.get_all_albums()
        target_names = set(era_info["albums"])
        matched_albums = [a for a in all_albums if a["album"] in target_names]

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

    # 主菜单与分类
    @dp.callback_query(F.data == "main_menu")
    async def cb_main_menu(query: CallbackQuery):
        stats = db.get_stats()
        v_stats = db.get_video_stats()
        text = get_welcome_text(stats, v_stats)
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, get_main_menu_markup(), query=query, prefer_photo=True)

    @dp.callback_query(F.data == "random:track")
    async def cb_random_track(query: CallbackQuery):
        song = db.get_random_song()
        if not song:
            await query.answer("曲库为空", show_alert=True)
            return

        # 100% 精确获取该歌曲自身所属的原版经典金句，杜绝张冠李戴
        quote = get_song_exact_quote(song["title"], song.get("lyrics"))

        year_str = f" [{song['year']}年]" if song.get("year") else ""
        tag = get_album_tag(song['album'])
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

    @dp.callback_query(F.data.startswith("cat:"))
    async def cb_category(query: CallbackQuery):
        cat = query.data.split("cat:", 1)[1]
        set_user_last_cat(query.from_user.id, cat)
        titles = {
            "studio": "💿 **李志经典录音室创作全集 (共9张)：**",
            "live": "🎸 **李志官方现场Live唱片全本 (共15张)：**",
            "japan": "🇯🇵 **李志日本官方唱片与东京现场 (共4张)：**\n_收录日本波丽佳音限定出版精选三部曲与2024东京Zepp现场：_",
            "bootleg": "🗂️ **李志民间现场巡演录音与乐迷合辑 (共7张)：**",
            "selection": "🗂️ **李志海外唱片与巡演精选合辑：**",
            "chronology": "📅 **李志唱片编年史全集 (2004 — 2025 全35张)：**"
        }
        title_text = titles.get(cat, "💿 **请选择你想收听的专辑：**")
        markup = build_albums_markup_by_filter(cat)
        await render_hub(bot, query.message.chat.id, query.from_user.id, title_text, markup, query=query)

    @dp.callback_query(F.data.startswith("album:"))
    async def cb_album_detail(query: CallbackQuery):
        album_name = query.data.split("album:", 1)[1]
        tracks = db.get_songs_by_album(album_name)
        if not tracks:
            await query.answer("未找到该专辑曲目", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        first_track = tracks[0]
        channel_url = f"https://t.me/libimusic/{first_track['message_id']}" if first_track.get('message_id') else "https://t.me/libimusic"
        builder.row(
            InlineKeyboardButton(text="🎧 在频道中沉浸顺序连播", url=channel_url),
            InlineKeyboardButton(text=f"📦 私聊连播全部{len(tracks)}首", callback_data=f"send_all:{album_name}")
        )

        for idx, t in enumerate(tracks, 1):
            dur_str = f" ({format_duration(t['duration'])})" if t['duration'] else ""
            builder.button(
                text=f"{idx:02d}. {t['title']}{dur_str}",
                callback_data=f"play:{t['id']}"
            )
        builder.adjust(1)

        last_cat = get_user_last_cat(query.from_user.id)
        valid_cats = ("studio", "live", "japan", "bootleg", "chronology")
        if last_cat not in valid_cats:
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

        cat_labels = {
            "studio": "💿 录音室全集",
            "live": "🎸 官方现场Live",
            "japan": "🇯🇵 日本唱片与现场",
            "bootleg": "🗂️ 民间合辑与现场",
            "chronology": "📅 唱片编年史",
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
            f"💡 支持一键连续点播整专，或点击单曲独立收听："
        )
        await render_hub(bot, query.message.chat.id, query.from_user.id, text, builder.as_markup(), query=query)

    # 核心播放调度：始终维持当前唯一消息
    async def switch_song_inplace(query: CallbackQuery, song: dict, album_name: str):
        user_id = query.from_user.id
        song_id = song["id"]
        prev_song, next_song, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)
        caption = build_song_caption(song, album_name, cur_idx, total_cnt)
        markup = get_song_control_markup(song_id, album_name, lyrics_expanded=False)

        # 1. 如果当前点击的消息本身就是音频消息，直接原地无缝切歌
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
            except Exception as e:
                logger.warning(f"edit_media 原地切换失败 ({e})，尝试更新 caption...")
                try:
                    await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
                    set_active_hub_mid(user_id, query.message.chat.id, query.message.message_id)
                    await query.answer(f"▶️ 已切至: {song['title']}")
                    return
                except Exception:
                    pass

        # 2. 如果是从菜单进入播放（原消息是文字卡片），删除原卡片，平滑转入单条播放器
        try:
            await query.message.delete()
        except Exception:
            pass

        # 清理旧的常驻消息（确保屏幕唯一，持久化感知）
        old_mid = get_active_hub_mid(user_id)
        if old_mid and old_mid != query.message.message_id:
            try:
                await bot.delete_message(chat_id=query.message.chat.id, message_id=old_mid)
            except Exception:
                pass

        await query.answer(f"正在为你播放: {song['title']}")
        try:
            new_msg = await bot.send_audio(
                chat_id=query.message.chat.id,
                audio=song["file_id"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=markup
            )
            set_active_hub_mid(user_id, query.message.chat.id, new_msg.message_id)
        except Exception as e:
            logger.warning(f"send_audio 失败 ({e})，使用 copy_message 兜底...")
            new_msg = await bot.copy_message(
                chat_id=query.message.chat.id,
                from_chat_id=song["channel_id"],
                message_id=song["message_id"],
                reply_markup=markup
            )
            set_active_hub_mid(user_id, query.message.chat.id, new_msg.message_id)

    @dp.callback_query(F.data.startswith("play:"))
    async def cb_play_song(query: CallbackQuery):
        song_id = int(query.data.split("play:", 1)[1])
        song = db.get_song_by_id(song_id)
        if not song:
            await query.answer("该歌曲不存在或已被移除", show_alert=True)
            return
        await switch_song_inplace(query, song, song["album"])

    @dp.callback_query(F.data.startswith("play_inplace:"))
    async def cb_play_inplace(query: CallbackQuery):
        parts = query.data.split(":", 2)
        song_id = int(parts[1])
        album_name = parts[2] if len(parts) > 2 else ""
        song = db.get_song_by_id(song_id)
        if not song:
            await query.answer("歌曲不存在", show_alert=True)
            return
        if not album_name:
            album_name = song["album"]
        await switch_song_inplace(query, song, album_name)

    # 歌词展开与收起（单消息原位编辑 Caption）
    @dp.callback_query(F.data.startswith("lyric_toggle:"))
    async def cb_lyric_toggle(query: CallbackQuery):
        parts = query.data.split(":")
        song_id = int(parts[1])
        action = parts[-1]
        album_name = parts[2] if len(parts) >= 4 else ""

        song = db.get_song_by_id(song_id)
        if not song:
            await query.answer("歌曲信息未找到", show_alert=True)
            return
        if not album_name:
            album_name = song["album"]

        prev_song, next_song, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)

        if action == "expand":
            title = song["title"]
            lyric_text = get_lyrics(title)
            if not lyric_text and song.get("lyrics"):
                lyric_text = song["lyrics"]

            if not lyric_text:
                await query.answer("暂未找到该曲目的文字歌词", show_alert=True)
                return

            caption = build_lyrics_caption(song, album_name, lyric_text)
            markup = get_song_control_markup(song_id, album_name, lyrics_expanded=True)
            try:
                await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
                await query.answer("📝 歌词已展开")
            except Exception as e:
                logger.warning(f"edit_caption 展开歌词失败: {e}")
                await query.answer("展开歌词失败")
        else:
            caption = build_song_caption(song, album_name, cur_idx, total_cnt)
            markup = get_song_control_markup(song_id, album_name, lyrics_expanded=False)
            try:
                await query.message.edit_caption(caption=caption, reply_markup=markup, parse_mode="Markdown")
                await query.answer("🔼 歌词已折叠收起")
            except Exception as e:
                logger.warning(f"edit_caption 折叠歌词失败: {e}")
                await query.answer()

    # 同名现场版本切换菜单（在当前消息内原地弹出键盘，零新消息）
    @dp.callback_query(F.data.startswith("versions_menu:"))
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
        except Exception as e:
            logger.warning(f"edit_reply_markup 切换版本菜单失败: {e}")
            await query.answer()

    # 连续点播整张专辑
    @dp.callback_query(F.data.startswith("send_all:"))
    async def cb_send_all(query: CallbackQuery):
        user_id = query.from_user.id
        now_time = asyncio.get_event_loop().time()
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
        for idx, t in enumerate(tracks, 1):
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
            except Exception as e:
                logger.error(f"发送单曲失败: {t['title']}, err: {e}")

        await query.message.answer(
            f"🎉 **专辑《{album_name}》全部 {success_count}/{len(tracks)} 首歌曲已送达！**\n"
            f"祝你聆听愉快 🎸",
            parse_mode="Markdown"
        )

    # 智能搜索：同样收敛在常驻单消息控制台内呈现结果
    @dp.message(F.text)
    async def handle_search(message: Message):
        user_id = message.from_user.id
        query_text = message.text.strip()
        if query_text.startswith("/"):
            return

        # 尝试自动删除用户发的搜索词，保证聊天框极简纯粹
        try:
            await message.delete()
        except Exception:
            pass

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

        # 1. 影音视频结果置顶
        if video_results:
            for v in video_results:
                year_str = f"[{v['year']}年] " if v.get("year") else ""
                v_title = v['title']
                if len(v_title) > 28:
                    v_title = v_title[:26] + ".."
                builder.row(
                    InlineKeyboardButton(
                        text=f"🎬 {year_str}{v_title}",
                        callback_data=f"vdetail:{v['id']}::0"
                    )
                )

        # 2. 歌曲结果紧随其后
        lyric_hits_shown = []
        if song_results:
            for s in song_results:
                year_str = f"[{s['year']}年] " if s.get("year") else ""
                tag = get_album_tag(s['album'])
                tag_str = f" {tag}" if tag else ""
                s_title = s['title']
                if len(s_title) > 26:
                    s_title = s_title[:24] + ".."
                
                # 歌词匹配标记
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

        builder.row(
            InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
        )

        v_cnt = len(video_results)
        s_cnt = len(song_results)
        stats_line = []
        if v_cnt > 0:
            stats_line.append(f"`{v_cnt}` 部影音视频")
        if s_cnt > 0:
            stats_line.append(f"`{s_cnt}` 首单曲")
        stats_str = " 和 ".join(stats_line)

        reply_lines = [
            f"🔍 找到与「`{safe_query}`」相关的 {stats_str}：",
            "━━━━━━━━━━━━━━━━━━━"
        ]
        if lyric_hits_shown:
            reply_lines.append("📝 **歌词逆向命中发现**：")
            reply_lines.extend(lyric_hits_shown[:3])
            reply_lines.append("━━━━━━━━━━━━━━━━━━━")
        reply_lines.append("💡 影音视频支持一键原画播放，单曲点击即刻点播：")
        reply_text = "\n".join(reply_lines)
        await render_hub(bot, message.chat.id, user_id, reply_text, builder.as_markup())

    @dp.inline_query()
    async def handle_inline_query(inline_query: InlineQuery):
        q = inline_query.query.strip()
        results = []

        # 1. 影音视频召回（支持拼音、年份、歌名、大片名称）
        if q:
            video_matches = db.search_videos(q, limit=6)
        else:
            # 默认推荐热门重磅现场大片
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

        # 2. 高保真单曲音频召回（附带母带音质规格徽章）
        song_matches = db.search_songs(q, limit=16) if q else db.get_random_songs(limit=8)
        for s in song_matches:
            year_str = f" [{s['year']}年]" if s.get("year") else ""
            tag = get_album_tag(s['album'])
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

    @dp.channel_post(F.audio)
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

    @dp.message(Command("sync"))
    async def handle_sync_command(message: Message):
        user_id = message.from_user.id
        try:
            await message.delete()
        except Exception:
            pass
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
        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 返回主菜单", callback_data="main_menu")
        await render_hub(bot, message.chat.id, user_id, sync_text, builder.as_markup())

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

    bot_info = await bot.get_me()
    logger.info("=" * 60)
    logger.info(f"🚀 Telegram 单消息全闭环点播机器人 @{bot_info.username} 已上线运行！")
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

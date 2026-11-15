# -*- coding: utf-8 -*-
"""音乐、专辑、歌词及原画影音卡片的统一排版与内联键盘工厂"""

import re
from typing import Dict, List, Optional, Tuple

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from constants import (
    BOOTLEG_AND_FAN_ALBUMS,
    CITIES,
    ERA_MAPPING,
    JAPAN_ALBUMS,
    OFFICIAL_LIVE_ALBUMS,
    SELECTION_AND_TOUR_ALBUMS,
    STUDIO_ALBUMS,
    VIDEO_CAT_ICONS,
    get_album_tag,
)
from hub import db


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


def format_video_size(v: dict) -> str:
    """智能解析视频规格（优先兼容 videos.size_mb，同时兼容 file_size 字节）"""
    if not v:
        return "未知规格"
    size_mb = v.get("size_mb")
    if size_mb is not None:
        try:
            val = float(size_mb)
            if val >= 1024:
                return f"{val / 1024:.2f} GB"
            return f"{val:.1f} MB"
        except (ValueError, TypeError):
            pass
    bytes_size = v.get("file_size")
    if bytes_size:
        return format_size(bytes_size)
    return "未知规格"


def escape_md(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'([_*`\[])', r'\\\1', str(text))


def truncate_title(title: str, limit: int = 26) -> str:
    if len(title) > limit:
        return title[:limit - 2] + ".."
    return title


def home_only_markup() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 返回主菜单", callback_data="main_menu")
    return builder.as_markup()


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
    builder.row(InlineKeyboardButton(text="🔍 智能搜歌搜视频指南 (拼音/歌名/大片)", callback_data="search_guide"))
    builder.row(InlineKeyboardButton(text="🎲 随缘一曲 · 听听逼哥 (随机盲盒)", callback_data="random:track"))
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
    builder.row(InlineKeyboardButton(text="📢 官方音乐频道 @libimusic", url="https://t.me/libimusic"))
    return builder.as_markup()


def get_search_guide_view(bot_username: str) -> Tuple[str, InlineKeyboardMarkup]:
    text = (
        f"🔍 **李志曲库与影音智能检索指南：**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"你无需点击复杂菜单，直接在当前对话框中发送文字即可！\n\n"
        f"📌 **支持的搜索方式：**\n"
        f"1. **歌名全称或关键字**：如 `关于郑州的记忆`、`梵高`、`天空之城`\n"
        f"2. **拼音首字母缩写**：如 `fgxs` (梵高先生)、`zz` (关于郑州的记忆)、`tkzc` (天空之城)\n"
        f"3. **影音视频检索**：如 `跨年`、`洗心革面`、`夜话`、`山东`、`吉隆坡`、`叁叁肆`\n"
        f"4. **城市地标点播**：如 `南京`、`郑州`、`兰州`、`成都`、`北京`\n"
        f"5. **全局行内分享**：在任意聊天框输入 `@{bot_username} 歌名` 实时搜索并卡片发送给好友！"
    )
    return text, home_only_markup()


def get_city_menu_view() -> Tuple[str, InlineKeyboardMarkup]:
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
    return text, builder.as_markup()


def get_era_menu_view() -> Tuple[str, InlineKeyboardMarkup]:
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
    return text, builder.as_markup()


def get_video_archive_view() -> Tuple[str, InlineKeyboardMarkup]:
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
    builder = InlineKeyboardBuilder()
    for cat_name, cnt in db.get_all_video_categories():
        icon = VIDEO_CAT_ICONS.get(cat_name, "🎬")
        builder.row(InlineKeyboardButton(text=f"{icon} {cat_name} ({cnt}部)", callback_data=f"vcat:{cat_name}:0"))
    builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
    return text, builder.as_markup()


def build_albums_markup_by_filter(filter_type: str) -> InlineKeyboardMarkup:
    all_albums = db.get_all_albums()
    filter_sets = {
        "studio": STUDIO_ALBUMS,
        "live": OFFICIAL_LIVE_ALBUMS,
        "japan": JAPAN_ALBUMS,
        "bootleg": BOOTLEG_AND_FAN_ALBUMS,
        "selection": SELECTION_AND_TOUR_ALBUMS,
    }
    target_set = filter_sets.get(filter_type)
    filtered = [a for a in all_albums if a["album"] in target_set] if target_set else all_albums

    builder = InlineKeyboardBuilder()
    for item in filtered:
        album_name = item["album"]
        count = item["track_count"]
        year_str = f"[{item['year']}年] " if item.get("year") else ""
        tag = get_album_tag(album_name)
        tag_str = f" {tag}" if tag else ""
        builder.button(text=f"{year_str}《{album_name}》{tag_str} ({count}首)", callback_data=f"album:{album_name}")

    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
    return builder.as_markup()


def build_song_caption(song: dict, album_name: str, cur_idx: int = 0, total_cnt: int = 0) -> str:
    title = song["title"]
    year_str = f" [{song['year']}年]" if song.get("year") else ""
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
    builder = InlineKeyboardBuilder()
    song = db.get_song_by_id(song_id)
    prev_song, next_song, cur_idx, total_cnt = db.get_album_track_nav(album_name, song_id)

    nav_row = [
        InlineKeyboardButton(text="⏮️ 上一首", callback_data=f"play_inplace:{prev_song['id']}:{album_name}")
        if prev_song else InlineKeyboardButton(text="⏮️ 已是首首", callback_data="noop"),
        InlineKeyboardButton(text=f"🎵 {cur_idx}/{total_cnt}" if total_cnt else "🎵 播放中", callback_data=f"album:{album_name}"),
        InlineKeyboardButton(text="下一首 ⏭️", callback_data=f"play_inplace:{next_song['id']}:{album_name}")
        if next_song else InlineKeyboardButton(text="已是末首 ⏭️", callback_data="noop"),
    ]
    builder.row(*nav_row)

    lyric_btn = (
        InlineKeyboardButton(text="🔼 收起歌词", callback_data=f"lyric_toggle:{song_id}:{album_name}:collapse")
        if lyrics_expanded
        else InlineKeyboardButton(text="📝 展开歌词", callback_data=f"lyric_toggle:{song_id}:{album_name}:expand")
    )
    builder.row(lyric_btn, InlineKeyboardButton(text="📦 连续听整张", callback_data=f"send_all:{album_name}"))

    core_title, other_versions = db.get_other_versions(song_id)
    if other_versions:
        builder.row(InlineKeyboardButton(text=f"🔄 切换其他现场版本 ({len(other_versions)}个)", callback_data=f"versions_menu:{song_id}:{album_name}"))

    if song:
        rel_video = db.get_related_video_for_song(song["title"])
        if rel_video:
            video_link = f"https://t.me/libimusic/{rel_video['message_id']}"
            builder.row(InlineKeyboardButton(text=f"🎬 观看现场高清原画视频: {rel_video['title'][:14]}..", url=video_link))

    builder.row(
        InlineKeyboardButton(text="💿 返回专辑曲目", callback_data=f"album:{album_name}"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )
    return builder.as_markup()


def get_versions_markup(current_song_id: int, album_name: str, versions: List[Dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for v in versions[:16]:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        v_title = truncate_title(v["title"], 26)
        builder.button(text=f"🎵 {year_str}{v_title} - 《{v['album']}》", callback_data=f"play_inplace:{v['id']}:{v['album']}")
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 取消，返回播放控制台", callback_data=f"play_inplace:{current_song_id}:{album_name}"))
    return builder.as_markup()


def build_video_category_markup(category: str, offset: int = 0, page_size: int = 6) -> Tuple[str, InlineKeyboardMarkup]:
    videos, total = db.get_videos_by_category(category, limit=page_size, offset=offset)
    builder = InlineKeyboardBuilder()

    for v in videos:
        year_str = f"[{v['year']}年] " if v.get("year") else ""
        title = truncate_title(v["title"], 28)
        builder.row(InlineKeyboardButton(text=f"🎬 {year_str}{title}", callback_data=f"vdetail:{v['id']}:{category}:{offset}"))

    nav_buttons = []
    current_page = (offset // page_size) + 1
    total_pages = max(1, (total + page_size - 1) // page_size)

    if offset > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ 上一页", callback_data=f"vcat:{category}:{max(0, offset - page_size)}"))
    nav_buttons.append(InlineKeyboardButton(text=f"📄 {current_page}/{total_pages}", callback_data="noop"))
    if offset + page_size < total:
        nav_buttons.append(InlineKeyboardButton(text="下一页 ➡️", callback_data=f"vcat:{category}:{offset + page_size}"))
    builder.row(*nav_buttons)

    builder.row(
        InlineKeyboardButton(text="🔙 返回影音专区", callback_data="menu:video"),
        InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu")
    )

    icon = VIDEO_CAT_ICONS.get(category, "🎬")
    text = (
        f"{icon} **{category}** (共 {total} 部)\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"当前第 {current_page}/{total_pages} 页，点击视频即可进入详情与播放："
    )
    return text, builder.as_markup()


def build_video_detail_card(v: dict, back_cat: Optional[str] = None, back_offset: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    title = v["title"]
    category = v.get("category", "影音视频")
    year_str = f"📅 **演出年份**：{v['year']} 年\n" if v.get("year") else ""
    dur_str = f"⏳ **视频时长**：约 {format_duration(v.get('duration', 0))}\n" if v.get("duration") else ""
    size_str = f"💾 **文件规格**：约 {format_video_size(v)}\n"
    channel_link = f"https://t.me/libimusic/{v['message_id']}"

    text = (
        f"🎬 **《{title}》**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📂 **收录专区**：{category}\n"
        f"{year_str}{dur_str}{size_str}"
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

    back_btn = (
        InlineKeyboardButton(text="🔙 返回列表", callback_data=f"vcat:{back_cat}:{back_offset}")
        if back_cat else InlineKeyboardButton(text="🔙 返回影音专区", callback_data="menu:video")
    )
    builder.row(back_btn, InlineKeyboardButton(text="🏠 返回主菜单", callback_data="main_menu"))
    return text, builder.as_markup()

# -*- coding: utf-8 -*-
"""
生成李志全专辑封面拼接海报 (Collage Banner)
用于 Telegram 机器人的首次欢迎界面 (/start)
用户选定版：11 列 x 3 行 全画幅超宽海报 (33 张专辑全平铺编年史)
"""
import os
import sys
import sqlite3
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_DIR = Path("D:/AI/电报机器人")
DB_PATH = PROJECT_DIR / "music.db"
THUMB_DIR = PROJECT_DIR / ".temp_audio" / "thumbnails"
Z_BASE_DIR = Path("Z:/音乐/李志")
OUTPUT_DIR = PROJECT_DIR / "bot" / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_BANNER_PATH = OUTPUT_DIR / "welcome_banner.jpg"
ARTIFACTS_DIR = Path("C:/Users/LIBI/.gemini/antigravity/brain/e23e1907-8532-4f3d-8307-10830338f0e3")

def get_font(size: int, bold: bool = False):
    """获取可用中文字体"""
    font_names = [
        "msyhbd.ttc" if bold else "msyh.ttc",   # 微软雅黑
        "simhei.ttf",                           # 黑体
        "simsun.ttc",                           # 宋体
        "arial.ttf"                             # 备用
    ]
    windir = os.environ.get("WINDIR", "C:\\Windows")
    for name in font_names:
        p = Path(windir) / "Fonts" / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()

def collect_album_covers():
    """从数据库和磁盘精确匹配 33 张专辑的封面路径"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT album, year FROM songs ORDER BY year ASC, album ASC")
    db_albums = c.fetchall()
    conn.close()

    manual_maps = {
        "被禁忌的游戏": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2004 - 被禁忌的游戏/Cover.jpg",
        "梵高先生": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2005 - 梵高先生/Cover.jpg",
        "这个世界会好吗": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2006 - 这个世界会好吗/Cover.jpg",
        "工体东路没有人": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2009 - 工体东路没有人/Cover.jpg",
        "我爱南京": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2009 - 我爱南京/Cover.jpg",
        "义乌隔壁酒吧": Z_BASE_DIR / "04. 巡演与跨年专场录音 (Bootleg & Tours)/2009 - 动物凶猛巡演第35站 (义乌隔壁酒吧跨年)/Cove.jpg",
        "二零零九年十月十六日事件": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2010 - 二零零九年十月十六日事件/Cover.jpg",
        "你好，郑州": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2010 - 你好，郑州/Cover.jpg",
        "杂选": PROJECT_DIR / ".temp_audio/zaxuan_cover.jpg",
        "F": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2011 - F/Cover.jpg",
        "我们也爱南京": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2011 - 我们也爱南京/Cover.jpg",
        "杭州酒球会一身酒气": Z_BASE_DIR / "04. 巡演与跨年专场录音 (Bootleg & Tours)/2011 - 杭州酒球会一身酒气专场/Cover.jpg",
        "Imagine Live": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2012 - IMAGINE/Cover.jpg",
        "“挺”不插电巡演 郑州站": Z_BASE_DIR / "04. 巡演与跨年专场录音 (Bootleg & Tours)/2012 - “挺”不插电全国巡演 (郑州站)/Cover.jpg",
        "108个关键词": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2013 - 108个关键词/Cover.jpg",
        "李志 1701": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2014 - 1701/Cover.jpg",
        "勾三搭四": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2014 - 勾三搭四/Cover.jpg",
        "I/O": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2015 - i_O/s27992073.jpg",
        "动静 (2015 Live)": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2016 - 动静/Cover.jpg",
        "李志LIVE精选": Z_BASE_DIR / "05. 乐迷合辑与未发行版本 (Compilations & Demos)/李志LIVE精选 (历年巡演高光合辑)/Cover.jpg",
        "看见 (李志2015巡回演唱会)": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2015 - 看见 (巡回演唱会北京站)/Cover.jpg",
        "金城兰州": Z_BASE_DIR / "04. 巡演与跨年专场录音 (Bootleg & Tours)/单曲 - 金城兰州 (现场翻唱)/Cover.jpg",
        "8": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2016 - 8/Cover.jpg",
        "在每一条伤心的应天大街上": Z_BASE_DIR / "01. 录音室专辑 (Studio Albums)/2016 - 在每一条伤心的应天大街上/Cover.jpg",
        "李志北京不插电现场 2016 Live": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2016 - 李志北京不插电现场/Cover.jpg",
        "李志、电声与管弦乐": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2017 - 李志、电声与管弦乐/Cover.jpg",
        "李志、电声与管弦乐II": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2018 - 李志、电声与管弦乐Ⅱ/s29771069.jpg",
        "爵士乐与不插电新编12首": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2018 - 爵士乐与不插电新编12首/Cover.jpg",
        "洗心革面 跨年音乐会": Z_BASE_DIR / "04. 巡演与跨年专场录音 (Bootleg & Tours)/2018 - “洗心革面”跨年音乐会/Cover.jpg",
        "Best Selection Songs 2004-2019 (Vol.1)": THUMB_DIR / "Best Selection Songs 2004-2019 (Vol.1).jpg",
        "Best Selection Songs 2004-2018 (Vol.2)": PROJECT_DIR / ".temp_audio/vol2_embedded.jpg",
        "Best Selection Songs 2004-2018 (Vol.3)": Z_BASE_DIR / "03. 官方海外精选辑 (Best Selection - 日本限定)/2021 - Best Selection Songs 2004-2018 (Vol.3) 倒影/cover.jpg",
        "叁缺壹 (2024 Tokyo Live)": Z_BASE_DIR / "02. 官方现场专辑 (Live Albums)/2024 - THREE MISSING ONE (叁缺壹) JAPAN Tour 2024 in Tokyo/cover.jpg"
    }

    covers_list = []
    for album, year in db_albums:
        cover_path = manual_maps.get(album)
        if not cover_path or not Path(cover_path).exists():
            for f in THUMB_DIR.iterdir():
                if album in f.name:
                    cover_path = f
                    break

        if cover_path and Path(cover_path).exists():
            covers_list.append({
                "album": album,
                "year": year,
                "path": Path(cover_path)
            })

    return covers_list

def generate_layout_11x3(covers):
    """
    用户青睐的 11 列 x 3 行 全画幅超宽海报 (33 张封面平铺排列，0 占位符)
    """
    tile_size = 280
    cols, rows = 11, 3
    gap = 6
    pad_x = 24
    pad_top = 105
    pad_bottom = 60

    total_width = pad_x * 2 + cols * tile_size + (cols - 1) * gap
    total_height = pad_top + rows * tile_size + (rows - 1) * gap + pad_bottom

    canvas = Image.new("RGB", (total_width, total_height), (13, 15, 19))
    draw = ImageDraw.Draw(canvas)

    # 顶部标题栏（纯文本防方块乱码，温暖金黄色）
    font_main = get_font(40, bold=True)
    font_sub = get_font(21, bold=False)

    title_text = "李志音乐全专辑编年典藏 · 33 ALBUMS COLLECTION (2004 — 2024)"
    sub_text = "33 张官方录音室与现场唱片收录 · 李志音乐点播站 @libimusic"

    draw.text((total_width // 2, 40), title_text, fill=(245, 198, 68), font=font_main, anchor="mm")
    draw.text((total_width // 2, 80), sub_text, fill=(185, 200, 220), font=font_sub, anchor="mm")

    border_color = (35, 40, 50)
    for idx, item in enumerate(covers):
        r = idx // cols
        c = idx % cols
        x = pad_x + c * (tile_size + gap)
        y = pad_top + r * (tile_size + gap)

        try:
            with Image.open(item["path"]) as im:
                im_rgb = im.convert("RGB")
                im_resized = im_rgb.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                canvas.paste(im_resized, (x, y))

                # 1px 细微画框，增加黑胶/CD实体装帧质感
                draw.rectangle([x, y, x + tile_size - 1, y + tile_size - 1], outline=border_color, width=1)
        except Exception as e:
            print(f"Error loading {item['path']}: {e}")

    # 底部说明题字
    f_footer = get_font(19, bold=False)
    footer_text = "「这个世界会好吗」· 400+ 首无损高保真曲库 · 点播机器人 [@libi_music_bot] · 音乐分享频道 [@libimusic]"
    draw.text((total_width // 2, total_height - 30), footer_text, fill=(130, 142, 158), font=f_footer, anchor="mm")

    return canvas

if __name__ == "__main__":
    covers = collect_album_covers()
    print(f"共加载 {len(covers)} 张封面，开始生成 11x3 欢迎横幅海报...")

    banner = generate_layout_11x3(covers)

    # 保存到 bot 资源目录 (bot/assets/welcome_banner.jpg)
    banner.save(OUTPUT_BANNER_PATH, "JPEG", quality=90, optimize=True)
    print(f"✔ 机器人封面已保存到: {OUTPUT_BANNER_PATH} ({os.path.getsize(OUTPUT_BANNER_PATH)} bytes)")

    # 同时复制一份到 artifacts 供预览
    artifact_path = ARTIFACTS_DIR / "welcome_banner_final_11x3.jpg"
    banner.save(artifact_path, "JPEG", quality=90, optimize=True)
    print(f"✔ 预览文件已保存到: {artifact_path}")

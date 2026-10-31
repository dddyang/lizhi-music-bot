import os
import sys
import json
import sqlite3
import shutil
import re

sys.path.append(r"D:\AI\电报机器人\bot")
from lyrics_bank import LYRICS_DATABASE
from mood_quotes import get_song_exact_quote, clean_song_title

sys.stdout.reconfigure(encoding='utf-8')

STUDIO_ALBUMS = {
    "被禁忌的游戏", "梵高先生", "这个世界会好吗", "我爱南京",
    "你好，郑州", "F", "李志 1701", "8",
    "在每一条伤心的应天大街上"
}

JAPAN_ALBUMS = {
    "Best Selection Songs 2004-2019 (Vol.1)",
    "Best Selection Songs 2004-2018 (Vol.2)",
    "Best Selection Songs 2004-2018 (Vol.3)",
    "叁缺壹 (2024 Tokyo Live)",
    "2025 叁缺壹 吉隆坡现场全场实况",
    "2025 叁缺壹 吉隆坡站"
}

CITIES = ["南京", "郑州", "兰州", "杭州", "北京", "成都", "定西"]

PROJECT_DIR = r"D:\AI\电报机器人"
DB_PATH = os.path.join(PROJECT_DIR, "music.db")
THUMB_DIR = os.path.join(PROJECT_DIR, ".temp_audio", "thumbnails")
WEBAPP_DIR = os.path.join(PROJECT_DIR, "webapp")
COVERS_DIR = os.path.join(WEBAPP_DIR, "covers")

os.makedirs(COVERS_DIR, exist_ok=True)

banner_src = os.path.join(PROJECT_DIR, "bot", "assets", "welcome_banner.jpg")
if os.path.exists(banner_src):
    shutil.copy2(banner_src, os.path.join(COVERS_DIR, "default_banner.jpg"))

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

album_cover_map = {}
for fname in os.listdir(THUMB_DIR):
    if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
        stem = os.path.splitext(fname)[0]
        clean_stem = re.sub(r"[《》【】\s_]+", "", stem).lower()
        album_cover_map[clean_stem] = fname

def find_cover_for_album(album_name):
    clean_alb = re.sub(r"[《》【】\s_]+", "", album_name).lower()
    for k, fname in album_cover_map.items():
        if k == clean_alb or k in clean_alb or clean_alb in k:
            src = os.path.join(THUMB_DIR, fname)
            safe_name = f"cov_{abs(hash(album_name)) % 100000}.jpg"
            dst = os.path.join(COVERS_DIR, safe_name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
            return f"covers/{safe_name}"
    return "covers/default_banner.jpg"

cursor.execute("SELECT * FROM songs ORDER BY year ASC, album ASC, id ASC")
all_songs = [dict(r) for r in cursor.fetchall()]

tracks_data = []

for s in all_songs:
    album = s["album"]
    title = s["title"]
    clean_t = clean_song_title(title)
    lyrics = s.get("lyrics") or LYRICS_DATABASE.get(clean_t) or ""
    quote = get_song_exact_quote(title, lyrics)
    cover_rel = find_cover_for_album(album)
    
    # 类别判定
    cat = "live"
    if album in STUDIO_ALBUMS:
        cat = "studio"
    elif album in JAPAN_ALBUMS:
        cat = "japan"
    elif any(kw in album for kw in ["民间", "酒球会", "不插电", "合辑", "精选", "杂选", "兰州"]):
        cat = "bootleg"
        
    city_tag = None
    for c in CITIES:
        if c in title or c in album:
            city_tag = c
            break

    year = s.get("year") or 2004
    era_tag = "era_04_09"
    if year >= 2019:
        era_tag = "era_19_25"
    elif year >= 2016:
        era_tag = "era_16_18"
    elif year >= 2010:
        era_tag = "era_10_15"

    channel_url = f"https://t.me/libimusic/{s['message_id']}" if s.get("message_id") else "https://t.me/libimusic"
    
    tracks_data.append({
        "id": s["id"],
        "title": title,
        "clean_title": clean_t,
        "album": album,
        "year": year,
        "duration": s["duration"],
        "quote": quote,
        "lyrics": lyrics.strip() if lyrics else "",
        "cover": cover_rel,
        "category": cat,
        "city": city_tag,
        "era": era_tag,
        "channel_url": channel_url,
        "msg_id": s.get("message_id")
    })

js_content = f"""// 李志编年史全系曲库数据源 (含机器人分类标签)
window.LIZHI_DATA = {json.dumps(tracks_data, ensure_ascii=False, indent=2)};
"""

data_js_path = os.path.join(WEBAPP_DIR, "data.js")
with open(data_js_path, "w", encoding="utf-8") as f:
    f.write(js_content)

print(f"✅ WebApp 数据已重新生成，已注入机器人分类标签 (曲目数: {len(tracks_data)})")

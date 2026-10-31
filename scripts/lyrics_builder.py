# -*- coding: utf-8 -*-
"""
lyrics_builder.py
根据真实歌词 json 生成 lyrics_bank.py 并反哺更新 music.db
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

JSON_PATH = Path(r"D:\AI\电报机器人\lyrics_bank_real.json")
DB_PATH = Path(r"D:\AI\电报机器人\music.db")
OUTPUT_BANK_PATH = Path(r"D:\AI\电报机器人\lyrics_bank.py")

def normalize_title(title: str) -> str:
    if not title:
        return ""
    # 去除开头的序号如 01. 02- 等
    t = re.sub(r'^\d{1,3}[\.\s\-_]+', '', title)
    # 去除括号及说明
    t = re.sub(r'[（\(【\[].*?[）\)】\]]', '', t)
    # 去除特殊标点与空格
    t = re.sub(r'[\s\-_，。！？、~]+', '', t)
    # 繁简或特殊字符统一
    t = t.replace('曖昧', '暧昧')
    return t.strip()

def build_lyrics_bank_py(lyrics_dict):
    code = ['# -*- coding: utf-8 -*-']
    code.append('"""')
    code.append('李志经典曲目完整歌词库（100% 官方原版真实词作，杜绝 AI 虚构）')
    code.append('"""')
    code.append('')
    code.append('import re')
    code.append('from typing import Optional')
    code.append('')
    code.append('LYRICS_DATABASE = {')
    
    for key, text in sorted(lyrics_dict.items()):
        # Escape triple quotes if any
        safe_text = text.replace('"""', r'\"\"\"')
        safe_key = json.dumps(key, ensure_ascii=False)
        code.append(f'    {safe_key}: """{safe_text}""",\n')
        
    code.append('}')
    code.append('')
    code.append('''
def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = re.sub(r"^\\d{1,3}[\\.\\s\\-_]+", "", title)
    t = re.sub(r"[（\\(【\\[].*?[）\\)】\\]]", "", t)
    t = re.sub(r"[\\s\\-_，。！？、~]+", "", t)
    t = t.replace("曖昧", "暧昧")
    return t.strip()

def get_lyrics(title: str) -> Optional[str]:
    """根据歌名模糊匹配真实歌词"""
    if not title:
        return None

    clean_t = normalize_title(title)

    # 1. 精确或规范化匹配
    if title in LYRICS_DATABASE:
        return LYRICS_DATABASE[title]
    if clean_t in LYRICS_DATABASE:
        return LYRICS_DATABASE[clean_t]

    # 2. 联唱歌曲拆分匹配 (例如 "关于郑州的记忆+董卓谣+春末南方的城市")
    parts = re.split(r"[\\+&/]", clean_t)
    if len(parts) > 1:
        matched_sections = []
        for part in parts:
            part = normalize_title(part)
            if not part:
                continue
            for k, v in LYRICS_DATABASE.items():
                if k == part or (len(k) >= 2 and (k in part or part in k)):
                    matched_sections.append(f"🎵 **《{k}》**\\n{v}")
                    break
        if matched_sections:
            return "\\n\\n━━━━━━━━━━━━━━━━━━━━━\\n\\n".join(matched_sections)

    # 3. 包含匹配 (防止单字误匹配，只对长度>=2的关键词进行匹配)
    for k, v in LYRICS_DATABASE.items():
        if len(k) >= 2 and (k == clean_t or k in clean_t or clean_t in k):
            return v

    return None
''')

    with open(OUTPUT_BANK_PATH, "w", encoding="utf-8") as f:
        f.write('\n'.join(code))
    print(f"✅ 已成功生成 lyrics_bank.py (包含 {len(lyrics_dict)} 条独立曲目真实歌词)")

def update_database(lyrics_dict):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT id, title, album FROM songs")
    rows = cur.fetchall()
    
    updated_count = 0
    not_matched = []
    
    for song_id, raw_title, album in rows:
        clean_t = normalize_title(raw_title)
        
        # 匹配歌词
        matched_lyrics = None
        if raw_title in lyrics_dict:
            matched_lyrics = lyrics_dict[raw_title]
        elif clean_t in lyrics_dict:
            matched_lyrics = lyrics_dict[clean_t]
        else:
            for k, v in lyrics_dict.items():
                if len(k) >= 2 and (k == clean_t or k in clean_t or clean_t in k):
                    matched_lyrics = v
                    break
        
        if matched_lyrics:
            cur.execute("UPDATE songs SET lyrics = ? WHERE id = ?", (matched_lyrics, song_id))
            updated_count += 1
        else:
            not_matched.append((song_id, raw_title, album))
            
    conn.commit()
    conn.close()
    
    print(f"✅ 数据库更新完成：总歌曲数 {len(rows)}，成功录入真实歌词 {updated_count} 首！")
    print(f"ℹ️ 未匹配到歌词或为纯乐曲/开场白的歌曲数：{len(not_matched)}")

def main():
    if not JSON_PATH.exists():
        print(f"错误：歌词文件 {JSON_PATH} 尚未生成，请等待抓取完成。")
        return
        
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
        
    print(f"读取到抓取歌词 {len(raw_data)} 项，开始清洗并构建...")
    
    # 建立标准化词库
    clean_dict = {}
    for k, v in raw_data.items():
        norm_k = normalize_title(k)
        if norm_k and v and len(v.strip()) > 20:
            clean_dict[norm_k] = v.strip()
            
    build_lyrics_bank_py(clean_dict)
    update_database(clean_dict)

if __name__ == "__main__":
    main()

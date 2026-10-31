import urllib.request
import re
import sys
import json
import time
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

ALBUM_URLS = [
    '/album/310145/bei-jin-ji-de-you-xi',
    '/album/310148/fan-gao-xian-sheng',
    '/album/311196/zhe-ge-shi-jie-hui-hao-ma',
    '/album/310143/wo-ai-nan-jing',
    '/album/278812/ni-hao-zheng-zhou',
    '/album/310147/F',
    '/album/457050/1701',
    '/album/573149/zai-mei-yi-tiao-shang-xin-de-ying-tian-da-jie-shang',
    '/album/574630/8',
    '/album/310146/gong-ti-dong-lu-mei-you-ren',
    '/album/407901/gou-san-da-si-2013-Live',
    '/album/471132/i-O-2014-Live',
    '/album/465213/108-ge-guan-jian-ci-2012-Live',
    '/album/574168/dong-jing-2015Live',
    '/album/573931/li-zhi-dian-sheng-yu-guan-xian-yue',
    '/album/577925/li-zhi-dian-sheng-yu-guan-xian-yue-II',
    '/album/573678/jue-shi-yue-yu-bu-cha-dian-xin-bian-12-shou',
    '/album/573750/li-zhi-bei-jing-bu-cha-dian-xian-chang-2016-5-29',
    '/album/649821/jin-cheng-lan-zhou',
    '/album/467300/zai-gu-dai',
    '/album/486060/kan-jian',
    '/album/487258/zhe-ge-shi-jie-hui-hao-ma-2015',
    '/album/18220/hui-se-ren-zhong'
]

def clean_song_title(title: str) -> str:
    t = re.sub(r'[\(\[（【].*?[\)\]）】]', '', title)
    t = re.sub(r'[\s\-_]+', '', t)
    return t.strip()

def clean_lyrics_text(lines):
    cleaned = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        # Skip URLs or amp links
        if '//' in l or 'http' in l:
            continue
        # Skip purely pinyin lines (Latin letters + spaces)
        if re.match(r'^[a-zA-Z\s,\.\'\-\?!]+$', l) and len(l) > 10:
            # check if it's English lyrics like Hey Jude or pinyin
            if not any(eng_word in l.lower() for eng_word in ['hey', 'jude', 'dont', 'make', 'better', 'take', 'sad']):
                continue
        # Skip tech credit tags
        if any(l.startswith(k) for k in ['作词', '作曲', '编曲', '演唱', '吉他', '贝斯', '鼓手', '制作人', '录音', '混音', '母带', '键盘', '和声', '萨克斯']):
            continue
        cleaned.append(l)
    return '\n'.join(cleaned)

def get_lyrics_from_page(song_url):
    full_url = "https://zh.followlyrics.com" + song_url
    req = urllib.request.Request(full_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    
    matches = re.findall(r'<td>\[\d{2}:\d{2}(?:\.\d+)?\]</td>\s*<td>(.*?)</td>', html)
    if matches:
        raw_lines = [m.strip() for m in matches if m.strip()]
        res = clean_lyrics_text(raw_lines)
        if len(res) > 20:
            return res
    
    # Meta fallback
    meta = re.search(r'<meta\s+name="description"\s+content="[^:]+:\s*(.*?)"', html)
    if meta:
        text = meta.group(1).strip()
        # split by space into lines
        words = text.split()
        if len(words) > 5:
            return '\n'.join(words)
    return None

def main():
    all_songs = {}
    print(f"开始抓取 {len(ALBUM_URLS)} 个专辑的歌词...")

    for a_idx, a_url in enumerate(ALBUM_URLS, 1):
        print(f"\n[{a_idx}/{len(ALBUM_URLS)}] 正在扫描专辑: {a_url}")
        full_a_url = "https://zh.followlyrics.com" + a_url
        try:
            req = urllib.request.Request(full_a_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            
            songs = re.findall(r'href="(/lyrics/\d+/[^"]+)"[^>]*>(.*?)</a>', html)
            seen_in_album = set()
            for s_link, s_name in songs:
                clean_name = re.sub(r'<[^>]+>', '', s_name).strip()
                if not clean_name or s_link in seen_in_album:
                    continue
                seen_in_album.add(s_link)
                
                norm_name = clean_song_title(clean_name)
                # If we already have lyrics for this normalized name, skip or keep
                if norm_name in all_songs and len(all_songs[norm_name]) > 50:
                    continue
                
                try:
                    lyrics = get_lyrics_from_page(s_link)
                    if lyrics and len(lyrics) > 30:
                        all_songs[norm_name] = lyrics
                        all_songs[clean_name] = lyrics
                        print(f"  ✅ 成功获取: {clean_name} ({norm_name}) - {len(lyrics.splitlines())} 行")
                    else:
                        print(f"  ⚠️ 无歌词: {clean_name}")
                except Exception as e:
                    print(f"  ❌ 抓取失败: {clean_name}, {e}")
                time.sleep(0.15)
        except Exception as e:
            print(f"扫描专辑失败: {a_url}, {e}")
        time.sleep(0.3)

    print(f"\n🎉 歌词抓取完成！共收集 {len(all_songs)} 首歌曲真实歌词！")
    output_file = Path(r"D:\AI\电报机器人\lyrics_bank_real.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_songs, f, ensure_ascii=False, indent=2)
    print(f"已保存到: {output_file}")

if __name__ == "__main__":
    main()

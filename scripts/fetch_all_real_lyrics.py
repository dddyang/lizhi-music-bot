import urllib.request
import re
import urllib.parse
import json
import time

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def get_html(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode('utf-8', errors='ignore')

def clean_lrc(lrc_text: str) -> str:
    lines = []
    for line in lrc_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip metadata tags like [ti:], [ar:], [al:], [by:], [offset:]
        if re.match(r'^\[(ti|ar|al|by|offset|length):', line, re.I):
            continue
        # Remove timestamps like [01:23.45] or [01:23]
        clean_line = re.sub(r'\[\d{2}:\d{2}(?:\.\d+)?\]', '', line).strip()
        if clean_line:
            lines.append(clean_line)
    return '\n'.join(lines)

def main():
    repo_url = 'https://github.com/nanjinglizhi/songs_album'
    html = get_html(repo_url)
    
    # 查找所有相册目录
    folder_matches = re.findall(r'href=["\']/nanjinglizhi/songs_album/tree/master/([^"\']+)["\']', html)
    unique_folders = sorted(set(folder_matches))
    print(f"找到 {len(unique_folders)} 个专辑目录")

    all_lyrics = {}

    for folder_enc in unique_folders:
        folder_name = urllib.parse.unquote(folder_enc)
        print(f"正在扫描专辑: {folder_name}...")
        sub_url = f"https://github.com/nanjinglizhi/songs_album/tree/master/{folder_enc}"
        try:
            sub_html = get_html(sub_url)
            # 查找所有 .lrc 文件链接
            lrc_matches = re.findall(r'href=["\']/nanjinglizhi/songs_album/blob/master/' + re.escape(folder_enc) + r'/([^"\']+\.lrc)["\']', sub_html)
            lrc_set = sorted(set(lrc_matches))
            print(f"  -> 找到 {len(lrc_set)} 个歌词文件")

            for lrc_enc in lrc_set:
                lrc_name = urllib.parse.unquote(lrc_enc)
                # 歌名提取（去掉数字序号如 '01 ' 或 '01. ' 和后缀 '.lrc'）
                song_title = lrc_name[:-4].strip()
                song_title = re.sub(r'^\d+[\.\s\-_]+', '', song_title).strip()
                
                # 从 jsdelivr 高速下载歌词内容
                cdn_url = f"https://fastly.jsdelivr.net/gh/nanjinglizhi/songs_album@master/{folder_enc}/{lrc_enc}"
                try:
                    req_lrc = urllib.request.Request(cdn_url, headers=HEADERS)
                    with urllib.request.urlopen(req_lrc, timeout=10) as resp:
                        raw_lrc = resp.read().decode('utf-8', errors='ignore')
                        cleaned = clean_lrc(raw_lrc)
                        if cleaned and len(cleaned) > 10:
                            all_lyrics[song_title] = cleaned
                            print(f"    ✅ 已收录: {song_title}")
                except Exception as e:
                    print(f"    ❌ 下载失败 {lrc_name}: {e}")
                time.sleep(0.1)
        except Exception as e:
            print(f"扫描目录失败 {folder_name}: {e}")
        time.sleep(0.5)

    print(f"\n🎉 采集完成！共收录 {len(all_lyrics)} 首真实正版歌词！")
    with open('/tmp/real_lizhi_lyrics.json', 'w', encoding='utf-8') as f:
        json.dump(all_lyrics, f, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    main()

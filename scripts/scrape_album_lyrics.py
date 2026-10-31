import urllib.request, re, sys, time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def get_album_songs(album_url):
    full_url = "https://zh.followlyrics.com" + album_url
    req = urllib.request.Request(full_url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    
    songs = re.findall(r'href="(/lyrics/\d+/[^"]+)"[^>]*>(.*?)</a>', html)
    result = []
    seen = set()
    for l, n in songs:
        clean_n = re.sub(r'<[^>]+>', '', n).strip()
        if clean_n and l not in seen:
            seen.add(l)
            result.append((clean_n, l))
    return result

def get_song_lyrics(song_url):
    full_url = "https://zh.followlyrics.com" + song_url
    req = urllib.request.Request(full_url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
    
    # Extract table rows: <td>[00:12.340]</td><td>text</td>
    lines = []
    matches = re.findall(r'<td>\[\d{2}:\d{2}(?:\.\d+)?\]</td>\s*<td>(.*?)</td>', html)
    if matches:
        for m in matches:
            t = m.strip()
            # filter out music tags
            if t and not any(k in t for k in ['作词', '作曲', '编曲', '演唱', '吉他', '贝斯', '鼓手', '制作人', '录音', '混音', '母带']):
                lines.append(t)
            elif t and len(lines) == 0:
                # keep credits at top if wanted, or skip
                pass
        return '\n'.join(lines)
    
    # Fallback to meta description
    meta = re.search(r'<meta\s+name="description"\s+content="[^:]+:\s*(.*?)"', html)
    if meta:
        return meta.group(1).strip()
    return None

# Test with 被禁忌的游戏
songs = get_album_songs('/album/310145/bei-jin-ji-de-you-xi')
print(f"《被禁忌的游戏》共 {len(songs)} 首歌:")
for name, link in songs:
    print(f"\n--- {name} ---")
    lyr = get_song_lyrics(link)
    if lyr:
        print(lyr[:200] + "...")
    else:
        print("无歌词")
    time.sleep(0.2)

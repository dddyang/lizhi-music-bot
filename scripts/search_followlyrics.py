import urllib.request, re, sys, urllib.parse

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

url = "https://zh.followlyrics.com/search?q=" + urllib.parse.quote("李志")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
        # Find song links
        song_links = re.findall(r'href="(/lyrics/\d+/[^"]+)"[^>]*>(.*?)</a>', html)
        print(f"搜索到 {len(song_links)} 首歌曲:")
        for link, name in song_links[:30]:
            print(f"  {name.strip()} -> {link}")
except Exception as e:
    print("Err:", e)

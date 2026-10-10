import urllib.request, re, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

url = "https://zh.followlyrics.com/artist/7654/li-zhi"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=10) as resp:
    html = resp.read().decode("utf-8", errors="ignore")

albums = re.findall(r'href="(/album/\d+/[^"]+)"[^>]*>(.*?)</a>', html)
print(f"Albums found: {len(albums)}")
unique_albums = {}
for l, n in albums:
    name_clean = re.sub(r'<[^>]+>', '', n).strip()
    if name_clean and l not in unique_albums:
        unique_albums[l] = name_clean
        print(f"  {name_clean} -> {l}")

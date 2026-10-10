import urllib.request, re, urllib.parse

req = urllib.request.Request('https://github.com/nanjinglizhi/songs_album', headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode('utf-8', errors='ignore')
        matches = re.findall(r'href=["\']/nanjinglizhi/songs_album/tree/master/([^"\']+)["\']', html)
        print('Found album folders:', len(matches))
        for m in sorted(set(matches)):
            print(urllib.parse.unquote(m))
except Exception as e:
    print('Err:', e)

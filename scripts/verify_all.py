import sys
sys.stdout.reconfigure(encoding='utf-8')
from database import MusicDatabase

db = MusicDatabase('music.db')
stats = db.get_stats()
print(f"📊 数据库统计: {stats['songs']} 首歌曲, {stats['albums']} 张专辑")

print("\n🔍 抽检各经典专辑真实曲目数:")
test_albums = [
    '被禁忌的游戏', '梵高先生', '这个世界会好吗', '我爱南京',
    '你好，郑州', '8', 'F', '李志 1701', '洗心革面 跨年音乐会',
    '叁缺壹 (2024 Tokyo Live)'
]
for alb in test_albums:
    songs = db.get_songs_by_album(alb)
    titles = [s['title'] for s in songs[:4]]
    print(f"  • 《{alb}》: 共 {len(songs)} 首歌 | 前排代表曲目: {titles}...")

print("\n🔎 模糊与拼音检索测试:")
for q in ['郑州', '黑色信封', 'fgxs', 'bb']:
    res = db.search_songs(q)
    samples = [f"{r['title']} 《{r['album']}》" for r in res[:2]]
    print(f"  • 搜索 '{q}': 命中 {len(res)} 首 | 示例: {samples}")

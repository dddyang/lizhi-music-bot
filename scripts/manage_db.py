"""
音乐曲库管理与调试工具 (CLI)
用法:
  python manage_db.py stats               # 查看曲库统计
  python manage_db.py albums              # 查看所有专辑及歌曲数
  python manage_db.py album "被禁忌的游戏" # 查看某专辑的歌曲
  python manage_db.py search "郑州"       # 测试搜索
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import DB_PATH
from database import MusicDatabase

db = MusicDatabase(DB_PATH)


def format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def show_stats():
    stats = db.get_stats()
    print("\n📊 === 曲库统计 ===")
    print(f"🎵 总收录歌曲: {stats['songs']} 首")
    print(f"💿 总收录专辑: {stats['albums']} 张")
    print("===================\n")


def show_albums():
    albums = db.get_all_albums()
    if not albums:
        print("暂无收录的专辑。")
        return
    print(f"\n💿 === 全部专辑列表 ({len(albums)}张) ===")
    for idx, item in enumerate(albums, 1):
        print(f"{idx:02d}. 《{item['album']}》 - 共 {item['track_count']} 首歌 (总时长 {format_duration(item['total_duration'] or 0)})")
    print("==================================\n")


def show_album_tracks(album_name: str):
    tracks = db.get_songs_by_album(album_name)
    if not tracks:
        print(f"未找到专辑《{album_name}》下的曲目。")
        return
    print(f"\n🎵 === 专辑《{album_name}》曲目 ({len(tracks)}首) ===")
    for idx, t in enumerate(tracks, 1):
        print(f" {idx:02d}. {t['title']} | 时长: {format_duration(t['duration'])} | 频道MsgID: {t['message_id']}")
    print("============================================\n")


def do_search(keyword: str):
    results = db.search_songs(keyword)
    if not results:
        print(f"未找到包含「{keyword}」的歌曲。")
        return
    print(f"\n🔍 === 搜索「{keyword}」结果 ({len(results)}条) ===")
    for idx, r in enumerate(results, 1):
        print(f" {idx:02d}. [{r['album']}] {r['title']} ({format_duration(r['duration'])}) -> ID:{r['id']}, MsgID:{r['message_id']}")
    print("======================================\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd == "stats":
        show_stats()
    elif cmd == "albums":
        show_albums()
    elif cmd == "album":
        if len(sys.argv) < 3:
            print("请提供专辑名称，例如: python manage_db.py album \"梵高先生\"")
        else:
            show_album_tracks(sys.argv[2])
    elif cmd == "search":
        if len(sys.argv) < 3:
            print("请提供搜索关键词，例如: python manage_db.py search \"郑州\"")
        else:
            do_search(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)

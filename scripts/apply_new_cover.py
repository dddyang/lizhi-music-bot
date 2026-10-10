import shutil
import sys
from pathlib import Path
from mutagen.id3 import ID3, APIC

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

src_cover = Path(r"D:\AI\电报机器人\Cover_wmyanj_final.jpg")
album_dir = Path(r"Z:\音乐\李志\我们也爱南京")
target_cover = album_dir / "Cover.jpg"

# 1. 替换本地 Cover.jpg
shutil.copy2(src_cover, target_cover)
# 删除过期的 cover.png
old_png = album_dir / "cover.png"
if old_png.exists():
    old_png.unlink()
print(f"已更新 {target_cover}")

# 2. 将新封面注入 9 首 MP3 文件的 ID3 APIC 标签
cover_data = target_cover.read_bytes()

for mp3 in sorted(album_dir.glob("*.mp3")):
    id3 = ID3(mp3)
    # Remove existing APIC
    id3.delall("APIC")
    id3.add(APIC(
        encoding=3,
        mime='image/jpeg',
        type=3,
        desc='Cover',
        data=cover_data
    ))
    id3.save()
    print(f"✅ 已成功更新内嵌封面: {mp3.name}")

print("\n全套 9 首 MP3 封面已全部无缝替换完毕！")

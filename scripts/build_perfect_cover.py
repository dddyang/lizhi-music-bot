from PIL import Image, ImageDraw, ImageFont

# Load the generated image with the stunning neon sign
im = Image.open(r'C:\Users\LIBI\.gemini\antigravity\brain\e23e1907-8532-4f3d-8307-10830338f0e3\wmyanj_cover_1791214582290.jpg')

# Find where the white section starts (around y=675)
# Let's inspect rows to find the exact boundary
width, height = im.size
split_y = 665

# Create a clean white canvas for the bottom section
draw = ImageDraw.Draw(im)
draw.rectangle([0, split_y, width, height], fill=(255, 255, 255))

# Load fonts
font_path_song = r"C:\Windows\Fonts\simsun.ttc"
font_path_kai = r"C:\Windows\Fonts\simkai.ttf"
font_path_yahei = r"C:\Windows\Fonts\msyh.ttc"

try:
    font_city = ImageFont.truetype(font_path_song, 42)
    font_names = ImageFont.truetype(font_path_song, 22)
    font_date = ImageFont.truetype(font_path_song, 16)
except Exception:
    font_city = ImageFont.load_default()
    font_names = ImageFont.load_default()
    font_date = ImageFont.load_default()

# 1. "南 京" centered
city_text = "南    京"
bbox_city = draw.textbbox((0, 0), city_text, font=font_city)
w_city = bbox_city[2] - bbox_city[0]
draw.text(((width - w_city) / 2, split_y + 45), city_text, fill=(30, 30, 30), font=font_city)

# 2. Artist names
line1 = "李志   欢庆   小河   周云蓬   马条"
line2 = "吴吞   万晓利   郭龙   张玮玮   苏阳"

bbox1 = draw.textbbox((0, 0), line1, font=font_names)
w1 = bbox1[2] - bbox1[0]
draw.text(((width - w1) / 2, split_y + 130), line1, fill=(50, 50, 50), font=font_names)

bbox2 = draw.textbbox((0, 0), line2, font=font_names)
w2 = bbox2[2] - bbox2[0]
draw.text(((width - w2) / 2, split_y + 175), line2, fill=(50, 50, 50), font=font_names)

# 3. Date & Venue at bottom right
date_text = "2010.12.31 - 2011.01.01  南京江南剧院"
bbox_date = draw.textbbox((0, 0), date_text, font=font_date)
w_date = bbox_date[2] - bbox_date[0]
draw.text((width - w_date - 40, height - 40), date_text, fill=(120, 120, 120), font=font_date)

# Save result
output_path = r"D:\AI\电报机器人\Cover_wmyanj_final.jpg"
im.save(output_path, "JPEG", quality=98)
print("Saved perfect cover to", output_path)

import http.server
import socketserver
import webbrowser
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

PORT = 8088
WEB_DIR = r"D:\AI\电报机器人\webapp"

os.chdir(WEB_DIR)
Handler = http.server.SimpleHTTPRequestHandler

print(f"==================================================")
print(f"🎵 李志沉浸式黑胶 Mini App 本地预览服务已就绪！")
print(f"🌐 本地访问地址: http://localhost:{PORT}")
print(f"==================================================")

url = f"http://localhost:{PORT}/index.html"
try:
    webbrowser.open(url)
except Exception:
    pass

with socketserver.TCPServer(("", PORT), Handler) as httpd:
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("服务已停止。")

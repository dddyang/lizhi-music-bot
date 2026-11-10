# -*- coding: utf-8 -*-
import os
import sys

# 适配 Windows 控制台输出编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import subprocess
import time
import urllib.request
import urllib.error

R2S_HOST = os.getenv("R2S_HOST", "192.168.100.1")
R2S_USER = os.getenv("R2S_USER", "root")
R2S_PASS = os.getenv("R2S_PASS") or os.getenv("R2S_PASSWORD", "")

# 若环境变量未设置，尝试从项目根目录 .env 中加载
if not R2S_PASS:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("R2S_PASS=") or line.strip().startswith("R2S_PASSWORD="):
                    R2S_PASS = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    break

def run_ssh_command(cmd):
    askpass = os.path.join(os.getenv("TEMP", "."), "askpass_r2s.cmd")
    with open(askpass, "w", encoding="ascii") as f:
        f.write(f"@echo off\necho {R2S_PASS}\n")

    env = os.environ.copy()
    env["SSH_ASKPASS"] = askpass
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = "dummy:0"

    try:
        res = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", f"{R2S_USER}@{R2S_HOST}", cmd],
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30
        )
        return res.returncode, res.stdout, res.stderr
    finally:
        if os.path.exists(askpass):
            os.remove(askpass)

def scp_file_to_r2s(local_file, remote_file):
    askpass = os.path.join(os.getenv("TEMP", "."), "askpass_scp.cmd")
    with open(askpass, "w", encoding="ascii") as f:
        f.write(f"@echo off\necho {R2S_PASS}\n")

    env = os.environ.copy()
    env["SSH_ASKPASS"] = askpass
    env["SSH_ASKPASS_REQUIRE"] = "force"
    env["DISPLAY"] = "dummy:0"

    try:
        res = subprocess.run(
            ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", local_file, f"{R2S_USER}@{R2S_HOST}:{remote_file}"],
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30
        )
        return res.returncode, res.stdout, res.stderr
    finally:
        if os.path.exists(askpass):
            os.remove(askpass)

def main():
    print(">>> 1. 同步 stream_server.py 到 NanoPi R2S...")
    local_server = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "bot", "stream_server.py"))
    code, out, err = scp_file_to_r2s(local_server, "/root/tg-music-bot/stream_server.py")
    if code != 0:
        print(f"❌ 同步失败: {err}")
        return
    print("✅ stream_server.py 已成功同步至 /root/tg-music-bot/stream_server.py")

    print(">>> 2. 重启软路由流媒体服务: /etc/init.d/tg-music-stream restart...")
    code, out, err = run_ssh_command("/etc/init.d/tg-music-stream restart")
    print(out)
    if err and "Warning" not in err:
        print(f"错误输出: {err}")

    time.sleep(2)

    print(">>> 3. 查看服务状态与进程信息...")
    code, out, err = run_ssh_command("/etc/init.d/tg-music-stream status; ps | grep stream_server | grep -v grep")
    print(out)

    print(">>> 4. 测试本地内网流媒体服务健康检查 (GET /health)...")
    try:
        req = urllib.request.Request(f"http://{R2S_HOST}:8880/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"✅ 健康检查状态: {resp.status}, 响应: {resp.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ 健康检查异常: {e}")

    print(">>> 5. 测试歌曲 1 的 HEAD 请求...")
    try:
        req = urllib.request.Request(f"http://{R2S_HOST}:8880/stream/audio/1", method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"✅ 歌曲 1 HEAD 状态: {resp.status}")
            for k, v in resp.headers.items():
                print(f"   {k}: {v}")
    except Exception as e:
        print(f"❌ 歌曲 1 HEAD 异常: {e}")

    print(">>> 6. 测试歌曲 1 的 Range 截取请求 (前 1024 字节)...")
    try:
        req = urllib.request.Request(f"http://{R2S_HOST}:8880/stream/audio/1")
        req.add_header("Range", "bytes=0-1023")
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"✅ 歌曲 1 Range 状态: {resp.status} (期望 206)")
            print(f"   Content-Range: {resp.headers.get('Content-Range')}")
            print(f"   Content-Length: {resp.headers.get('Content-Length')}")
            content = resp.read()
            print(f"   实测接收分片大小: {len(content)} 字节")
    except Exception as e:
        print(f"❌ 歌曲 1 Range 异常: {e}")

if __name__ == "__main__":
    main()

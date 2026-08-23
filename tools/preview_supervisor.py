"""预览监督器（Python 版，等价于 start_preview.cmd 的自愈逻辑）。

开机任务 cw-preview 在系统层会以 SYSTEM 身份运行 tools/start_preview.cmd；
本脚本用于「当下即时」拉起自愈（无需等待下次重启），二者端口检测逻辑一致、互相幂等：
- 检测 5000 端口（Flask/waitress），掉了就重启。
"""
import os
import subprocess
import sys
import time

# 项目根目录：本文件位于 <根>/tools/preview_supervisor.py，向上一级即根；
# 从文件自身路径反推，不再依赖写死的绝对路径。
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, "venv", "Scripts", "python.exe")
PORT = 5000
LOG = os.path.join(PROJ, "tools", "preview_supervisor_py.log")

# Windows: 脱离父控制台启动子进程（避免被前台 shell 关闭连带杀掉）
DETACHED = 0x08000000


def port_in_use(port):
    """用 TCP 连接探测端口是否被监听（比 netstat 更稳，不依赖外部命令）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (ts, msg))
    except Exception:
        pass


def kill_stray():
    """启动前清掉同项目残留的 waitress，避免重复实例（孤儿进程）。"""
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*customer-workspace*' -and $_.CommandLine -like '*waitress*' } | ForEach-Object { taskkill /F /PID $_.ProcessId }"],
            capture_output=True, text=True, timeout=20)
    except Exception:
        pass


def start_waitress():
    kill_stray()
    env = dict(os.environ)
    # 保活已独立为 cw-preview 计划任务，不再由本进程内启动
    subprocess.Popen(
        [PY, "-m", "waitress", "--host=0.0.0.0", "--port=%d" % PORT, "app:app"],
        cwd=PROJ, env=env, creationflags=DETACHED,
    )


def main():
    log("Python 预览监督器启动（监视 Flask:%d）" % PORT)
    while True:
        try:
            if not port_in_use(PORT):
                log("Flask 未运行，重启 waitress")
                start_waitress()
                time.sleep(5)
        except Exception as e:
            log("循环异常: %s" % e)
        time.sleep(30)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("监督器被手动停止")
        sys.exit(0)

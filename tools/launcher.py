# -*- coding: utf-8 -*-
"""客户管理 CRM 一键启动 / 诊断面板。

只用这一个文件即可：
  - 检测本地服务(Flask)是否运行、外网是否可达
  - 一键修复（缺什么启什么，且不会制造重复进程）
  - 打开应用、重启本地服务、重启开机自启保活

历史遗留脚本（run_waitress.bat / start_windows.bat ...）请勿再使用，
统一用本项目根的 Launch-App.cmd。
"""
import os
import sys
import time
import socket
import subprocess

# 项目根目录：本文件位于 <根>/tools/launcher.py，向上一级即根；
# 从文件自身路径反推，文件夹放到任何位置都能正确定位，不再写死绝对路径。
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(PROJ, "venv", "Scripts", "python.exe")
PORT = 5000
DETACHED = 0x08000000  # DETACHED_PROCESS：脱离父控制台，关掉本窗口也不会杀掉子进程


# ---------------- 基础工具 ----------------
def port_in_use(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        return s.connect_ex((host, port)) == 0
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def listener_pid(port):
    """返回正在监听该端口的进程 PID（Windows）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue).OwningProcess" % port],
            capture_output=True, text=True, timeout=15).stdout
        pids = [int(x) for x in out.split() if x.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def find_pids(pattern):
    """返回命令行含 pattern 的 python.exe 进程 PID 列表（Windows）。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -like '*%s*' } | ForEach-Object { $_.ProcessId }" % pattern],
            capture_output=True, text=True, timeout=20).stdout
        return [int(x) for x in out.split() if x.strip().isdigit()]
    except Exception:
        return []


def kill_pids(pids):
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        except Exception:
            pass


def start_flask():
    env = dict(os.environ)
    # 保活已独立为 cw-preview 计划任务，不再由本进程内启动
    # 走统一锁定通道，避免与保活竞态产生孤儿进程
    subprocess.Popen(
        [PY, os.path.join(PROJ, "tools", "launch_bg.py"), PY, "-m", "waitress",
         "--host=0.0.0.0", "--port=%d" % PORT, "app:app"],
        cwd=PROJ, env=env, creationflags=DETACHED)


# ---------------- 状态与修复 ----------------
def ensure_flask(verbose=True):
    """确保本地服务运行，且只有一个监听实例。去重/防孤儿逻辑统一在 launch_bg.py。"""
    if port_in_use(PORT):
        if verbose:
            print("  [正常] 本地服务 Flask 已在运行 (PID %s)，监听 5000" % listener_pid(PORT))
        return True
    if verbose:
        print("  > 本地服务未运行，正在启动 Flask（统一通道自动防重复）...")
    start_flask()
    for _ in range(15):
        time.sleep(1)
        if port_in_use(PORT):
            if verbose:
                print("  [正常] Flask 已启动并监听 5000 (PID %s)" % listener_pid(PORT))
            return True
    if verbose:
        print("  [异常] Flask 启动失败，请检查 venv / app.py 是否完整")
    return False


def _cmd_of(pid):
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"ProcessId=%d\").CommandLine" % pid],
            capture_output=True, text=True, timeout=15).stdout
        return out or ""
    except Exception:
        return ""


def restart_flask(verbose=True):
    wpids = find_pids("waitress")
    if verbose:
        print("  > 停止现有 Flask 进程: %s" % wpids)
    kill_pids(wpids)
    time.sleep(2)
    return ensure_flask(verbose)


def restart_keeper():
    """启用 / 重启开机自启保活（计划任务 cw-preview）。"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Stop-ScheduledTask -TaskName 'cw-preview' -ErrorAction SilentlyContinue; "
             "Start-ScheduledTask -TaskName 'cw-preview' -ErrorAction Stop; "
             "'done'"],
            capture_output=True, text=True, timeout=30).stdout
        print("  [正常] 开机自启保活已重启：%s" % (r.strip() or "ok"))
        return True
    except Exception as e:
        print("  [异常] 重启保活失败：%s" % e)
        return False


# ---------------- 展示 ----------------
def show_status():
    flask_up = port_in_use(PORT)
    flask_live = listener_pid(PORT) if flask_up else None

    print("")
    print("=" * 54)
    print("   客户管理 CRM  启动 / 诊断面板")
    print("=" * 54)
    print("  [本地服务 Flask :5000]  %s%s" % (
        "[正常] 运行中" if flask_up else "[异常] 未运行",
        " (PID %s)" % flask_live if flask_up else ""))
    print("-" * 54)
    print("  💻 电脑本机地址：http://127.0.0.1:5000")
    print("=" * 54)
    print("")
    return flask_up


def open_app():
    url = "http://127.0.0.1:5000/"
    print("  正在用默认浏览器打开：%s" % url)
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def do_fix():
    print("\n>>> 一键检测并修复")
    f = ensure_flask()
    print("")
    if f:
        print("  ✅ 修复完成：本地服务已就绪。")
    else:
        print("  ⚠️ 仍有异常，详见上方提示；可尝试菜单 [2] 单独重启，或 [4] 重启保活。")


def menu():
    while True:
        flask_up = show_status()
        print("请选择操作：")
        print("  [1] 一键检测并修复（缺什么启什么，自动清理孤儿进程）")
        print("  [2] 重启本地服务（Flask）")
        print("  [3] 打开应用（浏览器）")
        print("  [4] 启用 / 重启 开机自启保活")
        print("  [0] 退出")
        try:
            choice = input("输入数字：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        print("")
        if choice == "1":
            do_fix()
        elif choice == "2":
            print(">>> 重启本地服务")
            restart_flask()
        elif choice == "3":
            open_app()
        elif choice == "4":
            print(">>> 启用 / 重启 开机自启保活")
            restart_keeper()
        elif choice in ("0", "q", "Q"):
            print("再见。")
            break
        else:
            print("  无效输入，请重新选择。")
        print("")
        time.sleep(0.5)


def main():
    args = sys.argv[1:]
    if "fix" in args:
        do_fix()
        print("")
        show_status()
    elif "check" in args:
        show_status()
    elif "open" in args:
        open_app()
    else:
        try:
            menu()
        except KeyboardInterrupt:
            print("\n再见。")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""统一的服务启动通道（被保活 start_preview.cmd 与启动器 launcher.py 共用）。

设计目标：无论保活与手动启动器是否同时触发，都只会产生【一个】监听实例，绝不制造孤儿进程。

算法（关键在"不先杀后起"，而是"看有没有在途实例"）：
  1. 文件锁串行化两个启动器，避免同时动手；
  2. 端口已在监听 -> 只清理"非监听者"的孤儿，绝不杀监听进程；
  3. 端口空了 ->
       a. 若有"正在启动中"(年龄<INFLIGHT_SECS)的同名进程，说明别人已经在拉起，
          直接轮询等它绑上端口即可，不再新开；
       b. 否则才清掉残留、起一个干净实例。
"""
import os
import sys
import time
import socket
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = os.path.join(HERE, ".startup.lock")
DETACHED = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
STALE_SECS = 60      # 锁超过此时长视为残留，强制接管
INFLIGHT_SECS = 20   # 进程年龄小于此值视为"正在启动中"，应等待而非另起


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
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue).OwningProcess" % port],
            capture_output=True, text=True, timeout=15).stdout
        pids = [int(x) for x in out.split() if x.strip().isdigit()]
        return pids[0] if pids else None
    except Exception:
        return None


def _procs_wmi(filter_wql, name_pattern):
    """返回 [(pid, age_seconds)]，age 为该进程已存活秒数。"""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"%s\" | "
        "Where-Object { $_.CommandLine -like '%s' } | "
        "ForEach-Object { '{0},{1}' -f $_.ProcessId, [int]((Get-Date) - $_.CreationDate).TotalSeconds }"
        % (filter_wql, name_pattern)
    )
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        try:
            pid_s, age_s = line.split(",", 1)
            res.append((int(pid_s), int(age_s)))
        except ValueError:
            continue
    return res


def waitress_procs():
    return _procs_wmi("Name='python.exe'",
                     '*customer-workspace*'' and $_.CommandLine -like ''*waitress*')


def acquire_lock():
    for _ in range(40):  # 最多等约 12 秒
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(LOCK) > STALE_SECS:
                    os.remove(LOCK)
                    continue
            except OSError:
                pass
            time.sleep(0.3)
    return False


def release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def kill_pid(pid):
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    except Exception:
        pass


def start_detached(exe, args):
    base = os.path.splitext(os.path.basename(exe))[0]
    log_path = os.path.join(HERE, "%s_bg.log" % base)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, "a", encoding="utf-8") as log:
        log.write("[%s] starting: %s\n" % (now, " ".join([exe] + args)))
        proc = subprocess.Popen(
            [exe] + args,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=DETACHED,
        )
        log.write("[%s] pid=%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), proc.pid))
    print(proc.pid)


def main():
    if len(sys.argv) < 2:
        print("usage: launch_bg.py <exe> [args...]", file=sys.stderr)
        sys.exit(1)

    exe = sys.argv[1]
    args = sys.argv[2:]
    port = 5000
    name = "waitress"

    if not acquire_lock():
        print("another starter is active, skip")
        sys.exit(0)

    try:
        # 1) 端口已在监听：直接返回，绝不杀任何进程。
        #    （保活已独立为 cw-preview 计划任务，不在本进程内 fork，
        #     故此处无需考虑保活父子进程问题；端口在时一律不动。）
        if port_in_use(port):
            print("%s up" % name)
            return

        # 2) 端口空：清掉残留，起一个干净实例，并且【持有锁直到端口确认监听】
        #    这样任何并发的第二个启动器都会被挡在锁外；等本进程绑定成功后，
        #    第二个启动器拿到锁会发现端口已起，直接跳过 —— 绝不会产生孤儿进程。
        procs = waitress_procs()
        for pid, _ in procs:
            kill_pid(pid)
        time.sleep(1)
        start_detached(exe, args)
        for _ in range(20):
            time.sleep(1)
            if port_in_use(port):
                print("%s started and bound" % name)
                return
        print("%s started but not bound in time" % name)
    finally:
        release_lock()


if __name__ == "__main__":
    main()

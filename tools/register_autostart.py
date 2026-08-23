#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为本机注册 CRM 所需的「登录自启」任务（隐藏运行、路径运行时反推，零硬编码）。

由 Launch-App.cmd 在「换电脑首次打开」时调用。注册项：
  - cw-preview      -> tools/start_preview.cmd   （Flask 保活）
  - CRM-TrayMonitor -> tools/tray-monitor.cmd   （托盘状态监控）
两项均 Hidden 隐藏运行、登录触发、当前用户身份。已存在的任务跳过（双重保护，绝不覆盖）。

tools 目录由 __file__ 反推，故文件夹放哪都能注册。仅依赖标准库 + schtasks（Windows 自带）。
"""
import os
import subprocess
import sys
import tempfile
import xml.sax.saxutils as su

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))

# (任务名, 要运行的 cmd 文件名)
TASKS = [
    ("cw-preview", "start_preview.cmd"),
    ("CRM-TrayMonitor", "tray-monitor.cmd"),
]


def build_xml(target_cmd: str) -> str:
    """动态生成任务 XML。target_cmd 可能含空格，作为 cmd 参数需加引号，
    作为 XML 属性值内的引号必须转义为 &quot;。"""
    args = "/c &quot;{}&quot;".format(su.escape(target_cmd))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo>\n'
        '    <Description>CRM auto-start task (auto-registered by Launch-App.cmd)</Description>\n'
        '  </RegistrationInfo>\n'
        '  <Triggers>\n'
        '    <LogonTrigger>\n'
        '      <Enabled>true</Enabled>\n'
        '    </LogonTrigger>\n'
        '  </Triggers>\n'
        '  <Principals>\n'
        '    <Principal id="Author">\n'
        '      <LogonType>InteractiveToken</LogonType>\n'
        '      <RunLevel>LeastPrivilege</RunLevel>\n'
        '    </Principal>\n'
        '  </Principals>\n'
        '  <Settings>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        '    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n'
        '    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n'
        '    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n'
        '    <Hidden>true</Hidden>\n'
        '  </Settings>\n'
        '  <Actions>\n'
        '    <Exec>\n'
        '      <Command>cmd.exe</Command>\n'
        '      <Arguments>' + args + '</Arguments>\n'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )


def task_exists(name: str) -> bool:
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", name],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def register_one(name: str, cmd_file: str) -> int:
    """返回 0=已就绪(已存在或新建成功) 1=注册失败 2=目标 cmd 文件缺失"""
    target = os.path.join(TOOLS_DIR, cmd_file)
    if not os.path.exists(target):
        print("[错误] 找不到 {}: {}".format(cmd_file, target))
        return 2
    if task_exists(name):
        print("[跳过] 任务 {} 已存在".format(name))
        return 0
    xml = build_xml(target)
    fd, path = tempfile.mkstemp(suffix=".xml", prefix="crm_task_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml)
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", name, "/XML", path, "/F"],
            capture_output=True, text=True,
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if r.returncode == 0:
        print("[完成] 已注册 {}（隐藏运行，路径={}）".format(name, target))
        return 0
    print("[失败] {} schtasks 返回 {}: {}".format(name, r.returncode, r.stderr.strip() or r.stdout.strip()))
    return 1


def main() -> int:
    rc = 0
    for name, cmd_file in TASKS:
        r = register_one(name, cmd_file)
        if r != 0:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

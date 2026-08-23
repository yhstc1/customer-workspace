# -*- coding: utf-8 -*-
"""FC 自定义运行时入口：自行安装依赖 + 用标准库 wsgiref 跑 Flask app，监听 9000。

为什么不用 FC 内置「Web 函数」：
FC Web 函数网关对所有动态路由响应强制注入 Content-Disposition: attachment，
应用层设 inline 无法覆盖 → 浏览器必下载 HTML，H5 永远打不开。
自定义运行时模式下，FC 只做 L7 转发、不注入响应头，响应头完全由本 server 决定，
因此 /m.html 可以正常返回 inline 的 text/html，浏览器直接渲染。

关键设计：本脚本**不依赖 bootstrap 文件**，直接在 FC 启动命令里调用：
    <python3 绝对路径> /code/server.py
依赖安装也放在本脚本开头（subprocess 调 sys.executable -m pip），
避免依赖 shell 的 bootstrap 协议（FC 在某些自定义运行时组合下不执行 bootstrap）。

wsgiref 是 Python 标准库，无需安装。
"""
import os
import sys
import subprocess
import shutil

# 确保当前目录在 sys.path（FC 自定义运行时的工作目录即代码包根 /code）
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)


def _prepare_db():
    """准备存储后端。

    - **MySQL 模式**（设置了 MYSQL_HOST）：数据全部在 RDS，无需本地 SQLite 文件，
      直接跳过 /tmp 拷贝，避免冷启动把过期包内 db 拷进 /tmp 误导排查。
    - **SQLite 模式**（未设置 MYSQL_HOST）：FC 自定义运行时 /code 只读，
      把包内只读 db 复制到可写层 /tmp 后用（冷启动自动从代码包恢复数据）。
    """
    if os.environ.get("MYSQL_HOST"):
        print("[server] MySQL 模式：数据存 RDS，跳过本地 db 准备", flush=True)
        return
    writable_db = os.environ.get("CUSTOMER_DB_PATH") or os.path.join("/tmp", "crm_data", "customers.db")
    os.environ["CUSTOMER_DB_PATH"] = writable_db
    db_dir = os.path.dirname(writable_db)
    os.makedirs(db_dir, exist_ok=True)
    if not os.path.exists(writable_db):
        src = os.path.join(CODE_DIR, "data", "customers.db")
        if os.path.exists(src):
            shutil.copyfile(src, writable_db)
            print(f"[server] db copied -> {writable_db}", flush=True)
        else:
            print("[server] no bundled db, will create empty", flush=True)
    else:
        print(f"[server] db exists -> {writable_db}", flush=True)


_prepare_db()


def _ensure_deps():
    """首次启动安装依赖（冷启动会慢几秒，之后实例常驻不再重装）。"""
    req = os.path.join(CODE_DIR, "requirements.txt")
    if not os.path.exists(req):
        return
    try:
        # 探测关键依赖是否已存在，存在则跳过安装（加速热启动）
        import importlib
        importlib.import_module("flask")
        return
    except Exception:
        pass
    # 用当前解释器安装（不依赖 PATH 中的 pip 命令）
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", req, "-q", "--no-cache-dir"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        print("[server] deps installed", flush=True)
    except Exception as e:
        print(f"[server] pip install failed: {e}", flush=True)


_ensure_deps()

import app as app_module  # 导入 Flask app 实例

from wsgiref.simple_server import make_server

PORT = int(os.environ.get("FC_CUSTOM_PORT", "9000"))


def main():
    application = app_module.app
    # 自定义运行时：自己写响应头，绝不被网关覆盖
    httpd = make_server("0.0.0.0", PORT, application)
    print(f"[server] listening on 0.0.0.0:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()

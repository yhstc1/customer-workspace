# -*- coding: utf-8 -*-
"""打包 FC 自定义运行时部署包：纯源码 + templates + static + m.html + server.py。
不依赖 bootstrap 文件：FC 启动命令直接调用 <python> /code/server.py，
依赖安装由 server.py 自身负责（subprocess 调 sys.executable -m pip）。
"""
import os
import zipfile
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)  # customer-workspace

# 后端源码文件
backend_files = [
    'app.py', 'models.py', 'geo_service.py', 'dingtalk_notify.py',
    'report_generator.py', 'requirements.txt',
]

ZIP_NAME = os.path.join(ROOT, "crm-api-custom-runtime-v2.zip")


def main():
    if os.path.exists(ZIP_NAME):
        try:
            os.remove(ZIP_NAME)
        except OSError:
            pass  # 沙箱回收站不可用时忽略

    with zipfile.ZipFile(ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as z:
        # 后端源码（从项目根目录读取，不在 aliyun-backend/）
        for f in backend_files:
            if f == 'server.py':
                continue  # server.py 单独处理
            fp = os.path.join(PROJECT_ROOT, f)
            if os.path.exists(fp):
                z.write(fp, f)
                print("added", f)

        # server.py 从 aliyun-backend/ 读取（FC 启动入口）
        server_fp = os.path.join(ROOT, 'server.py')
        if os.path.exists(server_fp):
            z.write(server_fp, 'server.py')
            print("added server.py (from aliyun-backend/)")

        # 模板
        tpl_dir = os.path.join(PROJECT_ROOT, "templates")
        if os.path.isdir(tpl_dir):
            for root, _, files in os.walk(tpl_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, PROJECT_ROOT)  # templates/...
                    z.write(full, arc)
            print("added templates/")

        # m.html（H5 入口，已注入 API_BASE）
        m_html = os.path.join(ROOT, "m.html")
        if os.path.exists(m_html):
            z.write(m_html, "m.html")
            print("added m.html")

        # 本地真实数据库（含 157 条客户），让 FC 默认 SQLite 路径直接读到
        db_src = os.path.join(PROJECT_ROOT, "data", "customers.db")
        if os.path.exists(db_src):
            z.write(db_src, "data/customers.db")
            print("added data/customers.db (local real data)")
        else:
            print("WARN: data/customers.db 不存在，FC 将使用空库")

        # 静态资源（剔除 apk 等大文件）
        static_dir = os.path.join(PROJECT_ROOT, "static")
        if os.path.isdir(static_dir):
            for root, dirs, files in os.walk(static_dir):
                # 排除无关目录
                dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
                for fn in files:
                    if fn.endswith('.apk') or fn.endswith('.pyc'):
                        continue
                    full = os.path.join(root, fn)
                    arc = os.path.relpath(full, PROJECT_ROOT)  # static/...
                    z.write(full, arc)
            print("added static/")

    size = os.path.getsize(ZIP_NAME)
    print(f"\n打包完成: {ZIP_NAME} ({size/1024:.0f} KB)")


if __name__ == "__main__":
    main()

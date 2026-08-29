# -*- coding: utf-8 -*-
"""
CRM 生产库只读查询小工具（沙箱/本机一键执行，自动读取 aliyun-backend/.env 的 RDS 密钥）

用法：
    venv/Scripts/python.exe migration/query_crm.py "SELECT id, business_type, start_date, end_date FROM businesses WHERE business_type='U+产品'"
    venv/Scripts/python.exe migration/query_crm.py --file some.sql

输出：表格式打印结果（最多 500 行）。仅 SELECT，禁止写操作（含 --force 才允许其他语句）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_dotenv(path):
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and not os.environ.get(k):
                    os.environ[k] = v
    except Exception as e:
        print("[WARN] 读取 .env 失败：%s" % e)


_load_dotenv(os.path.join(ROOT, "aliyun-backend", ".env"))

REQUIRED = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DB", "MYSQL_PASSWORD"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    sys.exit("缺少环境变量：" + ", ".join(missing) + "（应可从 aliyun-backend/.env 自动加载）")

import pymysql  # noqa: E402

args = sys.argv[1:]
force = "--force" in args
if force:
    args.remove("--force")
if not args:
    sys.exit("用法：python migration/query_crm.py \"SELECT ...\"")

if args[0] == "--file":
    with open(args[1], "r", encoding="utf-8") as fh:
        sql = fh.read()
else:
    sql = args[0]

head = sql.lstrip().lower()
if not force and not head.startswith("select") and not head.startswith("show") and not head.startswith("desc"):
    sys.exit("拒绝执行非只读语句（如需强制请加 --force）：" + sql[:80])

conn = pymysql.connect(
    host=os.environ["MYSQL_HOST"],
    port=int(os.environ.get("MYSQL_PORT", "3306")),
    user=os.environ["MYSQL_USER"],
    password=os.environ["MYSQL_PASSWORD"],
    database=os.environ["MYSQL_DB"],
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)
try:
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()
        if not rows:
            print("(0 行)")
        else:
            cols = list(rows[0].keys())
            widths = [max(len(str(c)), *(len(str(r[c])) for r in rows)) for c in cols]
            widths = [min(w, 40) for w in widths]
            print(" | ".join(str(c).ljust(widths[i])[: widths[i]] for i, c in enumerate(cols)))
            print("-+-".join("-" * w for w in widths))
            for r in rows[:500]:
                print(" | ".join(str(r[c])[: widths[i]].ljust(widths[i]) for i, c in enumerate(cols)))
            print("(%d 行)" % len(rows))
finally:
    conn.close()

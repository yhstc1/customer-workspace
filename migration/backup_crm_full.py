# -*- coding: utf-8 -*-
"""
CRM 生产库全量备份脚本（纯 Python / pymysql，无需 mysqldump 客户端）

用法（在本机 PowerShell，从仓库根目录执行）：
    $env:MYSQL_HOST="rm-bp1x01d9d8g8i844qlo.rwlb.rds.aliyuncs.com"
    $env:MYSQL_PORT="3306"; $env:MYSQL_USER="crm_user"; $env:MYSQL_DB="crm"
    $env:MYSQL_PASSWORD=Read-Host "请输入RDS密码"
    venv/Scripts/python.exe migration/backup_crm_full.py

产出：仓库根 backup_crm_<YYYYMMDD_HHMMSS>.sql
恢复：mysql -h<host> -u<user> -p<db> < backup_crm_xxx.sql
"""
import os
import sys
import pymysql
from datetime import datetime, date

REQUIRED = ["MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_DB", "MYSQL_PASSWORD"]
missing = [k for k in REQUIRED if not os.environ.get(k)]
if missing:
    sys.exit("缺少环境变量：" + ", ".join(missing) + "\n请先在本机 PowerShell 设好 MYSQL_HOST/PORT/USER/DB/PASSWORD 再运行。")

HOST = os.environ["MYSQL_HOST"]
PORT = int(os.environ.get("MYSQL_PORT", "3306"))
USER = os.environ["MYSQL_USER"]
DB = os.environ["MYSQL_DB"]
PWD = os.environ["MYSQL_PASSWORD"]

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f"backup_crm_{TS}.sql")


def esc(val):
    if val is None:
        return "NULL"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, (datetime, date)):
        return "'" + str(val) + "'"
    if isinstance(val, bytes):
        val = val.decode("utf-8", "replace")
    s = str(val).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return "'" + s + "'"


def main():
    print(f"连接 RDS {HOST}:{PORT} / {DB} ...")
    conn = pymysql.connect(host=HOST, port=PORT, user=USER, password=PWD, database=DB,
                           charset="utf8mb4", connect_timeout=30)
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = [r[0] for r in cur.fetchall()]
    print(f"共 {len(tables)} 张表：{', '.join(tables)}")

    lines = []
    lines.append(f"-- CRM 全量备份  {TS}")
    lines.append(f"-- host={HOST} db={DB}")
    lines.append("SET NAMES utf8mb4;")
    lines.append("SET FOREIGN_KEY_CHECKS=0;")
    lines.append("")

    for t in tables:
        cur.execute(f"SHOW CREATE TABLE `{t}`")
        create_sql = cur.fetchone()[1]
        lines.append(f"-- ---- 表 {t} ----")
        lines.append(f"DROP TABLE IF EXISTS `{t}`;")
        lines.append(create_sql + ";")
        cur.execute(f"SELECT * FROM `{t}`")
        rows = cur.fetchall()
        if not rows:
            lines.append(f"-- {t}: 0 行")
            lines.append("")
            continue
        col_count = len(cur.description)
        col_names = [d[0] for d in cur.description]
        cols_sql = ", ".join(f"`{c}`" for c in col_names)
        BATCH = 500
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            val_strs = []
            for row in chunk:
                val_strs.append("(" + ", ".join(esc(row[j]) for j in range(col_count)) + ")")
            lines.append(f"INSERT INTO `{t}` ({cols_sql}) VALUES\n" + ",\n".join(val_strs) + ";")
        lines.append(f"-- {t}: {len(rows)} 行")
        lines.append("")
        print(f"  [ok] {t}: {len(rows)} 行")

    lines.append("SET FOREIGN_KEY_CHECKS=1;")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    cur.close()
    conn.close()
    size = os.path.getsize(OUT)
    print(f"\n✅ 备份完成：{OUT}  ({size/1024:.1f} KB)")
    print("下一步：把此 .sql 文件留存好，再喊 AI 继续「删列迁移」。")


if __name__ == "__main__":
    main()

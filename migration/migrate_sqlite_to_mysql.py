"""
SQLite -> RDS MySQL 一次性迁移脚本
====================================
前置步骤：
  1. 在 RDS 执行 schema_mysql.sql 建表（见同目录）
  2. pip install pymysql
  3. 填写下方 MYSQL 连接参数（推荐用环境变量注入，避免明文）
运行：
  MYSQL_HOST=rm-xxx.mysql.rds.aliyuncs.com MYSQL_USER=crm \
  MYSQL_PASSWORD='你的密码' MYSQL_DB=crm \
  python migrate_sqlite_to_mysql.py
"""
import sqlite3
import os
import pymysql

SQLITE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "customers.db")

# ===== RDS MySQL 连接参数（建议用环境变量，不要硬编码密码）=====
MYSQL = dict(
    host=os.environ.get("MYSQL_HOST", "rm-xxxx.mysql.rds.aliyuncs.com"),
    port=int(os.environ.get("MYSQL_PORT", 3306)),
    user=os.environ.get("MYSQL_USER", "crm"),
    password=os.environ.get("MYSQL_PASSWORD", "你的密码"),
    database=os.environ.get("MYSQL_DB", "crm"),
    charset="utf8mb4",
)

# 依赖顺序：先父表后子表，避免外键约束报错
TABLE_ORDER = [
    "users", "customers", "tasks", "subtasks",
    "businesses", "password_resets", "checkins", "settings",
]


def conv(v):
    """SQLite 的 bytes 类型解码为 str；其余原样返回（pymysql 自动适配类型）。"""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except Exception:
            return v
    return v


def main():
    sconn = sqlite3.connect(SQLITE_DB)
    sconn.row_factory = sqlite3.Row
    scur = sconn.cursor()

    mconn = pymysql.connect(**MYSQL)
    mcur = mconn.cursor()

    mcur.execute("SET FOREIGN_KEY_CHECKS=0")

    for tbl in TABLE_ORDER:
        cols = [r[1] for r in scur.execute(f"PRAGMA table_info({tbl})").fetchall()]
        rows = scur.execute(f"SELECT {','.join(cols)} FROM {tbl}").fetchall()
        if not rows:
            print(f"[SKIP] {tbl}: 0 行")
            continue
        placeholders = ",".join(["%s"] * len(cols))
        # 列名加反引号，避免 year_month 等保留字/关键字列名报错
        col_list = ",".join(f"`{c}`" for c in cols)
        sql = f"INSERT INTO {tbl} ({col_list}) VALUES ({placeholders})"
        data = [tuple(conv(v) for v in row) for row in rows]
        mcur.executemany(sql, data)
        mconn.commit()

        # 修正 AUTO_INCREMENT 计数器，避免后续新插入主键冲突
        # settings 为复合主键、无 id 列，跳过该步
        if "id" in cols:
            mcur.execute(f"SELECT MAX(id) FROM {tbl}")
            mx = mcur.fetchone()[0] or 0
            mcur.execute(f"ALTER TABLE {tbl} AUTO_INCREMENT={mx + 1}")
            mconn.commit()
        print(f"[OK] {tbl}: 迁移 {len(rows)} 行")

    mcur.execute("SET FOREIGN_KEY_CHECKS=1")
    sconn.close()
    mconn.close()
    print("迁移完成。")


if __name__ == "__main__":
    main()

"""迁移：从 tasks 表移除 priority / progress 两个冗余列。

背景：事项模块的「优先级（重要紧急矩阵）/ 进度（0-100）」字段前端早已不渲染、
后端保存也不读取，属于死字段。本脚本在生产 RDS（或本地 SQLite）上将其删除，保持
表结构干净，避免 AR 对账 / 导出时误用。

使用方式（请在已配置 MySQL 环境、且已备份 RDS 的前提下运行）：
    # 1) 备份（示例，按你的实际凭据/工具执行）
    #    mysqldump -h <host> -u <user> -p crm tasks > tasks_backup_$(date +%F).sql
    # 2) 用 venv 运行本脚本（需设置 MYSQL_HOST 等环境变量，与 models.py 一致）
    venv\\Scripts\\python.exe migration\\drop_task_dead_columns.py

幂等：列不存在则跳过，可反复运行。仅删除列，不触碰任何业务数据。
"""
import os
import sys

import pymysql
import sqlite3

TABLE = "tasks"
COLS = ("priority", "progress")


def _mysql_cfg():
    return dict(
        host=os.environ.get("MYSQL_HOST"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER"),
        password=os.environ.get("MYSQL_PASSWORD"),
        database=os.environ.get("MYSQL_DB"),
    )


def _col_exists_mysql(cur, table, col):
    cur.execute(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
        (table, col),
    )
    return cur.fetchone()[0] > 0


def _col_exists_sqlite(conn, table, col):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return col in [r[1] for r in rows]


def main():
    use_mysql = bool(os.environ.get("MYSQL_HOST")) and pymysql is not None
    if use_mysql:
        raw = pymysql.connect(**_mysql_cfg())
        try:
            cur = raw.cursor()
            for col in COLS:
                if _col_exists_mysql(cur, TABLE, col):
                    print(f"[DROP] {TABLE}.{col} (MySQL)")
                    cur.execute(f"ALTER TABLE `{TABLE}` DROP COLUMN `{col}`")
                else:
                    print(f"[skip] {TABLE}.{col} 不存在 (MySQL)")
            raw.commit()
        finally:
            raw.close()
    else:
        db = os.environ.get("CUSTOMER_DB_PATH") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "customers.db"
        )
        conn = sqlite3.connect(db)
        try:
            for col in COLS:
                if _col_exists_sqlite(conn, TABLE, col):
                    print(f"[DROP] {TABLE}.{col} (SQLite: {db})")
                    conn.execute(f"ALTER TABLE {TABLE} DROP COLUMN {col}")
                else:
                    print(f"[skip] {TABLE}.{col} 不存在 (SQLite)")
            conn.commit()
        finally:
            conn.close()
    print("[OK] 事项死列清理完成")


if __name__ == "__main__":
    main()

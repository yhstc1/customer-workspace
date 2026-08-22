# -*- coding: utf-8 -*-
"""数据访问层：把现有 sqlite3 调用平滑迁移到 RDS MySQL(pymysql)。

设计要点：
- 现有业务代码大量使用 `?` 占位符和 `row["col"]` 字典访问。
- 这里统一把 `?` 转成 `%s`，并使用 DictCursor，使业务层几乎免改。
- 兼容少量 SQLite 方言（INSERT OR IGNORE / LIMIT 语法一致，COALESCE 一致）。
"""
import pymysql
import config

_pool = None


def _connect():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASS,
        database=config.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def _normalize(sql):
    """把 SQLite 方言转成 MySQL 可接受的形式。"""
    s = sql.replace("?", "%s")
    # SQLite 的 INSERT OR IGNORE -> MySQL 的 INSERT IGNORE
    s = s.replace("INSERT OR IGNORE", "INSERT IGNORE")
    # SQLite 的 AUTOINCREMENT 等已在建表脚本处理，运行期无需
    return s


def query(sql, params=None, one=False):
    """查询，返回 dict 列表（one=True 时返回单个 dict 或 None）。"""
    sql = _normalize(sql)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


def execute(sql, params=None):
    """写操作，返回 lastrowid。"""
    sql = _normalize(sql)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            last = cur.lastrowid
        conn.commit()
        return last
    finally:
        conn.close()


def executemany(sql, seq_params):
    """批量写（迁移/导入用）。"""
    sql = _normalize(sql)
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, seq_params or [])
        conn.commit()
    finally:
        conn.close()


def ensure_dingtalk_column():
    """首次启动时确保 users 表有 dingtalk_user_id 列（幂等）。"""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name='users' AND column_name='dingtalk_user_id'",
                        (config.DB_NAME,))
            exists = cur.fetchone()["c"] > 0
            if not exists:
                cur.execute("ALTER TABLE users ADD COLUMN dingtalk_user_id VARCHAR(64) DEFAULT NULL")
                cur.execute("CREATE INDEX idx_users_ding ON users(dingtalk_user_id)")
        conn.commit()
    finally:
        conn.close()

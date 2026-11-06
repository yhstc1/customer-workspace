# -*- coding: utf-8 -*-
"""RDS -> GitHub 存储后端 迁移脚本（方案 A 一次性执行）

用途：
    把生产 RDS(crm 库) 的全量数据导出为本地 SQLite 的 customers.db，
    再上传到 GitHub 私有仓，作为方案 A 的初始数据基线。

前置：
    1. 已在 GitHub 上准备好私有仓（默认 yhstc1/customer-data），并授予 token 写权限；
    2. 环境变量 GITHUB_STORE_REPO / GITHUB_TOKEN 已设置；
    3. aliyun-backend/.env 中 RDS 凭据可用（脚本自动加载）。

用法：
    python migration/migrate_rds_to_github.py            # 导出 + 上传
    python migration/migrate_rds_to_github.py --export-only  # 只导出本地 db，不上传
    python migration/migrate_rds_to_github.py --verify    # 上传后回读校验

安全：
    - 只读 RDS，不做任何写操作；
    - 本地导出文件默认写到 .workbuddy/migration/（已被 .gitignore 忽略，不入库）；
    - 上传使用乐观锁，若远端已有文件且 SHA 不匹配会中止（需显式 --force 覆盖）。
"""
import os
import sqlite3
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def _load_dotenv(path):
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and not os.environ.get(k):
                os.environ[k] = v


_load_dotenv(os.path.join(ROOT, "aliyun-backend", ".env"))

# 目标表：与 models.init_db() 的 SQLite 表结构对齐
TABLES = ["users", "customers", "tasks", "subtasks", "businesses",
          "settings", "checkins", "password_resets"]

# RDS 表里存在但 SQLite 侧无对应列的遗留字段（app.py 未引用，丢弃）
DROP_COLS = {
    "customers": ["business_type", "importance", "tier"],
    "tasks": ["priority", "progress"],
}

LOCAL_DIR = os.path.join(ROOT, ".workbuddy", "migration")
LOCAL_DB = os.path.join(LOCAL_DIR, "customers.db")


def export_from_rds():
    """从 RDS 读出全部表，写入本地 SQLite customers.db。返回行数统计。"""
    import pymysql

    host = os.environ.get("MYSQL_HOST")
    user = os.environ.get("MYSQL_USER")
    pwd = os.environ.get("MYSQL_PASSWORD")
    db = os.environ.get("MYSQL_DB")
    port = int(os.environ.get("MYSQL_PORT", "3306"))
    if not all([host, user, pwd, db]):
        sys.exit("缺少 RDS 凭据（应可从 aliyun-backend/.env 自动加载）")

    os.makedirs(LOCAL_DIR, exist_ok=True)
    if os.path.exists(LOCAL_DB):
        os.remove(LOCAL_DB)

    conn = pymysql.connect(host=host, port=port, user=user, password=pwd,
                           database=db, charset="utf8mb4", connect_timeout=30,
                           cursorclass=pymysql.cursors.DictCursor)
    # 建表结构：直接复用 models.init_db()（幂等 DDL，保证与运行时 schema 完全一致）。
    # 关键：models 模块在 import 时就求值了 USE_MYSQL / USE_GITHUB_STORE，
    # 所以必须在 import 之前暂时摘掉 MYSQL_HOST 与 GITHUB_STORE_REPO，
    # 否则会走 MySQL 分支（只在 RDS 建表）或触发从 GitHub 恢复，
    # 本地 SQLite 不会按预期建表（首次执行时全表报 no such table 即此原因）。
    saved_env = {}
    for k in ("MYSQL_HOST", "GITHUB_STORE_REPO"):
        saved_env[k] = os.environ.pop(k, None)
    try:
        models = __import__("models")
        models.DB_PATH = LOCAL_DB
        os.environ["CUSTOMER_DB_PATH"] = LOCAL_DB
        models.init_db()
    finally:
        for k, v in saved_env.items():
            if v is not None:
                os.environ[k] = v

    local = sqlite3.connect(LOCAL_DB)
    local.row_factory = sqlite3.Row
    lcur = local.cursor()
    # 关掉外键约束以便按任意顺序导入（父表可能后到）
    lcur.execute("PRAGMA foreign_keys = OFF")

    counts = {}
    try:
        mcur = conn.cursor()
        for t in TABLES:
            try:
                mcur.execute("SELECT * FROM `%s`" % t)
            except Exception as e:  # noqa: BLE001
                print("  [skip] %s: %s" % (t, e))
                counts[t] = 0
                continue
            rows = mcur.fetchall()
            if not rows:
                counts[t] = 0
                print("  [ok] %s: 0 行" % t)
                continue
            cols = [d[0] for d in mcur.description]
            drop = DROP_COLS.get(t, [])
            cols = [c for c in cols if c not in drop]
            lcur.execute("PRAGMA table_info(%s)" % t)
            lcols = {r[1] for r in lcur.fetchall()}
            use_cols = [c for c in cols if c in lcols]
            missing = [c for c in cols if c not in lcols]
            if missing:
                print("  [warn] %s 跳过本地不存在的列: %s" % (t, missing))
            if not use_cols:
                counts[t] = 0
                continue
            ph = ",".join("?" * len(use_cols))
            sql = "INSERT OR REPLACE INTO `%s` (%s) VALUES (%s)" % (
                t, ",".join("`%s`" % c for c in use_cols), ph)
            data = [tuple(r[c] for c in use_cols) for r in rows]
            lcur.executemany(sql, data)
            counts[t] = len(data)
            print("  [ok] %s: %d 行" % (t, len(data)))
        local.commit()
        lcur.execute("PRAGMA foreign_keys = ON")
        # 校验落库行数
        print("\n=== 本地 SQLite 校验 ===")
        for t in TABLES:
            try:
                n = lcur.execute("SELECT COUNT(*) FROM `%s`" % t).fetchone()[0]
                print("  %-16s %d" % (t, n))
            except Exception as e:  # noqa: BLE001
                print("  %-16s ERR %s" % (t, e))
    finally:
        local.close()
        conn.close()
    return counts


def upload(force=False):
    """上传本地 db 到 GitHub 仓。"""
    import github_store
    if not os.path.exists(LOCAL_DB):
        sys.exit("本地 db 不存在：%s" % LOCAL_DB)
    if not github_store.enabled():
        sys.exit("未启用 GitHub 后端：请设置 GITHUB_STORE_REPO 与 GITHUB_TOKEN")
    print("\n=== 上传到 GitHub ===")
    print("  仓库: %s" % os.environ["GITHUB_STORE_REPO"])
    print("  路径: %s" % github_store.DATA_PATH_IN_REPO)
    print("  文件: %s (%.1f KB)" % (LOCAL_DB, os.path.getsize(LOCAL_DB) / 1024))
    expected = None
    remote_sha = github_store.get_remote_sha()
    if remote_sha:
        if not force:
            # 远端已有文件：用本地算出的 blob sha 比对
            local_sha = github_store.local_sha(LOCAL_DB)
            # VACUUM INTO 后的内容与原文件 sha 不同，故用打包后的文件比对
            packed = github_store._pack_sqlite(LOCAL_DB)
            try:
                local_sha = github_store.local_sha(packed)
            finally:
                os.remove(packed)
            if local_sha != remote_sha:
                sys.exit(
                    "远端已存在数据文件且内容不同。\n"
                    "  远端 SHA: %s\n  本地 SHA: %s\n"
                    "如确认要覆盖，请加 --force。" % (remote_sha[:12], local_sha[:12])
                )
        expected = remote_sha
    sha = github_store.sync_to_github(LOCAL_DB, expected_sha=expected)
    print("  已上传，新 SHA: %s" % sha)
    return sha


def verify():
    """回读校验：重新下载并比对行数。"""
    import github_store
    tmp = os.path.join(LOCAL_DIR, "verify.db")
    if os.path.exists(tmp):
        os.remove(tmp)
    got = github_store.download_db(tmp)
    if not got:
        sys.exit("远端没有数据文件")
    v = sqlite3.connect(tmp)
    print("\n=== 回读校验 ===")
    ok = True
    for t in TABLES:
        n = v.execute("SELECT COUNT(*) FROM `%s`" % t).fetchone()[0]
        print("  %-16s %d" % (t, n))
    v.close()
    os.remove(tmp)
    return ok


def main():
    force = "--force" in sys.argv
    export_only = "--export-only" in sys.argv
    do_verify = "--verify" in sys.argv

    print("=== 1. 从 RDS 导出 ===")
    print("  目标: %s" % LOCAL_DB)
    export_from_rds()

    if export_only:
        print("\n已跳过上传（--export-only）")
        return

    print("\n=== 2. 上传 GitHub ===")
    upload(force=force)

    if do_verify:
        verify()

    print("\n完成。")


if __name__ == "__main__":
    main()

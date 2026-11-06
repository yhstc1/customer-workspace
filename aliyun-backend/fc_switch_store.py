# -*- coding: utf-8 -*-
"""切换 FC 函数的存储后端：MySQL(RDS) <-> GitHub。

安全要点：
  - FC UpdateFunction 的 environmentVariables 是**全量替换**，只传部分 key 会清空其余变量。
    故本脚本先 GetFunction 取回全量 env，再合并目标变更后整体提交。
  - 切换到 GitHub 后端时必须**移除 MYSQL_***（models.py 优先级 MYSQL > GITHUB，
    留着会让应用继续连 RDS，切换形同虚设）。
  - RDS 实例本身不删除、不停机，随时可切回（回滚 = 再跑一次 --mode mysql）。

用法：
    python aliyun-backend/fc_switch_store.py --mode github   # 切到 GitHub 存储
    python aliyun-backend/fc_switch_store.py --mode mysql    # 切回 RDS 存储
    python aliyun-backend/fc_switch_store.py --show           # 只看当前 env

GitHub token 来源（优先级）：
    1) 环境变量 GITHUB_TOKEN
    2) 仓库根 .workbuddy/密钥与凭据备份.md 里的 gho_ token（本地开发用）
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from fc_client import (  # noqa: E402
    make_client,
    get_function_env,
    function_name,
    runtime,
)
from alibabacloud_fc20230330 import models as fc_models  # noqa: E402

GITHUB_REPO = os.environ.get("GITHUB_STORE_REPO", "yhstc1/customer-data")
GITHUB_DATA_PATH = os.environ.get("GITHUB_DATA_PATH", "data/customers.db")
# FC 上必须用**同步**模式（请求内写回）：wsgiref 单线程 + 实例空闲缩容回收，
# 后台线程往往等不到 debounce 就被杀掉 → 数据丢失。详见交接文档「坑 #5」。
GITHUB_SYNC_ASYNC = os.environ.get("GITHUB_SYNC_ASYNC", "0")
GITHUB_SYNC_DEBOUNCE = os.environ.get("GITHUB_SYNC_DEBOUNCE", "5")


def _gh_token():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if tok:
        return tok
    # 从密钥备份文件读取（仅本地开发机可用；FC 上靠环境变量）
    bak = os.path.join(ROOT, ".workbuddy", "密钥与凭据备份.md")
    if os.path.isfile(bak):
        import re
        with open(bak, "r", encoding="utf-8") as fh:
            m = re.search(r"(gho_[A-Za-z0-9]+)", fh.read())
        if m:
            return m.group(1)
    raise SystemExit("取不到 GITHUB_TOKEN：请设环境变量或检查 .workbuddy/密钥与凭据备份.md")


def get_env(client):
    return get_function_env(client)


def _check_rds_reachable(mysql_vars):
    """检查 RDS 实例是否真实可达。返回 (ok, detail)。

    RDS 实例 rm-bp1x01d9d8g8i844q 已于 2026-11-07 释放，此处用于防止把
    失效地址写进 FC env 导致应用整体不可用。
    """
    try:
        import pymysql
    except ImportError:
        return False, "本机未装 pymysql，无法校验 RDS 连通性"
    try:
        conn = pymysql.connect(
            host=mysql_vars.get("MYSQL_HOST"),
            port=int(mysql_vars.get("MYSQL_PORT", 3306)),
            user=mysql_vars.get("MYSQL_USER"),
            password=mysql_vars.get("MYSQL_PASSWORD"),
            database=mysql_vars.get("MYSQL_DB"),
            charset="utf8mb4",
            connect_timeout=10,
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM customers")
            n = cur.fetchone()[0]
            return True, "customers 表 %d 行" % n
        finally:
            conn.close()
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:200])


def put_env(client, env):
    body = fc_models.UpdateFunctionInput(environment_variables=env)
    req = fc_models.UpdateFunctionRequest(body=body)
    resp = client.update_function(function_name(), runtime())
    out = resp.body
    return out.to_map() if hasattr(out, "to_map") else out


def main():
    mode = None
    args = sys.argv[1:]
    if "--show" in args:
        mode = "show"
    elif "--mode" in args:
        i = args.index("--mode")
        mode = args[i + 1] if i + 1 < len(args) else None
    if mode not in ("show", "github", "mysql"):
        raise SystemExit("用法：python fc_switch_store.py [--show | --mode github|mysql]")

    client = make_client()
    env = get_env(client)

    if mode == "show":
        print("当前环境变量（%d 项）：" % len(env))
        for k in sorted(env):
            v = env[k]
            if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
                v = "***"
            print("  %-22s = %s" % (k, v))
        return

    # 合并：保留原有全部变量，只改存储相关项
    if mode == "github":
        for k in list(env):
            if k.startswith("MYSQL_"):
                env.pop(k)
        env["GITHUB_STORE_REPO"] = GITHUB_REPO
        env["GITHUB_TOKEN"] = _gh_token()
        env["GITHUB_DATA_PATH"] = GITHUB_DATA_PATH
        env["GITHUB_BRANCH"] = "main"
        env["GITHUB_SYNC_ASYNC"] = GITHUB_SYNC_ASYNC
        env["GITHUB_SYNC_DEBOUNCE"] = GITHUB_SYNC_DEBOUNCE
    else:  # mysql
        for k in ("GITHUB_STORE_REPO", "GITHUB_TOKEN", "GITHUB_DATA_PATH",
                  "GITHUB_BRANCH", "GITHUB_SYNC_ASYNC", "GITHUB_SYNC_DEBOUNCE"):
            env.pop(k, None)
        # 从本地 .env 恢复 MYSQL_*（.env 不入库，仅本机有）
        dotenv = os.path.join(HERE, ".env")
        mysql_vars = {}
        if os.path.isfile(dotenv):
            with open(dotenv, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k.startswith("MYSQL_"):
                        mysql_vars[k] = v
        else:
            print("[warn] 未找到 aliyun-backend/.env，MYSQL_* 变量可能不完整", flush=True)

        # ⚠️ RDS 实例已于 2026-11-07 释放。切回 mysql 前必须先确认实例真实存在且可连，
        # 否则会把失效地址写进 FC env → 应用既连不上 RDS 也读不到 GitHub → 全面挂掉。
        if mysql_vars.get("MYSQL_HOST"):
            ok, detail = _check_rds_reachable(mysql_vars)
            if not ok:
                print("=" * 62)
                print("❌ 拒绝切换：RDS 实例不可达")
                print("   %s" % detail)
                print()
                print("   RDS 实例 rm-bp1x01d9d8g8i844q 已于 2026-11-07 释放（省 ¥12.2/月）。")
                print("   要回滚到 MySQL 模式，必须先重建 RDS 实例并导入备份：")
                print("     本地备份   : backup_crm_20261107_034551.sql")
                print("     GitHub 私有仓: yhstc1/customer-data/backup/backup_crm_20261107_034551.sql")
                print("   重建后把新实例的连接信息写进 aliyun-backend/.env，再重跑本命令。")
                print("=" * 62)
                raise SystemExit(1)
            print("[ok] RDS 实例可连（%s），允许切换" % detail, flush=True)

        for k, v in mysql_vars.items():
            if k not in env:
                env[k] = v

    print("提交环境变量（%d 项）..." % len(env))
    put_env(client, env)

    print("=== 更新后 ===")
    for k in sorted(env):
        v = env[k]
        if any(s in k.upper() for s in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
            v = "***"
        print("  %-22s = %s" % (k, v))


if __name__ == "__main__":
    main()

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

from fc_creds import load_creds  # noqa: E402
from alibabacloud_fc20230330.client import Client as FCClient  # noqa: E402
from alibabacloud_fc20230330 import models as fc_models  # noqa: E402
from alibabacloud_tea_openapi import models as openapi_models  # noqa: E402
from alibabacloud_tea_util import models as util_models  # noqa: E402

CREDS = load_creds() or {}
AK_ID = os.environ.get("ALIYUN_AK_ID") or CREDS.get("ALIYUN_AK_ID", "")
AK_SECRET = os.environ.get("ALIYUN_AK_SECRET") or CREDS.get("ALIYUN_AK_SECRET", "")
REGION = os.environ.get("ALIYUN_REGION") or CREDS.get("ALIYUN_REGION", "cn-hangzhou")
ACCOUNT_ID = os.environ.get("ALIYUN_ACCOUNT_ID") or CREDS.get("ALIYUN_ACCOUNT_ID", "")
FUNCTION_NAME = os.environ.get("ALIYUN_FC_FUNCTION") or CREDS.get("ALIYUN_FC_FUNCTION", "crm-api-fc")

GITHUB_REPO = os.environ.get("GITHUB_STORE_REPO", "yhstc1/customer-data")
GITHUB_DATA_PATH = os.environ.get("GITHUB_DATA_PATH", "data/customers.db")


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


def make_client():
    endpoint = (
        "%s.%s.fc.aliyuncs.com" % (ACCOUNT_ID, REGION)
        if ACCOUNT_ID else "fc.%s.aliyuncs.com" % REGION
    )
    cfg = openapi_models.Config(
        access_key_id=AK_ID, access_key_secret=AK_SECRET,
        region_id=REGION, endpoint=endpoint,
    )
    return FCClient(cfg)


def get_env(client):
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
    runtime.read_timeout = 60
    runtime.connect_timeout = 30
    resp = client.get_function(FUNCTION_NAME, runtime)
    body = resp.body
    body = body.to_map() if hasattr(body, "to_map") else body
    return dict(body.get("environmentVariables") or {})


def put_env(client, env):
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
    runtime.read_timeout = 60
    runtime.connect_timeout = 30
    body = fc_models.UpdateFunctionInput(environment_variables=env)
    req = fc_models.UpdateFunctionRequest(body=body)
    resp = client.update_function(FUNCTION_NAME, req)
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
        env["GITHUB_SYNC_ASYNC"] = "1"
        env["GITHUB_SYNC_DEBOUNCE"] = "5"
    else:  # mysql
        for k in ("GITHUB_STORE_REPO", "GITHUB_TOKEN", "GITHUB_DATA_PATH",
                  "GITHUB_BRANCH", "GITHUB_SYNC_ASYNC", "GITHUB_SYNC_DEBOUNCE"):
            env.pop(k, None)
        # 从本地 .env 恢复 MYSQL_*（.env 不入库，仅本机有）
        dotenv = os.path.join(HERE, ".env")
        if os.path.isfile(dotenv):
            with open(dotenv, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k.startswith("MYSQL_") and k not in env:
                        env[k] = v
        else:
            print("[warn] 未找到 aliyun-backend/.env，MYSQL_* 变量可能不完整", flush=True)

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

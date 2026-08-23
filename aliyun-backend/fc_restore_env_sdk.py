# -*- coding: utf-8 -*-
"""恢复 FC 函数完整环境变量（含本次更新的钉钉凭证）。"""
import sys
from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_tea_openapi import models as openapi_models
from alibabacloud_tea_util import models as util_models

# 阿里云 AccessKey 从环境变量读取，禁止硬编码到仓库（会被 GitHub 推送保护拦截）
AK_ID = os.environ.get("ALIYUN_AK_ID", "")
AK_SECRET = os.environ.get("ALIYUN_AK_SECRET", "")
REGION = os.environ.get("ALIYUN_REGION", "cn-hangzhou")
ACCOUNT_ID = os.environ.get("ALIYUN_ACCOUNT_ID", "")
FUNCTION_NAME = os.environ.get("ALIYUN_FC_FUNCTION", "crm-api-fc")


def load_env_vars():
    """从同目录 .env 读取需要恢复到 FC 的全部环境变量（不硬编码任何密钥到仓库）。"""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env_vars = {}
    if not os.path.exists(env_path):
        print("ERROR: 同目录未找到 .env，无法恢复环境变量")
        sys.exit(1)
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k:
                env_vars[k] = v
    # 必须包含 FC 运行所需的最小集合，缺失则提示
    required = ["DING_APP_KEY", "DING_APP_SECRET", "JWT_SECRET",
                "MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB"]
    missing = [k for k in required if k not in env_vars]
    if missing:
        print("ERROR: .env 缺少恢复 FC 所需的变量:", missing)
        sys.exit(1)
    return env_vars


def make_client():
    cfg = openapi_models.Config(
        access_key_id=AK_ID,
        access_key_secret=AK_SECRET,
        region_id=REGION,
        endpoint=f"{ACCOUNT_ID}.{REGION}.fc.aliyuncs.com",
    )
    return FCClient(cfg)


def update_env(client, env_vars):
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
    body = fc_models.UpdateFunctionInput(
        environment_variables=env_vars
    )
    req = fc_models.UpdateFunctionRequest(body=body)
    try:
        resp = client.update_function(FUNCTION_NAME, req)
        return resp.body
    except Exception as e:
        return {"error": str(e)}


def main():
    print("=== RestoreFunctionEnv ===")
    client = make_client()
    env_vars = load_env_vars()
    r = update_env(client, env_vars)
    print(r)


if __name__ == "__main__":
    main()

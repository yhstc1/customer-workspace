# -*- coding: utf-8 -*-
"""使用阿里云官方 FC 20230330 SDK 更新函数环境变量（不动代码）。"""
import sys
import os
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
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    env_vars[k] = v

    keys = ["DING_APP_KEY", "DING_APP_SECRET"]
    filtered = {k: env_vars[k] for k in keys if k in env_vars}
    if not filtered:
        print("ERROR: .env 中未找到 DING_APP_KEY/DING_APP_SECRET")
        sys.exit(1)
    print("=== UpdateFunctionEnv ===")
    print("updating:", filtered)
    client = make_client()
    r = update_env(client, filtered)
    print(r)


if __name__ == "__main__":
    main()

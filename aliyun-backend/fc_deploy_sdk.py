# -*- coding: utf-8 -*-
"""使用阿里云官方 FC 20230330 SDK 更新函数代码与配置。"""
import os
import sys
from alibabacloud_fc20230330.client import Client as FCClient
from alibabacloud_fc20230330 import models as fc_models
from alibabacloud_tea_openapi import models as openapi_models
from alibabacloud_tea_util import models as util_models

# 凭证来源优先级：环境变量 > 本地加密存储(fc_creds.py)
# 禁止硬编码到仓库（会被 GitHub 推送保护拦截）。
try:
    from fc_creds import load_creds
    _CREDS = load_creds() or {}
except Exception:
    _CREDS = {}


def _get(key, default=""):
    # 环境变量优先（便于临时覆盖），其次本地加密存储
    return os.environ.get(key) or _CREDS.get(key, default)


AK_ID = _get("ALIYUN_AK_ID", "")
AK_SECRET = _get("ALIYUN_AK_SECRET", "")
REGION = _get("ALIYUN_REGION", "cn-hangzhou")
ACCOUNT_ID = _get("ALIYUN_ACCOUNT_ID", "")
FUNCTION_NAME = _get("ALIYUN_FC_FUNCTION", "crm-api-fc")
ZIP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm-api-custom-runtime-v2.zip")


def make_client():
    # 优先用通配 endpoint（fc.<region>.aliyuncs.com），无需 ALIYUN_ACCOUNT_ID。
    # 若设了 ALIYUN_ACCOUNT_ID 则用 account-scoped endpoint（与控制台/CLI 默认一致）。
    endpoint = (
        f"{ACCOUNT_ID}.{REGION}.fc.aliyuncs.com"
        if ACCOUNT_ID else f"fc.{REGION}.aliyuncs.com"
    )
    cfg = openapi_models.Config(
        access_key_id=AK_ID,
        access_key_secret=AK_SECRET,
        region_id=REGION,
        endpoint=endpoint,
    )
    return FCClient(cfg)


def get_function(client):
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
    runtime.read_timeout = 60
    runtime.connect_timeout = 30
    try:
        resp = client.get_function(FUNCTION_NAME, runtime)
        return resp.body
    except Exception as e:
        return {"error": str(e)}


def update_code(client):
    import base64
    with open(ZIP_PATH, "rb") as f:
        zip_bytes = f.read()
    zip_b64 = base64.b64encode(zip_bytes).decode("ascii")
    code_location = fc_models.InputCodeLocation(zip_file=zip_b64)
    body = fc_models.UpdateFunctionInput(code=code_location)
    req = fc_models.UpdateFunctionRequest(body=body)
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
    # 上传代码包可能较慢（尤其手机热点），拉长超时并自动重试，避免 The write operation timed out
    runtime.read_timeout = 300
    runtime.connect_timeout = 60
    runtime.autoretry = True
    runtime.max_attempts = 3
    try:
        resp = client.update_function(FUNCTION_NAME, req)
        return resp.body
    except Exception as e:
        return {"error": str(e)}


def main():
    client = make_client()
    action = sys.argv[1] if len(sys.argv) > 1 else "get"

    if action == "get":
        print("=== GetFunction ===")
        r = get_function(client)
        print(r)
    elif action == "update":
        print("=== UpdateFunctionCode ===")
        r = update_code(client)
        print(r)
        print("\n=== re-GetFunction to confirm ===")
        import time
        time.sleep(3)
        print(get_function(client))
    else:
        print("usage: python fc_deploy_sdk.py [get|update]")


if __name__ == "__main__":
    main()

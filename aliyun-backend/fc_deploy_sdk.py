# -*- coding: utf-8 -*-
"""使用阿里云官方 FC 20230330 SDK 更新函数代码与配置。"""
import os
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
ZIP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crm-api-custom-runtime-v2.zip")


def make_client():
    cfg = openapi_models.Config(
        access_key_id=AK_ID,
        access_key_secret=AK_SECRET,
        region_id=REGION,
        endpoint=f"{ACCOUNT_ID}.{REGION}.fc.aliyuncs.com",
    )
    return FCClient(cfg)


def get_function(client):
    runtime = util_models.RuntimeOptions()
    runtime.qualifier = "LATEST"
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

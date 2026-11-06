# -*- coding: utf-8 -*-
"""使用阿里云官方 FC 20230330 SDK 更新函数代码与配置。

凭证、AccountId、endpoint 统一由 fc_client 提供：
  - 缺 AccountId 时自动通过 STS GetCallerIdentity 探测并回填；
  - 必须用 account-scoped endpoint（<AccountId>.<region>.fc.aliyuncs.com），
    通配 endpoint 会被 SDK 判为 InvalidVersion。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fc_client import make_client, function_name, runtime  # noqa: E402
from alibabacloud_fc20230330 import models as fc_models  # noqa: E402

ZIP_PATH = os.path.join(HERE, "crm-api-custom-runtime-v2.zip")


def get_function(client):
    try:
        resp = client.get_function(function_name(), runtime())
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
    # 上传代码包可能较慢（尤其手机热点），拉长超时并自动重试，避免 The write operation timed out
    rt = runtime(read_timeout=300, connect_timeout=60)
    rt.autoretry = True
    rt.max_attempts = 3
    try:
        resp = client.update_function(function_name(), req)
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

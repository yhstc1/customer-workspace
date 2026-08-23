# -*- coding: utf-8 -*-
"""用 FC 2023-03-30 REST API 签名更新函数环境变量（复用 fc_update_rest.py 签名方案）。"""
import base64
import hashlib
import hmac
import json
import datetime
import os
import sys

# 阿里云 AccessKey 从环境变量读取，禁止硬编码到仓库（会被 GitHub 推送保护拦截）
AK_ID = os.environ.get("ALIYUN_AK_ID", "")
AK_SECRET = os.environ.get("ALIYUN_AK_SECRET", "")
REGION = os.environ.get("ALIYUN_REGION", "cn-hangzhou")
ACCOUNT_ID = os.environ.get("ALIYUN_ACCOUNT_ID", "")
FUNCTION_NAME = os.environ.get("ALIYUN_FC_FUNCTION", "crm-api-fc")
HOST = f"{ACCOUNT_ID}.{REGION}.fc.aliyuncs.com"


def sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def get_signature_key(key, date_stamp, region, service):
    k_date = sign(key.encode("utf-8"), date_stamp)
    k_region = sign(k_date, region)
    k_service = sign(k_region, service)
    k_signing = sign(k_service, "fc_request")
    return k_signing


def main():
    # 从本地 .env 读取钉钉凭证
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

    keys_to_update = ["DING_APP_KEY", "DING_APP_SECRET"]
    filtered = {k: env_vars[k] for k in keys_to_update if k in env_vars}
    if not filtered:
        print("ERROR: .env 中未找到 DING_APP_KEY/DING_APP_SECRET")
        sys.exit(1)
    print("updating env:", filtered)

    body = json.dumps({"environmentVariables": filtered}).encode("utf-8")
    path = f"/2023-03-30/functions/{FUNCTION_NAME}"

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y%m%d")

    service = "fc"
    content_type = "application/json"
    canonical_headers = (
        f"host:{HOST}\n"
        f"x-acs-date:{amz_date}\n"
        f"x-acs-version:2023-03-30\n"
        f"x-fc-date:{amz_date}\n"
    )
    signed_headers = "host;x-acs-date;x-acs-version;x-fc-date"
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_request = "\n".join([
        "PUT", path, "", canonical_headers, signed_headers, payload_hash,
    ])
    algorithm = "ACS4-HMAC-SHA256"
    credential_scope = f"{date_str}/{REGION}/{service}/fc_request"
    string_to_sign = "\n".join([
        algorithm, amz_date, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    signing_key = get_signature_key(AK_SECRET, date_str, REGION, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"{algorithm} Credential={AK_ID}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    import requests
    headers = {
        "Host": HOST,
        "Content-Type": content_type,
        "X-Acs-Date": amz_date,
        "X-Acs-Version": "2023-03-30",
        "X-Fc-Date": amz_date,
        "Authorization": authorization,
    }
    url = f"https://{HOST}{path}"
    r = requests.put(url, headers=headers, data=body, timeout=60)
    print(r.status_code, r.text[:2000])


if __name__ == "__main__":
    main()

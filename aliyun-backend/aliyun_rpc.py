# -*- coding: utf-8 -*-
"""阿里云 RPC 风格 OpenAPI 通用调用器（不需要装对应 SDK）。

背景：部分环境无法访问 PyPI 装 `alibabacloud_*` SDK，但账号里能直接调的
产品（BssOpenApi 账单、RDS 实例属性等）都是老的 RPC 签名风格
（HMAC-SHA1 + SignatureVersion 1.0），用标准库就能实现。

用法：
    python aliyun-backend/aliyun_rpc.py BssOpenApi 2017-07-01 GetAccountBalance
    python aliyun-backend/aliyun_rpc.py BssOpenApi 2017-07-01 QueryBillOverview BillingCycle=2026-11
    python aliyun-backend/aliyun_rpc.py Rds 2014-08-15 DescribeDBInstanceAttribute DBInstanceId=rm-xxxx

签名算法（阿里云 RPC v1）：
    1. 公共参数 + 业务参数，全部 RFC3986 百分号编码
    2. 按 key 字典序拼成 canonicalizedQueryString
    3. stringToSign = "GET&" + encode("/" + canonicalizedQueryString)
    4. Signature = base64(HMAC-SHA1(ak_secret + "&", stringToSign))
    5. 最终 query = 排序后的参数（不含 Signature）+ "&Signature=" + encode(signature)
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fc_creds import load_creds  # noqa: E402

# 产品 code -> 公开 endpoint（老 RPC 风格基本都是全局域名）
ENDPOINTS = {
    "BssOpenApi": "bssopenapi.aliyuncs.com",
    "billing": "billing.aliyuncs.com",
    "Rds": "rds.aliyuncs.com",
    "Ecs": "ecs.aliyuncs.com",
    "Fc": "fc.aliyuncs.com",
    "Sts": "sts.aliyuncs.com",
}


def _percent_encode(s: str) -> str:
    """RFC3986 编码：保留 A-Za-z0-9-._~，其余 %XX（UTF-8 字节）。"""
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    out = []
    for b in s.encode("utf-8"):
        ch = chr(b)
        out.append(ch if ch in safe else "%%%02X" % b)
    return "".join(out)


def _sign(ak_secret: str, string_to_sign: str) -> str:
    digest = hmac.new(
        (ak_secret + "&").encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def call(product: str, version: str, action: str, params: dict = None, endpoint: str = None):
    """发起一次 RPC 调用，返回解析后的 JSON dict。"""
    creds = load_creds() or {}
    ak_id = os.environ.get("ALIYUN_AK_ID") or creds.get("ALIYUN_AK_ID", "")
    ak_secret = os.environ.get("ALIYUN_AK_SECRET") or creds.get("ALIYUN_AK_SECRET", "")
    if not (ak_id and ak_secret):
        raise SystemExit("缺少 ALIYUN_AK_ID / ALIYUN_AK_SECRET")

    host = endpoint or ENDPOINTS.get(product, "%s.aliyuncs.com" % product.lower())
    args = {
        "AccessKeyId": ak_id,
        "Action": action,
        "Format": "JSON",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": uuid.uuid4().hex,
        "SignatureVersion": "1.0",
        "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "Version": version,
    }
    args.update({k: v for k, v in (params or {}).items() if v is not None})

    canonical = "&".join(
        "%s=%s" % (_percent_encode(k), _percent_encode(str(v)))
        for k, v in sorted(args.items())
    )
    string_to_sign = "GET&%s&%s" % (
        _percent_encode("/"),
        _percent_encode(canonical),
    )
    signature = _sign(ak_secret, string_to_sign)
    query = "%s&Signature=%s" % (canonical, _percent_encode(signature))

    import requests

    url = "https://%s/?%s" % (host, query)
    r = requests.get(url, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"_http_status": r.status_code, "_raw": r.text[:2000]}


def main():
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法：python aliyun-backend/aliyun_rpc.py <Product> <Version> <Action> [Key=Value ...]"
        )
    product, version, action = sys.argv[1], sys.argv[2], sys.argv[3]
    params = {}
    for kv in sys.argv[4:]:
        if "=" in kv:
            k, _, v = kv.partition("=")
            params[k] = v
    out = call(product, version, action, params)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

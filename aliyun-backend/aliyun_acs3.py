# -*- coding: utf-8 -*-
"""阿里云 OpenAPI 3.0（ACS3-HMAC-SHA256）签名调用器。

与 `aliyun_rpc.py`（老 RPC v1 签名）互补：
  - BssOpenApi（账单/余额）等新产品只认 ACS3 签名，
    用老签名会被判 "Specified parameter Version is not valid"。
  - ACS3 与 FC 的签名基本一致，差别有三处：
      1. signing key 的收尾串是 "aliyun_v4"（不是 "fc_request"）
      2. 签名串固定 4 行：算法 / 时间 / credential_scope / canonical_request 的 sha256
      3. 参数走 query string 时进 canonical_request 的 query 部分（需按 key 排序 percent 编码）

用法：
    python aliyun-backend/aliyun_acs3.py bssopenapi.aliyuncs.com 2017-07-01 GetAccountBalance
    python aliyun-backend/aliyun_acs3.py bssopenapi.aliyuncs.com 2017-07-01 QueryBillOverview BillingCycle=2026-11
"""
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from fc_creds import load_creds  # noqa: E402

ALGORITHM = "ACS3-HMAC-SHA256"
SAFE = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"


def _pe(s: str) -> str:
    out = []
    for b in str(s).encode("utf-8"):
        ch = chr(b)
        out.append(ch if ch in SAFE else "%%%02X" % b)
    return "".join(out)


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def call(host: str, version: str, action: str, params: dict = None, region: str = "cn-hangzhou"):
    creds = load_creds() or {}
    ak_id = os.environ.get("ALIYUN_AK_ID") or creds.get("ALIYUN_AK_ID", "")
    ak_secret = os.environ.get("ALIYUN_AK_SECRET") or creds.get("ALIYUN_AK_SECRET", "")
    if not (ak_id and ak_secret):
        raise SystemExit("缺少 ALIYUN_AK_ID / ALIYUN_AK_SECRET")

    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = now.strftime("%Y%m%d")

    args = {k: str(v) for k, v in (params or {}).items() if v is not None}
    canonical_query = "&".join(
        "%s=%s" % (_pe(k), _pe(args[k])) for k in sorted(args)
    )
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_headers = "host:%s\nx-acs-action:%s\nx-acs-date:%s\nx-acs-version:%s\n" % (
        host,
        action,
        amz_date,
        version,
    )
    signed_headers = "host;x-acs-action;x-acs-date;x-acs-version"

    canonical_request = "\n".join(
        ["GET", "/", canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    credential_scope = "%s/%s/bssopenapi/acs_request" % (date_str, region)
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    k_date = _hmac(ak_secret.encode("utf-8"), date_str)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, "bssopenapi")
    k_signing = _hmac(k_service, "aliyun_v4")
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s"
        % (ALGORITHM, ak_id, credential_scope, signed_headers, signature)
    )

    import requests

    url = "https://%s/" % host
    if canonical_query:
        url += "?" + canonical_query
    headers = {
        "Host": host,
        "x-acs-action": action,
        "x-acs-date": amz_date,
        "x-acs-version": version,
        "Authorization": authorization,
    }
    r = requests.get(url, headers=headers, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"_http_status": r.status_code, "_raw": r.text[:2000]}


def main():
    if len(sys.argv) < 4:
        raise SystemExit(
            "用法：python aliyun-backend/aliyun_acs3.py <host> <version> <action> [Key=Value ...]"
        )
    host, version, action = sys.argv[1], sys.argv[2], sys.argv[3]
    params = {}
    for kv in sys.argv[4:]:
        if "=" in kv:
            k, _, v = kv.partition("=")
            params[k] = v
    print(json.dumps(call(host, version, action, params), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

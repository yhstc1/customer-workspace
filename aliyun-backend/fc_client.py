# -*- coding: utf-8 -*-
"""阿里云 FC 客户端构造：统一处理凭证、AccountId 与 endpoint。

为什么需要这个模块
------------------
1) **通配 endpoint 会报 InvalidVersion**
   alibabacloud_fc20230330 对 `fc.<region>.aliyuncs.com`（通配）会返回
   `400 InvalidVersion: Specified parameter Version is not valid`，
   必须改用 account-scoped endpoint：`<AccountId>.<region>.fc.aliyuncs.com`。

2) **AccountId 容易丢**
   本地加密凭证（~/.workbuddy/.fc_creds.enc）里若没有 `ALIYUN_ACCOUNT_ID`
   （换机、漏录、从 AccessKey.csv 临时恢复等场景），通配 endpoint 又不可用，
   于是所有 FC 脚本全线报错。本模块在缺失时通过 STS `GetCallerIdentity`
   自动探测 AccountId，并回填到本地加密凭证，下次无需再探。

用法：
    from fc_client import make_client, get_function_env
    client = make_client()
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fc_creds import load_creds, save_creds  # noqa: E402
from alibabacloud_fc20230330.client import Client as FCClient  # noqa: E402
from alibabacloud_tea_openapi import models as openapi_models  # noqa: E402
from alibabacloud_tea_util import models as util_models  # noqa: E402


def _creds() -> dict:
    c = load_creds() or {}
    return c


def _get(key: str, default: str = "") -> str:
    """环境变量优先，其次本地加密凭证。"""
    v = os.environ.get(key)
    if v:
        return v.strip()
    return (_creds().get(key) or default).strip()


def discover_account_id(ak_id: str, ak_secret: str, region: str) -> str:
    """通过 STS GetCallerIdentity 探测账号 ID。失败返回空串。"""
    if not (ak_id and ak_secret):
        return ""
    try:
        from alibabacloud_sts20150401.client import Client as STSClient

        cfg = openapi_models.Config(
            access_key_id=ak_id,
            access_key_secret=ak_secret,
            region_id=region or "cn-hangzhou",
        )
        resp = STSClient(cfg).get_caller_identity()
        body = resp.body.to_map() if hasattr(resp.body, "to_map") else resp.body
        return str(body.get("AccountId") or "")
    except Exception as e:
        print("[fc_client] STS 探测 AccountId 失败: %s" % e, flush=True)
        return ""


def account_id() -> str:
    """返回阿里云账号 ID；缺失时自动探测并回填本地加密凭证。"""
    aid = _get("ALIYUN_ACCOUNT_ID")
    if aid:
        return aid
    aid = discover_account_id(
        _get("ALIYUN_AK_ID"), _get("ALIYUN_AK_SECRET"), _get("ALIYUN_REGION", "cn-hangzhou")
    )
    if aid:
        c = _creds()
        if c.get("ALIYUN_ACCOUNT_ID") != aid:
            c["ALIYUN_ACCOUNT_ID"] = aid
            try:
                save_creds(c)
                print("[fc_client] 已回填 ALIYUN_ACCOUNT_ID=%s 到本地加密凭证" % aid, flush=True)
            except Exception as e:
                print("[fc_client] 回填凭证失败（不影响本次调用）: %s" % e, flush=True)
    return aid


def region() -> str:
    return _get("ALIYUN_REGION", "cn-hangzhou")


def function_name() -> str:
    return _get("ALIYUN_FC_FUNCTION", "crm-api-fc")


def endpoint() -> str:
    """account-scoped endpoint（通配 endpoint 在 FC 20230330 SDK 下不可用）。"""
    aid = account_id()
    if not aid:
        raise SystemExit(
            "无法确定阿里云账号 ID：请设环境变量 ALIYUN_ACCOUNT_ID，"
            "或执行 `python aliyun-backend/fc_creds.py set --account <AccountId>`"
        )
    return "%s.%s.fc.aliyuncs.com" % (aid, region())


def make_client() -> FCClient:
    ak_id = _get("ALIYUN_AK_ID")
    ak_secret = _get("ALIYUN_AK_SECRET")
    if not (ak_id and ak_secret):
        raise SystemExit(
            "缺少阿里云 AK：请设环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET，"
            "或执行 `python aliyun-backend/fc_creds.py set`"
        )
    cfg = openapi_models.Config(
        access_key_id=ak_id,
        access_key_secret=ak_secret,
        region_id=region(),
        endpoint=endpoint(),
    )
    return FCClient(cfg)


def runtime(read_timeout: int = 60, connect_timeout: int = 30) -> "util_models.RuntimeOptions":
    rt = util_models.RuntimeOptions()
    rt.qualifier = "LATEST"
    rt.read_timeout = read_timeout
    rt.connect_timeout = connect_timeout
    return rt


def get_function_env(client) -> dict:
    """读取函数当前的全量环境变量（已转成普通 dict）。"""
    resp = client.get_function(function_name(), runtime())
    body = resp.body
    body = body.to_map() if hasattr(body, "to_map") else body
    return dict(body.get("environmentVariables") or {})


if __name__ == "__main__":
    print("AccountId :", account_id() or "(探测失败)")
    print("Region    :", region())
    print("Function  :", function_name())
    print("Endpoint  :", endpoint())

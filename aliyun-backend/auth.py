# -*- coding: utf-8 -*-
"""钉钉免登 + JWT 鉴权。

流程：小程序 dd.requestAuthCode -> 后端用 authCode 换钉钉 userId
      -> 查 users.dingtalk_user_id 映射本地 user_id -> 签发 JWT。
FC 无状态，用 JWT 替代原 Flask session 维持登录态。
"""
import time
import json
import base64
import hmac
import hashlib
import requests
import config

_app_token_cache = {"token": None, "exp": 0}


def get_app_token():
    """获取企业内部应用 access_token（带简单缓存，避免频繁调用）。"""
    now = time.time()
    if _app_token_cache["token"] and _app_token_cache["exp"] > now + 60:
        return _app_token_cache["token"]
    r = requests.get("https://oapi.dingtalk.com/gettoken",
                     params={"appkey": config.DING_APP_KEY, "appsecret": config.DING_APP_SECRET},
                     timeout=10)
    d = r.json()
    if d.get("errcode") != 0:
        raise RuntimeError("gettoken failed: %s" % d)
    _app_token_cache["token"] = d["access_token"]
    _app_token_cache["exp"] = now + int(d.get("expires_in", 7200))
    return d["access_token"]


def get_userid_by_code(auth_code):
    """用免登 authCode 换钉钉 userId（新版 topapi/v2/user/getuserinfo）。"""
    token = get_app_token()
    r = requests.post("https://oapi.dingtalk.com/topapi/v2/user/getuserinfo",
                      params={"access_token": token}, json={"code": auth_code}, timeout=10)
    d = r.json()
    if d.get("errcode") != 0:
        # 兼容老接口 user/getuserinfo
        r2 = requests.get("https://oapi.dingtalk.com/user/getuserinfo",
                          params={"access_token": token, "code": auth_code}, timeout=10)
        d2 = r2.json()
        if d2.get("errcode") != 0:
            raise RuntimeError("getuserinfo failed: %s / %s" % (d, d2))
        return d2.get("userid")
    return d.get("result", {}).get("userid")


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s):
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_jwt(user_id, is_admin=False):
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"uid": user_id, "adm": bool(is_admin), "exp": int(time.time()) + config.JWT_EXPIRE_HOURS * 3600}
    h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing = "%s.%s" % (h, p)
    sig = hmac.new(config.JWT_SECRET.encode("utf-8"), signing.encode("utf-8"), hashlib.sha256).digest()
    return "%s.%s" % (signing, _b64url(sig))


def parse_jwt(token):
    try:
        h, p, s = token.split(".")
        signing = "%s.%s" % (h, p)
        expected = _b64url(hmac.new(config.JWT_SECRET.encode("utf-8"), signing.encode("utf-8"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, s):
            return None
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


def dingtalk_userid_to_local(ding_userid):
    """钉钉 userId -> 本地 users.id；未绑定返回 None。"""
    import db
    row = db.query("SELECT id, is_admin FROM users WHERE dingtalk_user_id=?", (ding_userid,), one=True)
    return row

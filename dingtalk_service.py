"""
钉钉服务模块
- 免登授权：钉钉内打开应用时，通过 authCode 获取用户身份，自动登录
- 消息推送：将每日报告等通知推送到钉钉
- 通讯录同步：从钉钉拉取组织架构（未来团队扩展用）
"""
import time
import requests
import json
from dingtalk_config import (
    DINGTALK_APP_KEY, DINGTALK_APP_SECRET, DINGTALK_CORP_ID,
    DINGTALK_GET_TOKEN_URL, DINGTALK_GET_USER_URL,
    DINGTALK_USER_ACCESS_TOKEN_URL, DINGTALK_CONTACT_ME_URL,
    APP_BASE_URL, is_configured
)


# ==================== Access Token 管理 ====================

_access_token_cache = {"token": None, "expires": 0}


def get_access_token():
    """
    获取钉钉企业 access_token（带缓存，有效期 7200 秒）
    返回: token 字符串 或 None
    """
    if not is_configured():
        return None

    # 检查缓存
    now = time.time()
    if _access_token_cache["token"] and now < _access_token_cache["expires"]:
        return _access_token_cache["token"]

    try:
        resp = requests.get(DINGTALK_GET_TOKEN_URL, params={
            "appkey": DINGTALK_APP_KEY,
            "appsecret": DINGTALK_APP_SECRET
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("errcode") == 0:
            _access_token_cache["token"] = data["access_token"]
            _access_token_cache["expires"] = now + data.get("expires_in", 7200) - 300  # 提前5分钟刷新
            return data["access_token"]
        else:
            print(f"[钉钉] 获取 token 失败: {data}")
            return None
    except Exception as e:
        print(f"[钉钉] 获取 token 异常: {e}")
        return None


# ==================== 免登授权 ====================

def get_user_by_authcode(auth_code):
    """
    通过免登授权码获取用户信息
    钉钉客户端打开应用时，前端 JS 会获取一个 authCode，
    用这个 code 向钉钉服务端换取用户身份。

    参数: auth_code - 前端传来的免登授权码
    返回: {"userid": "...", "name": "...", "unionid": "..."} 或 None
    """
    token = get_access_token()
    if not token:
        return None

    try:
        resp = requests.post(
            DINGTALK_GET_USER_URL,
            params={"access_token": token},
            json={"code": auth_code},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("errcode") == 0:
            result = data.get("result", {})
            return {
                "userid": result.get("userid"),
                "unionid": result.get("unionid"),
                "device_id": result.get("device_id"),
                # 需要额外调用接口获取姓名（简化处理）
                "name": result.get("userid", ""),  # 先用 userid，后面可扩展获取真实姓名
            }
        else:
            print(f"[钉钉] 获取用户失败: {data}")
            return None
    except Exception as e:
        print(f"[钉钉] 获取用户异常: {e}")
        return None


# ==================== 新版扫码登录（OAuth2）====================

def get_login_user_by_oauth2(auth_code):
    """
    新版钉钉扫码登录：用授权码 authCode 换取登录用户信息。

    流程（钉钉开放平台 2021+ OAuth2）：
      1. authCode -> 用户级 accessToken（userAccessToken）
      2. accessToken -> /contact/users/me 拿当前登录用户信息

    参数: auth_code - 前端扫码授权成功后回调带回的 authCode
    返回: {"name","nick","openid","unionid","mobile","avatar","email"} 或 None
    """
    if not is_configured():
        return None

    try:
        # 第 1 步：authCode 换 userAccessToken
        token_resp = requests.post(
            DINGTALK_USER_ACCESS_TOKEN_URL,
            json={
                "clientId": DINGTALK_APP_KEY,
                "clientSecret": DINGTALK_APP_SECRET,
                "code": auth_code,
                "grantType": "authorization_code",
            },
            timeout=10,
        )
        token_data = token_resp.json()
        user_token = token_data.get("accessToken")
        if not user_token:
            print(f"[钉钉] 换取 userAccessToken 失败: {token_data}")
            return None

        # 第 2 步：拿当前登录用户信息
        me_resp = requests.get(
            DINGTALK_CONTACT_ME_URL,
            headers={"x-acs-dingtalk-access-token": user_token},
            timeout=10,
        )
        me = me_resp.json()
        if not me.get("openId") and not me.get("unionId"):
            print(f"[钉钉] 获取登录用户信息失败: {me}")
            return None

        return {
            "name": me.get("nick", ""),
            "nick": me.get("nick", ""),
            "openid": me.get("openId", ""),
            "unionid": me.get("unionId", ""),
            "mobile": me.get("mobile", ""),
            "avatar": me.get("avatarUrl", ""),
            "email": me.get("email", ""),
        }
    except Exception as e:
        print(f"[钉钉] 扫码登录异常: {e}")
        return None


# ==================== 消息推送 ====================

def send_work_notification(user_id, title, content, url=None):
    """
    发送工作通知（推送到钉钉客户端）

    参数:
        user_id: 钉钉用户 ID
        title: 通知标题
        content: 通知内容
        url: 点击通知后跳转的链接（如报告地址）
    返回: True/False
    """
    token = get_access_token()
    if not token:
        return False

    try:
        msg = {
            "msgtype": "action_card",
            "action_card": {
                "title": title,
                "markdown": f"# {title}\n\n{content}",
                "single_title": "查看详情",
                "single_url": url or APP_BASE_URL,
            }
        }

        resp = requests.post(
            "https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2",
            params={"access_token": token},
            json={
                "agent_id": _get_agent_id(),
                "userid_list": user_id,
                "msg": msg
            },
            timeout=10
        )
        data = resp.json()
        if data.get("errcode") == 0:
            print(f"[钉钉] 消息已推送给 {user_id}")
            return True
        else:
            print(f"[钉钉] 推送失败: {data}")
            return False
    except Exception as e:
        print(f"[钉钉] 推送异常: {e}")
        return False


def _get_agent_id():
    """获取 Agent ID（从环境变量）"""
    import os
    return os.environ.get("DINGTALK_AGENT_ID", "")


# ==================== 测试连接 ====================

def test_connection():
    """测试钉钉配置是否正确"""
    if not is_configured():
        return {"ok": False, "message": "钉钉未配置，请先填写 AppKey 和 AppSecret"}

    token = get_access_token()
    if token:
        return {"ok": True, "message": "钉钉连接成功！access_token 已获取"}
    else:
        return {"ok": False, "message": "钉钉连接失败，请检查 AppKey/AppSecret 是否正确"}

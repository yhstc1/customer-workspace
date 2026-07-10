"""
钉钉微应用配置

═══════════════════════════════════════════════════════════════
本地部署 + 钉钉扫码登录 配置步骤
═══════════════════════════════════════════════════════════════
  1. 访问钉钉开放平台 https://open-dev.dingtalk.com
     应用开发 → 企业内部应用 → 创建应用（H5 微应用）
  2. 进入应用详情，拿到 AppKey 和 AppSecret，填到下方
     DINGTALK_APP_KEY / DINGTALK_APP_SECRET（或用环境变量）
  3. 「安全设置」→「登录 / 重定向 URL（回调域名）」里，
     添加本地回调地址：
        http://localhost:5000/api/dingtalk/oauth/callback
  4. 「权限管理」开通 personnel（个人信息）相关权限，scope 用 openid
  5. 保存后，双击「启动.bat」，浏览器打开 http://localhost:5000
     会自动跳到扫码登录页，用钉钉 App 扫码即可登录。

注意: AppSecret 是敏感信息，正式环境请用环境变量管理，不要提交到仓库。
═══════════════════════════════════════════════════════════════
"""
import os


# ==================== 钉钉应用配置 ====================
# 从环境变量读取，没有则用下方默认值（本地部署可直接把凭证填在引号里）

DINGTALK_APP_KEY = os.environ.get("DINGTALK_APP_KEY", "")
DINGTALK_APP_SECRET = os.environ.get("DINGTALK_APP_SECRET", "")

# 应用访问地址（本地部署保持 localhost 即可）
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000")

# 扫码登录回调地址：钉钉扫码授权成功后前端会带 authCode 跳到这里。
# ⚠️ 必须与钉钉开放平台「重定向 URL」里填的完全一致。
DINGTALK_LOGIN_REDIRECT = os.environ.get(
    "DINGTALK_LOGIN_REDIRECT",
    APP_BASE_URL.rstrip("/") + "/api/dingtalk/oauth/callback"
)

# ==================== 钉钉 API 端点 ====================
# —— 新版扫码登录（OAuth2，推荐）——
DINGTALK_OAUTH2_AUTH_URL = "https://login.dingtalk.com/oauth2/auth"          # 授权页（PC 显示二维码）
DINGTALK_USER_ACCESS_TOKEN_URL = "https://api.dingtalk.com/v1.0/oauth2/userAccessToken"  # authCode 换 accessToken
DINGTALK_CONTACT_ME_URL = "https://api.dingtalk.com/v1.0/contact/users/me"   # 拿登录用户信息

# —— 旧版免登 / 消息推送（保留）——
DINGTALK_GET_TOKEN_URL = "https://oapi.dingtalk.com/gettoken"
DINGTALK_GET_USER_URL = "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo"

# 企业 CorpId（从钉钉管理后台获取，扫码登录非必需）
DINGTALK_CORP_ID = os.environ.get("DINGTALK_CORP_ID", "")


def is_configured():
    """检查钉钉是否已配置"""
    return bool(DINGTALK_APP_KEY and DINGTALK_APP_SECRET)


def get_config_info():
    """获取当前配置状态（脱敏）"""
    return {
        "configured": is_configured(),
        "app_key": DINGTALK_APP_KEY[:6] + "***" if DINGTALK_APP_KEY else "未配置",
        "corp_id": DINGTALK_CORP_ID[:6] + "***" if DINGTALK_CORP_ID else "未配置",
        "base_url": APP_BASE_URL,
        "login_redirect": DINGTALK_LOGIN_REDIRECT,
    }

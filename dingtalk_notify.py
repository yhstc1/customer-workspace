# 钉钉群机器人推送模块（Webhook + 加签）
#
# 设计要点：
# - 通过「群机器人 Webhook」把提醒发到钉钉群（区别于单聊/应用推送）。
# - 安全方式：用 SECRET 对 timestamp 做 HMAC-SHA256，base64 后 urlencode 得到 sign。
# - 推送消息末尾自动追加「请点击 <公网地址> 查看」可点击链接（公网地址取 APP_BASE_URL
#   环境变量，未配置则留空）。
# - 所有异常均在内部吞掉并返回 False，绝不会阻断注册/审核主流程。
# - 凭证来自环境变量（见 .env.example）：DINGTALK_WEBHOOK_URL / DINGTALK_SECRET。

import hashlib
import base64
import hmac
import time
import os
import urllib.request
import urllib.parse
import datetime


def _load_env():
    """从项目根目录 .env 读取钉钉凭证到环境变量（仅当尚未设置时）。

    计划任务进程的环境未必加载 .env，导致 DINGTALK_WEBHOOK_URL 缺失、
    告警静默失效。这里自读 .env，不依赖启动脚本注入，也不引入第三方依赖。
    """
    try:
        # FC 环境：密钥已在函数环境变量中，禁用本地 .env 读取
        if os.environ.get("MYSQL_HOST"):
            return
        here = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(here, ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


_load_env()

WEBHOOK_URL = os.environ.get("DINGTALK_WEBHOOK_URL", "").strip()
SECRET = os.environ.get("DINGTALK_SECRET", "").strip()
# 最近一次 _post 失败的原因，供调用方记录到日志排查。
LAST_ERROR = ""


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_base_url():
    """取公网地址用于拼接推送链接。

    地址取 APP_BASE_URL 环境变量；未配置则留空（链接省略）。
    """
    env = os.environ.get("APP_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    return ""


def _link_suffix(path=""):
    """拼「请点击 <公网地址> 查看」可点击链接后缀。"""
    base = _get_base_url()
    if not base:
        return ""
    url = base.rstrip("/") + path
    return "\n\n请点击 [{}]({}) 查看".format(url, url)


def _sign():
    """计算加签参数 (timestamp, sign)。"""
    timestamp = str(round(time.time() * 1000))
    string_to_sign = "{}\n{}".format(timestamp, SECRET)
    hmac_code = hmac.new(
        SECRET.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return timestamp, sign


def _post(payload):
    """发送 POST 到群机器人 Webhook（已带加签），成功返回 True，失败写入 LAST_ERROR。"""
    global LAST_ERROR
    LAST_ERROR = ""
    if not WEBHOOK_URL:
        LAST_ERROR = "未配置 DINGTALK_WEBHOOK_URL"
        print("[钉钉推送] 未配置 DINGTALK_WEBHOOK_URL，跳过推送", flush=True)
        return False
    if not SECRET:
        LAST_ERROR = "未配置 DINGTALK_SECRET"
        print("[钉钉推送] 未配置 DINGTALK_SECRET，跳过推送", flush=True)
        return False
    ts, sign = _sign()
    url = "{}&timestamp={}&sign={}".format(WEBHOOK_URL, ts, sign)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        LAST_ERROR = "请求异常: {}".format(e)
        print("[钉钉推送] 请求异常: {}".format(e), flush=True)
        return False
    if body.get("errcode") == 0:
        print("[钉钉推送] 成功: {}".format(payload.get("markdown", {}).get("title", "")), flush=True)
        return True
    LAST_ERROR = "errcode={} errmsg={}".format(body.get("errcode"), body.get("errmsg"))
    print("[钉钉推送] 失败: {}".format(LAST_ERROR), flush=True)
    return False


def _send_markdown(title, text):
    return _post({"msgtype": "markdown", "markdown": {"title": title, "text": text}})


def notify_registration_pending(username, phone):
    """新成员注册待审核 -> 推送到钉钉群。"""
    text = (
        "**【客户管理平台】新成员注册待审核**\n"
        "> 用户名：**{}**\n"
        "> 手机号：**{}**\n"
        "> 提交时间：{}{}"
    ).format(username, phone, _now(), _link_suffix("/settings"))
    return _send_markdown("新成员注册待审核", text)


def notify_password_reset_pending(username, phone):
    """成员申请重置密码待审核 -> 推送到钉钉群提醒管理员。"""
    text = (
        "**【客户管理平台】密码重置待审核**\n"
        "> 用户名：**{}**\n"
        "> 手机号：**{}**\n"
        "> 提交时间：{}{}"
    ).format(username, phone, _now(), _link_suffix("/settings"))
    return _send_markdown("密码重置待审核", text)


def notify_registration_approved(phone):
    """成员审核通过 -> 推送到钉钉群。"""
    text = (
        "**【客户管理平台】成员审核通过**\n"
        "> 手机号：**{}**\n"
        "> 处理时间：{}{}"
    ).format(phone, _now(), _link_suffix(""))
    return _send_markdown("成员审核通过", text)


def notify_registration_rejected(phone):
    """成员审核被拒绝 -> 推送到钉钉群。"""
    text = (
        "**【客户管理平台】成员审核被拒绝**\n"
        "> 手机号：**{}**\n"
        "> 处理时间：{}{}"
    ).format(phone, _now(), _link_suffix(""))
    return _send_markdown("成员审核被拒绝", text)


def notify_night_digest(text):
    """夜间异常汇总晨报（含昨夜事件 + 恢复指引）-> 合并为一条推送。

    text 已由调用方拼好，这里只负责发出去。
    """
    return _send_markdown("🌅 夜间异常汇总", text)


if __name__ == "__main__":
    # 直接运行 = 连通性测试（真实发一条到钉钉群）
    ok = _send_markdown(
        "客户管理平台·推送测试",
        "这是钉钉群机器人推送通道连通性测试。若群里收到此条，说明通道已通。",
    )
    print("推送结果:", ok)

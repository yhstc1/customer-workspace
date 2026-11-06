#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检测一个 ngrok authtoken 是否仍然有效。

用途：撤销 authtoken 后验证是否真的吊销成功。

原理：
  ngrok API 对无效凭据返回 HTTP 403（ERR_NGROK_202 "does not look like a valid credential"），
  对有效但权限不足的 authtoken 返回 HTTP 400（ERR_NGROK_206 "actually an authtoken"）。
  所以只要看 /endpoints 这类需要鉴权的端点返回 400 还是 403，就能区分「有效」与「已失效」。

用法：
    python tools/check_ngrok_token.py                 # 自动从本地 ngrok备份docx 里提取
    python tools/check_ngrok_token.py <token>         # 直接传 token
    python tools/check_ngrok_token.py --docx "路径"   # 指定 docx 路径
"""
import os
import re
import sys
import json
import zipfile
import urllib.request
import urllib.error

API_ROOT = "https://api.ngrok.com"
PROBE_PATH = "/endpoints"  # 需要鉴权但普通 authtoken 无权访问的端点


def token_from_docx(path):
    """从 docx 里提取 authtoken（ngrok token 形如 49 位 Base64 串）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    text = re.sub(r"<[^>]+>", " ", xml)
    # ngrok authtoken：字母数字下划线连字符，长度约 49
    for m in re.finditer(r"\b([A-Za-z0-9]{2}[A-Za-z0-9_\-]{30,})\b", text):
        candidate = m.group(1)
        # 排除域名（带点）和 URL
        if "." in candidate or candidate.startswith("http"):
            continue
        return candidate
    return None


def probe(token, path=PROBE_PATH):
    """请求一个需要鉴权的端点，返回 (http_code, body)。"""
    headers = {
        "Authorization": "Bearer " + token,
        "Ngrok-Version": "2",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(API_ROOT + path, headers=headers)
    try:
        r = urllib.request.urlopen(req, timeout=25)
        return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, "NET-ERR %s: %s" % (type(e).__name__, e)


def main():
    token = None
    docx = None

    args = sys.argv[1:]
    if args and args[0] == "--docx":
        docx = args[1] if len(args) > 1 else "ngrok访问信息备份.docx"
        args = args[2:]
    if args:
        token = args[0]

    if token is None:
        # 默认在项目根找本地那份 docx
        candidates = [
            docx or "",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ngrok访问信息备份.docx"),
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", ".workbuddy", "_backup", "ngrok访问信息备份.docx.bak",
            ),
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                token = token_from_docx(c)
                if token:
                    print("已从 %s 提取 token: %s…%s（长度 %d）"
                          % (os.path.basename(c), token[:6], token[-4:], len(token)))
                    break

    if not token:
        print("未找到 token。用法：python tools/check_ngrok_token.py <token> 或 --docx <路径>")
        return 2

    code, body = probe(token)
    print("HTTP %s" % code)

    err_code = ""
    m = re.search(r'"error_code"\s*:\s*"([^"]+)"', body)
    if m:
        err_code = m.group(1)
    msg = ""
    m = re.search(r'"msg"\s*:\s*"([^"]*)"', body)
    if m:
        msg = m.group(1)

    if code == 400 and "ERR_NGROK_206" in body:
        print("判定：**token 仍然有效**（ngrok 认出它是一个有效 authtoken，只是无权访问该端点）")
        print("→ 还没吊销成功，请回控制台删除它")
        return 1
    if code == 403 or "ERR_NGROK_202" in body:
        print("判定：**token 已失效 / 不存在**（ngrok 不认这个凭据了）")
        print("→ 吊销成功 ✅")
        return 0
    if code is None:
        print("判定：网络不可达，无法判定")
        return 3
    print("判定：未知响应")
    print(body[:400])
    return 3


if __name__ == "__main__":
    sys.exit(main())

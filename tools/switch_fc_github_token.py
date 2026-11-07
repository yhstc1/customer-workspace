#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给 FC 换 GitHub token，并做端到端验证。

用途：把 FC 用的 classic PAT（repo scope，能读写全部私有仓）换成
fine-grained PAT（只授权 yhstc1/customer-data 的 Contents:Read/Write），
缩小凭证泄露的爆炸半径。

流程：
  1. 校验新 token 的身份与权限（能读 customer-data、能写、不能碰别的仓）
  2. 写入 FC 环境变量（先 Get 全量再合并，避免清空其他变量）
  3. 重启 FC 实例（换 env 需要新实例生效）
  4. 线上端到端验证：登录 → 读 → 写 → 远端 SHA 变化 → 清理测试数据
  5. 回滚保护：新 token 不合格则不动 FC

用法：
    # 1) 先看新 token 合格不合格（不碰 FC）
    python tools/switch_fc_github_token.py --check --token ghp_xxx

    # 2) 合格后正式切换并验证
    python tools/switch_fc_github_token.py --apply --token ghp_xxx

    # token 不放命令行（会进 shell 历史）时用环境变量
    export GITHUB_TOKEN=ghp_xxx
    python tools/switch_fc_github_token.py --check
    python tools/switch_fc_github_token.py --apply
"""
import base64
import json
import os
import sys
import time
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "aliyun-backend"))

API = "https://api.github.com"
FC_API = "https://crm-api-fc-nrfocbaaxv.cn-hangzhou.fcapp.run"
TARGET_REPO = "yhstc1/customer-data"
DATA_PATH = "data/customers.db"


# ============================================================
# GitHub 侧
# ============================================================
def gh(path, token, method="GET", data=None, raw=False, timeout=60):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = json.dumps(data).encode() if data is not None else None
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, headers=headers, method=method, data=body)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        payload = r.read()
        if raw:
            return r.status, payload
        return r.status, json.loads(payload.decode("utf-8"))
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload
        try:
            return e.code, json.loads(payload.decode("utf-8"))
        except Exception:
            return e.code, {"_raw": payload.decode("utf-8", "replace")[:300]}
    except Exception as e:
        return None, {"_error": "%s: %s" % (type(e).__name__, e)}


def write_probe(token, repo, path):
    """写权限探测：对已存在的文件用**错误的 sha** 发 PUT。

    返回 (status, detail)。语义（已实测）：
        409 Conflict  -> 有写权限（GitHub 先校验 sha，不匹配就拒绝，不会写入）
        403 / 404     -> 无写权限
        401           -> token 无效
        200 / 201     -> 意外写入成功（正常不会发生，sha 恒错）

    ⚠️ 零副作用：sha 恒为 40 个 0，永远匹配不上，
       所以**不会产生任何 commit、不会改动任何数据**。
       实测确认：探测前后目标文件 blob SHA 完全不变。
    """
    body = {
        "message": "probe: verify write permission (no-op, sha mismatch)",
        "content": base64.b64encode(b"probe").decode("ascii"),
        "sha": "0" * 40,          # 恒错的 sha -> 保证 409，不会真的写
        "branch": "main",
    }
    code, payload = gh("/repos/%s/contents/%s" % (repo, path), token,
                       method="PUT", data=body, timeout=60)
    if code == 409:
        return code, "有写权限（sha 不匹配被拒，未写入）"
    if code in (403, 404):
        return code, "无写权限"
    if code == 401:
        return code, "token 无效"
    if code in (200, 201):
        return code, "⚠️ 意外写入成功（不应发生）"
    return code, str(payload)[:120]


def check_token(token):
    """校验新 token：身份、能否读写目标仓、能否碰其他仓。返回 (ok, report)。"""
    report = {"ok": False, "checks": [], "notes": []}

    def add(name, ok, detail=""):
        report["checks"].append((name, ok, detail))
        return ok

    # 0) token 类型
    report["kind"] = ("fine-grained" if token.startswith("github_pat_")
                      else "classic" if token.startswith("ghp_")
                      else "unknown")

    # 1) 身份有效
    #    GET /user 对 fine-grained token 不需要任何权限（GitHub 官方文档确认）
    code, me = gh("/user", token)
    if not add("token 有效（能识别身份）", code == 200,
               "HTTP %s%s" % (code, "" if code == 200 else " " + str(me)[:120])):
        return False, report
    report["login"] = me.get("login")

    # 2) 目标仓可读
    code, _ = gh("/repos/%s/contents/%s" % (TARGET_REPO, DATA_PATH), token, raw=True)
    add("能读 %s（%s）" % (TARGET_REPO, DATA_PATH), code == 200, "HTTP %s" % code)

    # 3) 目标仓有写权限
    #    ⚠️ 不能用 GET /repos/{repo} 返回的 permissions.push 判断：
    #    那个对象反映的是**账号本人**在该仓的角色（yhstc1 是 owner，
    #    恒为 admin/push=true），不是 token 被授予的 scope ——
    #    即便 token 只给了 Read-only 也会误判为有写权限。
    #    改用写探测：409 = 有写权限，403/404 = 无写权限。零副作用。
    code, detail = write_probe(token, TARGET_REPO, DATA_PATH)
    add("对 %s 有写权限（Contents: Read and write）" % TARGET_REPO,
        code == 409, "写探测 -> HTTP %s %s" % (code, detail))

    # 4) 爆炸半径检查：能否**写**其它仓库
    #    ⚠️ 不能用 GET /repos/{其它仓} 是否 200 来判定：
    #    GitHub 官方明确「fine-grained token 永远可以读所有公开仓」
    #    （页面原文：Tokens can always read all public repositories）。
    #    customer-workspace / kehu 都是公开仓，用读权限判据必然误判失败，
    #    导致合格的 fine-grained PAT 被拒之门外。
    #
    #    也不能用 GET /repos/{其它仓}/collaborators：
    #    官方文档说该端点对 fine-grained 只需「Metadata: read」，
    #    而 Metadata 是**自动附带**的 —— 判别力不可靠。
    #
    #    真正要卡的是「能不能改别的仓」——用写探测直接判定。
    others = [
        ("yhstc1/customer-workspace", ".gitignore"),
        ("yhstc1/kehu", ".gitignore"),
    ]
    writable = []
    details = []
    for r, p in others:
        c, d = write_probe(token, r, p)
        details.append("%s=%s" % (r.split("/")[-1], c))
        if c == 409:
            writable.append(r)
    add("无法写其它仓库（爆炸半径已收窄）", not writable,
        "写探测: %s%s" % ("  ".join(details),
                          "  ❌ 仍可写: %s" % writable if writable else "  ✅ 全部拒绝"))

    # 5) 范围说明
    if report.get("login"):
        report["notes"].append(
            "验证要点：读公开仓任何 token 都能做到（GitHub 强制），"
            "所以判据用的是「写权限」；fine-grained 对未授权仓写入返回 403/404，"
            "classic PAT 返回 409"
        )
    report["notes"].append(
        "Metadata:read 对 fine-grained token 是自动附带的，"
        "页面里不可取消也不必勾选"
    )

    report["ok"] = all(ok for _, ok, _ in report["checks"])
    return report["ok"], report


def read_remote_sha(token):
    code, payload = gh("/repos/%s/contents/%s" % (TARGET_REPO, DATA_PATH), token, raw=True)
    if code != 200:
        return None
    return json.loads(payload.decode("utf-8")).get("sha")


# ============================================================
# FC 侧
# ============================================================
def fc_env_update(new_token):
    """把 GITHUB_TOKEN 换掉。先 Get 全量再合并提交。"""
    from fc_client import make_client, get_function_env, function_name, runtime
    from alibabacloud_fc20230330 import models as fc_models

    client = make_client()
    env = get_function_env(client)
    old = env.get("GITHUB_TOKEN", "")
    env["GITHUB_TOKEN"] = new_token

    body = fc_models.UpdateFunctionInput(environment_variables=env)
    req = fc_models.UpdateFunctionRequest(body=body)
    resp = client.update_function(function_name(), req)
    out = resp.body
    out = out.to_map() if hasattr(out, "to_map") else out
    return old, out


def fc_restart():
    """让新 env 生效：FC 换环境变量后会滚动重启实例，这里等它就绪。"""
    time.sleep(8)


# ============================================================
# 线上端到端验证
# ============================================================
def api(path, method="GET", data=None, cookie=None, timeout=120):
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(FC_API + path, headers=headers, method=method, data=body)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        raw = r.read().decode("utf-8", "replace")
        try:
            return r.status, json.loads(raw), r.headers.get("Set-Cookie", "")
        except Exception:
            return r.status, raw, r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), ""
        except Exception:
            return e.code, raw, ""
    except Exception as e:
        return None, {"_error": "%s: %s" % (type(e).__name__, e)}, ""


def e2e_verify(token):
    """线上验证：登录 → 读 → 写 → 远端 SHA 变化 → 清理。"""
    result = {}

    code, body, cookie = api("/api/login", "POST",
                             {"phone": "18607184641", "password": "yuhui1230"})
    result["login"] = (code, "ok" if code == 200 else str(body)[:150])
    if code != 200:
        return result

    ck = cookie.split(";")[0] if cookie else ""

    for name, path in (("customers", "/api/customers"),
                       ("tasks", "/api/tasks"),
                       ("business", "/api/business"),
                       ("settings", "/api/settings"),
                       ("admin_users", "/api/admin/users")):
        c, _, _ = api(path, cookie=ck)
        result["read_" + name] = c

    # 写测试
    sha_before = read_remote_sha(token)
    c, body, _ = api("/api/customers", "POST",
                  {"name": "token切换验证", "company": "token切换验证",
                   "phone": "027-0000002", "category": "普通客户"}, cookie=ck)
    result["write"] = c
    new_id = body.get("id") if isinstance(body, dict) else None
    result["new_id"] = new_id

    time.sleep(2)
    sha_after = read_remote_sha(token)
    result["sha_before"] = sha_before
    result["sha_after"] = sha_after
    result["remote_updated"] = bool(sha_before and sha_after and sha_before != sha_after)

    # 清理
    if new_id:
        c, _, _ = api("/api/customers/%s" % new_id, "DELETE", cookie=ck)
        result["cleanup"] = c
    time.sleep(2)
    sha_final = read_remote_sha(token)
    result["sha_final"] = sha_final

    # 残留检查
    c, payload, _ = api("/api/customers", cookie=ck)
    items = payload if isinstance(payload, list) else (
        (payload.get("items") or payload.get("data") or []) if isinstance(payload, dict) else [])
    result["residual"] = sum(
        1 for it in items if isinstance(it, dict) and "token切换验证" in str(it.get("company", "")))
    result["customer_count"] = len(items)
    return result


def main():
    args = sys.argv[1:]
    if "--check" not in args and "--apply" not in args:
        raise SystemExit("用法：python tools/switch_fc_github_token.py [--check|--apply] [--token xxx]")

    token = ""
    if "--token" in args:
        i = args.index("--token")
        token = args[i + 1] if i + 1 < len(args) else ""
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("取不到 token：请用 --token xxx 或设 GITHUB_TOKEN 环境变量")

    print("=" * 62)
    print("token 预检（不会修改任何东西）")
    print("=" * 62)
    print("  token 前缀 = %s…  长度 = %d" % (token[:6], len(token)))
    ok, rep = check_token(token)
    for name, passed, detail in rep["checks"]:
        print("  [%s] %-42s %s" % ("✓" if passed else "✗", name, detail))
    for note in rep.get("notes", []):
        print("  · %s" % note)

    if not ok:
        print("\n❌ 预检不通过，**未改动 FC**。请换一个权限合适的 token 再试。")
        return 1

    if "--check" in args and "--apply" not in args:
        print("\n✅ 预检通过。加 --apply 执行正式切换。")
        return 0

    print()
    print("=" * 62)
    print("正式切换：写入 FC 环境变量")
    print("=" * 62)
    old, out = fc_env_update(token)
    print("  旧 token 前缀 = %s…" % old[:6])
    print("  新 token 前缀 = %s…" % token[:6])
    print("  ✅ 环境变量已提交")

    print("  等待实例重启生效…")
    fc_restart()

    print()
    print("=" * 62)
    print("线上端到端验证")
    print("=" * 62)
    r = e2e_verify(token)
    print("  登录          = %s %s" % (r.get("login", ("?", ""))[0], r.get("login", ("", ""))[1]))
    for k in ("read_customers", "read_tasks", "read_business",
              "read_settings", "read_admin_users"):
        print("  %-14s = %s" % (k.replace("read_", "读 "), r.get(k)))
    print("  写入新建      = %s (id=%s)" % (r.get("write"), r.get("new_id")))
    print("  远端 SHA 变化 = %s" % ("✅ 是" if r.get("remote_updated") else "❌ 否"))
    print("  清理测试数据  = %s" % r.get("cleanup"))
    print("  残留测试客户  = %s" % r.get("residual"))
    print("  当前客户数    = %s" % r.get("customer_count"))

    allok = (r.get("login", (0,))[0] == 200
             and all(r.get(k) == 200 for k in ("read_customers", "read_tasks",
                                              "read_business", "read_settings",
                                              "read_admin_users"))
             and r.get("write") in (200, 201)
             and r.get("remote_updated")
             and r.get("residual") == 0)
    print()
    print("✅ 切换成功，全链路通过" if allok else "❌ 验证未全部通过，请检查上面的输出")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())

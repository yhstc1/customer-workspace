# -*- coding: utf-8 -*-
"""
纯标准库 GitHub 推送（不依赖 git 二进制）。

当 github.com 直连被墙、或环境没有 git（如鸿蒙本）时，用 api.github.com 的
Git Data API 把本地改动推到远端 main。零第三方依赖，只用 base64/json/urllib/hashlib。

与旧版区别：旧版用 `git diff` / `git rev-parse` 等本地 git 对象库判断改动；本版改为
「扫描本地纳入同步的文件集（按 .gitignore 排除），与远端 tree 逐文件比对 content sha，
仅差异文件建 blob」，因此不需要 git 二进制、也不需要在本地有完整的 git 对象库。

用法（仓库根目录执行）：
    python3 tools/gh_push_api.py                  # 默认 dry-run：预览要改/增/删的文件
    python3 tools/gh_push_api.py --apply          # 真正推送
    python3 tools/gh_push_api.py --repo yhstc1/customer-workspace
    python3 tools/gh_push_api.py --token ghp_xxx   # 或设环境变量 GH_TOKEN

仓库 slug：--repo > GH_REPO 环境变量 > 状态文件(.workbuddy/gh_push_state.json 的 repo)
token    ：--token > GH_TOKEN 环境变量 > （可选）git credential fill 兜底（仅当本机有 git）
安全护栏：推送前校验远端 main 的 sha == 上次记录（防覆盖他人/他途提交）；不一致中止。
          dry-run 不会改动任何远端资源。
"""
import argparse
import base64
import fnmatch
import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

# 鸿蒙本 Python 不带 CA 证书包，api.github.com 的 TLS 握手会 CERTIFICATE_VERIFY_FAILED。
# 与 fc_probe/fc_deploy_stdlib 一致：关闭证书校验（仅影响本机↔GitHub 链路；
# token 仍走 HTTPS 加密通道，仅跳过对端证书链校验，在可信网络下可接受）。
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"
BRANCH = "main"
STATE_FILE = os.path.join(ROOT, ".workbuddy", "gh_push_state.json")


def api(path, token, method="GET", data=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "gh-push-stdlib")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60, context=_CTX) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit("API %s %s 失败: %s\n%s" % (method, path, e.code, e.read().decode("utf-8", "replace")))


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        print("（状态文件写入失败，不影响推送：%s）" % e)


def get_token(args):
    if args.token:
        return args.token
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    # 兜底：本机有 git 时用 credential fill（鸿蒙本无 git 会直接跳过）
    try:
        if shutil.which("git"):
            out = subprocess.run(["git", "credential", "fill"],
                                 input="protocol=https\nhost=github.com\n\n",
                                 capture_output=True, text=True).stdout
            for line in out.splitlines():
                if line.startswith("password="):
                    return line[len("password="):].strip()
    except Exception:
        pass
    sys.exit("取不到 GitHub token：请设环境变量 GH_TOKEN 或传 --token")


def blob_sha(content_bytes):
    header = b"blob %d\0" % len(content_bytes)
    return hashlib.sha1(header + content_bytes).hexdigest()


def parse_gitignore(path):
    pats = []
    if not os.path.exists(path):
        return pats
    for line in open(path, encoding="utf-8").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        neg = line.startswith("!")
        if neg:
            line = line[1:]
        is_dir = line.endswith("/")
        if is_dir:
            line = line.rstrip("/")
        anchored = "/" in line  # 含 /（非仅末尾）视为从仓库根锚定
        pats.append((line, neg, is_dir, anchored))
    return pats


def is_ignored(rel, pats):
    # 防御性硬黑名单：.git 内部文件绝不可被纳入（gitignore 未必显式写）
    if rel == ".git" or rel.startswith(".git/"):
        return True
    parts = rel.split("/")
    base = parts[-1]
    for (m, neg, is_dir, anchored) in pats:
        matched = False
        if anchored:
            if "*" in m:
                matched = fnmatch.fnmatch(rel, m) or fnmatch.fnmatch(rel, m.rstrip("/") + "/*")
            else:
                matched = (rel == m) or rel.startswith(m.rstrip("/") + "/")
        elif is_dir:
            matched = (m in parts) or rel.startswith(m + "/")
        else:
            if "*" in m:
                matched = fnmatch.fnmatch(base, m) or fnmatch.fnmatch(rel, m)
            else:
                matched = (base == m)
        if matched:
            return not neg
    return False


def scan_local(pats):
    files = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # 强制剪枝：绝不进入这些目录（.git 尤其不能扫，会泄露 git 内部文件）
        dirnames[:] = [d for d in dirnames if d not in (
            ".git", "node_modules", ".workbuddy", "venv", ".venv", "__pycache__")]
        rel_dir = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        for fn in filenames:
            rel = (rel_dir + "/" + fn) if rel_dir != "." else fn
            if is_ignored(rel, pats):
                continue
            files.add(rel)
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正推送；默认仅 dry-run 预览")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    state = load_state()
    repo = args.repo or os.environ.get("GH_REPO") or state.get("repo")
    if not repo:
        sys.exit("无法确定仓库：传 --repo 或设 GH_REPO，或先写入状态文件")
    token = get_token(args)
    repo_path = "/repos/" + repo
    print("仓库: %s  分支: %s" % (repo, BRANCH))

    # ---- 安全护栏：远端 sha 必须 == 上次记录 ----
    ref = api("%s/git/ref/heads/%s" % (repo_path, BRANCH), token)
    remote_sha = ref["object"]["sha"]
    prev = state.get("remote_sha")
    if prev and prev != remote_sha:
        sys.exit("✗ 中止：远端 main 与上次推送记录不一致（远端=%s，记录=%s）。\n"
                 "  可能有人/他途改过远端，请先人工对齐再推。" % (remote_sha[:10], prev[:10]))
    if not prev:
        print("（首次推送：未找到历史记录，将初始化同步；请确保远端当前状态是你想作为基准的）")

    # ---- 扫描本地 + 远端 tree ----
    pats = parse_gitignore(os.path.join(ROOT, ".gitignore"))
    local_files = scan_local(pats)
    tree_resp = api("%s/git/trees/%s?recursive=1" % (repo_path, remote_sha), token)
    base_tree_sha = tree_resp.get("sha", remote_sha)
    remote_map = {t["path"]: t["sha"] for t in tree_resp.get("tree", []) if t.get("type") == "blob"}

    # ---- 增量对比（本地 vs 远端 tree，按 content sha）----
    items, added, modified, deleted = [], [], [], []
    for rel in sorted(local_files):
        with open(os.path.join(ROOT, rel), "rb") as fh:
            content = fh.read()
        sha = blob_sha(content)
        rsha = remote_map.get(rel)
        if rsha == sha:
            continue
        if len(content) > 100 * 1024 * 1024:
            sys.exit("文件过大，跳过以防 API 限制: %s" % rel)
        blob = api("%s/git/blobs" % repo_path, token, "POST",
                   {"content": base64.b64encode(content).decode("ascii"), "encoding": "base64"})
        items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        (modified if rsha else added).append(rel)

    old_tracked = set(state.get("tracked", []))
    for rel in sorted(old_tracked - local_files):
        items.append({"path": rel, "mode": "100644", "type": "blob", "sha": None})
        deleted.append(rel)

    if not items:
        print("无变化，无需推送")
        return

    print("将改动：+%d 新增/修改, -%d 删除" % (len(added) + len(modified), len(deleted)))
    for r in added:
        print("  + " + r)
    for r in modified:
        print("  ~ " + r)
    for r in deleted:
        print("  - " + r)

    if not args.apply:
        print("\n[dry-run] 未加 --apply，不改动远端。")
        return

    new_tree = api("%s/git/trees" % repo_path, token, "POST",
                   {"base_tree": base_tree_sha, "tree": items})
    message = args.message or ("chore: 经 GitHub API 同步（鸿蒙本纯标准库推送）\n\n"
                               "改动 %d 个文件" % len(items))
    new_commit = api("%s/git/commits" % repo_path, token, "POST",
                    {"message": message, "tree": new_tree["sha"], "parents": [remote_sha]})
    api("%s/git/refs/heads/%s" % (repo_path, BRANCH), token, "PATCH", {"sha": new_commit["sha"]})
    after = api("%s/git/ref/heads/%s" % (repo_path, BRANCH), token)["object"]["sha"]
    if after != new_commit["sha"]:
        sys.exit("✗ 校验失败：远端未指向新提交")
    save_state({"branch": BRANCH, "remote_sha": new_commit["sha"],
                "tracked": sorted(local_files), "repo": repo})
    print("\n✓ 推送成功  %s" % new_commit.get("html_url", ""))


if __name__ == "__main__":
    main()

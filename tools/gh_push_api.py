# -*- coding: utf-8 -*-
"""
github.com 直连被墙（git push 必然失败）时，改用 api.github.com 的 Git Data API 推送本地提交。

原理：不传 diff，而是把「改动后的文件全文」逐个建成 blob，再用一棵新 tree + 一个 commit
把远端 main 指过去。效果等价于 git push，且保持**单个 commit**。

用法（仓库根目录执行）：
    venv/Scripts/python.exe tools/gh_push_api.py            # 推送最后 1 个提交（最常用）
    venv/Scripts/python.exe tools/gh_push_api.py HEAD~2     # 把 HEAD~2..HEAD 合并成 1 个提交推送

token 来源（按优先级）：
    1) 环境变量 GH_TOKEN
    2) `git credential fill`（Windows 凭据管理器里已存的 yhstc1 token，本机/沙箱同身份可解）

安全护栏：
    - 推送前校验「本地记录的 origin/main」== «远端真实 main»，不一致直接中止（防止覆盖他人提交）
    - 只处理本次 diff 涉及的文件，其余文件沿用远端 tree，不动
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

GIT = r"C:\Users\yohyi\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin\git.exe"
API = "https://api.github.com"
BRANCH = "main"


def git(*args, check=True):
    r = subprocess.run([GIT] + list(args), capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode:
        sys.exit("git 命令失败: git %s\n%s" % (" ".join(args), r.stderr))
    return r.stdout.strip()


def get_token():
    tok = os.environ.get("GH_TOKEN")
    if tok:
        return tok
    out = subprocess.run([GIT, "credential", "fill"],
                         input="protocol=https\nhost=github.com\n\n",
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line[len("password="):].strip()
    sys.exit("取不到 GitHub token：既无 GH_TOKEN，credential fill 也没返回 password")


STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          ".workbuddy", "gh_push_state.json")


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return {}


def save_state(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        print("（状态文件写入失败，不影响推送结果：%s）" % e)


def api(path, token, method="GET", data=None):
    url = API + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "gh-push-api-script")
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit("API %s %s 失败: %s\n%s" % (method, path, e.code, e.read().decode("utf-8", "replace")))


def main():
    since = sys.argv[1] if len(sys.argv) > 1 else "HEAD~1"
    token = get_token()

    # 仓库全名：从 remote URL 解析（形如 https://github.com/yhstc1/customer-workspace.git）
    remote = git("remote", "get-url", "origin")
    slug = remote.replace("https://github.com/", "").replace("http://github.com/", "")
    slug = slug.replace("git@github.com:", "").rstrip("/").removesuffix(".git")
    repo_path = "/repos/" + slug
    print("仓库: %s    分支: %s" % (slug, BRANCH))

    # ---- 安全护栏：基准必须自洽 ----
    # 由 API 推上去的 commit 只存在于远端，本地对象库没有它，git update-ref 必然失败，
    # 因此本地 origin/main 会「看起来落后」。用状态文件记住上次 API 推送的对应关系，
    # 只要 (远端sha, 本地HEAD) 与记录一致，就说明基准自洽，可以继续推。
    local_head = git("rev-parse", "HEAD")
    local_origin = git("rev-parse", "origin/" + BRANCH, check=False) or ""
    ref = api("%s/git/ref/heads/%s" % (repo_path, BRANCH), token)
    remote_sha = ref["object"]["sha"]
    state = load_state()
    print("本地 HEAD       = %s" % local_head[:10])
    print("本地 origin/%s = %s" % (BRANCH, local_origin[:10]))
    print("远端 %-9s = %s" % (BRANCH, remote_sha[:10]))
    # 情况③：上次 API 推过，之后本地又新增了提交 —— 只要上次的 local_commit 是
    # 当前 HEAD 的祖先，就说明本地是在那个基准上往前走的，基准依然自洽。
    ahead_of_state = False
    if state.get("local_commit"):
        ahead_of_state = subprocess.run(
            [GIT, "merge-base", "--is-ancestor", state["local_commit"], "HEAD"]
        ).returncode == 0
    synced = (local_origin == remote_sha) or (
        state.get("branch") == BRANCH
        and state.get("remote_sha") == remote_sha
        and (state.get("local_commit") == local_head or ahead_of_state)
    )
    if not synced:
        sys.exit("✗ 中止：本地记录的远端与线上不一致，且不匹配上次 API 推送记录。\n"
                 "  请在能连 github.com 的环境先 `git fetch && git reset --soft origin/%s` 对齐后再推。"
                 % BRANCH)

    # ---- 收集改动文件 ----
    status = git("diff", "--name-status", since, "HEAD")
    if not status:
        sys.exit("没有任何改动，无需推送")
    entries, deleted = [], []
    for line in status.splitlines():
        if not line.strip():
            continue
        st, path = line.split("\t", 1)
        path = path.replace("\\", "/")
        if st.startswith("D"):
            deleted.append(path)
        else:
            entries.append(path)
    print("改动文件（%d 新增/修改，%d 删除）:" % (len(entries), len(deleted)))

    # ---- 为每个改动文件建 blob ----
    tree_items = []
    for path in entries:
        with open(path, "rb") as fh:
            content = fh.read()
        blob = api("%s/git/blobs" % repo_path, token, "POST", {
            "content": base64.b64encode(content).decode("ascii"),
            "encoding": "base64",
        })
        tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("  + %-42s %6d B" % (path, len(content)))
    for path in deleted:
        tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        print("  - %s（删除）" % path)

    # ---- 建 tree / commit / 更新 ref ----
    base_commit = api("%s/git/commits/%s" % (repo_path, remote_sha), token)
    new_tree = api("%s/git/trees" % repo_path, token, "POST", {
        "base_tree": base_commit["tree"]["sha"],
        "tree": tree_items,
    })
    if since == "HEAD~1":
        message = git("log", "-1", "--format=%B")
    else:
        message = "chore: 批量同步 %s..HEAD\n\n由 tools/gh_push_api.py 经 GitHub API 推送（直连 github.com 不可用）" % since
    new_commit = api("%s/git/commits" % repo_path, token, "POST", {
        "message": message,
        "tree": new_tree["sha"],
        "parents": [remote_sha],
    })
    api("%s/git/refs/heads/%s" % (repo_path, BRANCH), token, "PATCH", {"sha": new_commit["sha"]})

    # ---- 回读校验 ----
    after = api("%s/git/ref/heads/%s" % (repo_path, BRANCH), token)["object"]["sha"]
    print("\n新提交: %s" % new_commit["sha"][:10])
    print("推送后远端 %s = %s" % (BRANCH, after[:10]))
    if after != new_commit["sha"]:
        sys.exit("✗ 校验失败：远端未指向新提交")
    # 新 commit 只存在于远端，本地对象库没有 → update-ref 会失败，这是预期行为。
    # 因此改为记录状态文件，供下次推送时判断基准是否自洽。
    save_state({"branch": BRANCH, "remote_sha": new_commit["sha"],
                "local_commit": local_head, "repo": slug})
    r = subprocess.run([GIT, "update-ref", "refs/remotes/origin/" + BRANCH, new_commit["sha"]],
                       capture_output=True, text=True)
    print("✓ 推送成功  %s" % new_commit["html_url"])
    if r.returncode:
        print("  注：本地 origin/%s 无法指向远端新提交（对象不在本地库，属正常）。\n"
              "     下次在能连 github.com 的环境执行 `git fetch && git reset --soft origin/%s` 即可对齐，\n"
              "     在此之前重复用本脚本推送不受影响。" % (BRANCH, BRANCH))


if __name__ == "__main__":
    main()

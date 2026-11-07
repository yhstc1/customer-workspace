# -*- coding: utf-8 -*-
"""GitHub 私有仓存储后端（方案 A：用 GitHub 替代 RDS 存业务数据）。

================================ 设计说明 ================================
为什么存「整个 SQLite 文件」而不是「逐表 JSON」
------------------------------------------------
app.py 有 59 处 get_db()、25 处 JOIN、GROUP BY / SUM / COUNT 聚合、
以及 SQLite 专有语法（datetime('now','localtime')、INSERT OR REPLACE、
ON CONFLICT ... DO UPDATE、PRAGMA foreign_keys）。
若把存储改成「逐表 JSON + 应用层查表」，等于要重写整个查询层，
改动面巨大、回归风险极高。

因此本方案的做法是：
    运行时引擎  = SQLite（保持 app.py 业务 SQL 零改动）
    持久化载体  = GitHub 私有仓里的 customers.db 文件
即「把 RDS 这块「云盘」换成 GitHub 仓」，语义等价、风险最低。

数据流
------
  冷启动：GitHub 拉取 customers.db -> 还原到 /tmp 可写目录 -> 正常提供服务
  写入后：把 SQLite 重新打包上传 GitHub（带 ETag 乐观锁，防并发覆盖）

并发安全
--------
FC 实例数=1 且 instanceConcurrency=1（已核实线上配置），同一时刻只有一个
实例在跑，写入天然串行。但仍用 blob SHA 做乐观锁：上传前比对远端 SHA，
不一致说明期间有别的写入，拒绝覆盖并抛错，避免静默丢数据。
（多实例部署时可通过 GH_FORCE_PUSH=1 退化为「后写覆盖」，需自行承担风险。）

切换方式（可回滚）
------------------
设置环境变量 GITHUB_STORE_REPO=owner/repo 即可启用本后端；
删除该变量即回退到 MySQL/SQLite 原逻辑。RDS 实例不删除，随时可切回。
============================================================================
"""
import base64
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.request

API = "https://api.github.com"

# 仓库内数据文件路径（放在 .workbuddy/ 之外的独立目录，避免与代码混淆）
DATA_PATH_IN_REPO = os.environ.get("GITHUB_DATA_PATH", "data/customers.db")

# 上传失败重试
_MAX_RETRY = int(os.environ.get("GITHUB_UPLOAD_RETRY", "3"))

_lock = threading.Lock()


def _env():
    repo = os.environ.get("GITHUB_STORE_REPO", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    return repo, token


def enabled() -> bool:
    """是否启用 GitHub 存储后端。"""
    repo, token = _env()
    return bool(repo and token)


def _api(path, token, method="GET", data=None, timeout=60, raw=False):
    url = API + path
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "crm-github-store")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            if raw:
                return payload
            return json.loads(payload.decode("utf-8")) if payload else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("GitHub API %s %s 失败: HTTP %s %s" % (method, path, e.code, detail))


def _split_repo(repo):
    repo = repo.strip().strip("/")
    if repo.startswith("http"):
        repo = repo.split("github.com/", 1)[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if "/" not in repo:
        raise RuntimeError("GITHUB_STORE_REPO 格式应为 owner/repo，当前: %r" % repo)
    return repo.split("/", 1)


def repo_access_status(token=None):
    """检查当前 token 对目标仓是否有访问权。

    返回 (ok: bool, detail: str)。

    为什么必须单独探测：
        fine-grained PAT 无权访问某个**私有**仓时，GitHub 对
        `GET /repos/{owner}/{repo}/contents/{path}` 返回 **404**，
        与「仓库可访问但文件不存在」的 404 完全一样。
        若不区分，就会把「权限不足」误判成「远端没数据」，
        于是 FC 用空库启动，并在首次写入时把空库上传覆盖真实数据。

    对照：公开仓（customer-workspace / kehu）对任何 token 都返回 200，
    所以本探测只对私有仓才有判别力——而 customer-data 正是私有仓。
    """
    repo, tok = _env()
    if token:
        tok = token
    owner, name = _split_repo(repo)
    try:
        raw = _api("/repos/%s/%s" % (owner, name), tok, timeout=30, raw=True)
        return True, "可访问 %s" % repo
    except RuntimeError as e:
        msg = str(e)
        if "HTTP 404" in msg:
            return False, ("无权访问 %s（404：token 未获该私有仓授权，"
                           "或仓库不存在）" % repo)
        if "HTTP 403" in msg:
            return False, "无权访问 %s（403）" % repo
        return False, msg[:200]


# ============================================================
# 下载
# ============================================================
def download_db(dest_path):
    """从 GitHub 仓下载 customers.db 到 dest_path。

    返回值：
        str  —— 成功，值为远端文件的 blob SHA（乐观锁基线）
        None —— 远端确实没有该文件（仓库可访问，但文件不存在 = 全新部署）
    抛 RuntimeError —— 无权访问仓库 / 网络错误等（**不可吞掉**，
        吞掉会导致调用方误以为「远端没数据」而用空库启动）。
    """
    repo, token = _env()
    owner, name = _split_repo(repo)

    # 先确认对仓库有访问权，把「无权访问(404)」与「文件不存在(404)」区分开
    ok, detail = repo_access_status(token)
    if not ok:
        raise RuntimeError("GitHub 仓库访问校验失败: %s" % detail)

    path = "/repos/%s/%s/contents/%s" % (owner, name, DATA_PATH_IN_REPO)
    try:
        raw = _api(path, token, timeout=90, raw=True)
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            # 仓库可访问但文件不存在 → 远端确实为空（首次部署），不是错误
            return None
        raise
    payload = json.loads(raw.decode("utf-8"))
    content = base64.b64decode(payload["content"])
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(content)
    return payload.get("sha")


def get_remote_sha():
    """取远端 customers.db 的 blob SHA（用于乐观锁比对）。"""
    repo, token = _env()
    owner, name = _split_repo(repo)
    path = "/repos/%s/%s/contents/%s" % (owner, name, DATA_PATH_IN_REPO)
    try:
        raw = _api(path, token, timeout=60, raw=True)
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            return None
        raise
    return json.loads(raw.decode("utf-8")).get("sha")


# ============================================================
# 上传
# ============================================================
def upload_db(src_path, expected_sha=None):
    """把本地 SQLite 文件上传到 GitHub 仓。

    expected_sha 不为空时做乐观锁：远端 SHA 与之不符则拒绝写入，
    抛 RuntimeError，避免并发场景下静默覆盖别人的数据。
    返回远端新文件的 SHA。
    """
    repo, token = _env()
    owner, name = _split_repo(repo)
    with open(src_path, "rb") as f:
        content = f.read()
    b64 = base64.b64encode(content).decode("ascii")

    remote_sha = get_remote_sha()
    if expected_sha is not None and remote_sha != expected_sha:
        raise RuntimeError(
            "GitHub 数据文件已被其他写入更新（远端 SHA %s != 预期 %s），已中止覆盖"
            % (str(remote_sha)[:12], str(expected_sha)[:12])
        )
    if os.environ.get("GITHUB_FORCE_PUSH") == "1":
        # 显式退化为后写覆盖（多实例部署时使用，牺牲一致性换可用性）
        remote_sha = None

    body = {
        "message": "chore(crm): sync customers.db %s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "content": b64,
        "branch": os.environ.get("GITHUB_BRANCH", "main"),
    }
    if remote_sha:
        body["sha"] = remote_sha
    path = "/repos/%s/%s/contents/%s" % (owner, name, DATA_PATH_IN_REPO)
    last_err = None
    for attempt in range(1, _MAX_RETRY + 1):
        try:
            res = _api(path, token, method="PUT", data=body, timeout=120)
            return (res.get("content") or {}).get("sha")
        except RuntimeError as e:
            last_err = e
            if attempt < _MAX_RETRY:
                time.sleep(1.5 * attempt)
    raise RuntimeError("上传 customers.db 到 GitHub 失败（重试 %d 次）：%s" % (_MAX_RETRY, last_err))


# ============================================================
# 与 SQLite 的桥接
# ============================================================
def _pack_sqlite(db_path):
    """用 VACUUM INTO 把 db 打包成一个干净的独立文件（含全部数据，无 WAL 残留）。"""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(tmp_fd)
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("VACUUM INTO ?", (tmp_path,))
        finally:
            conn.close()
        return tmp_path
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def sync_to_github(db_path, expected_sha=None):
    """把当前 SQLite 内容同步到 GitHub。返回远端 SHA。"""
    with _lock:
        packed = _pack_sqlite(db_path)
        try:
            return upload_db(packed, expected_sha=expected_sha)
        finally:
            if os.path.exists(packed):
                os.remove(packed)


def restore_from_github(dest_path):
    """从 GitHub 还原数据库到 dest_path。

    返回值同 download_db：
        str  —— 成功，值为远端 blob SHA
        None —— 远端确实没有数据文件（首次部署）
    异常  —— 无权访问 / 网络错误（调用方必须视为致命错误，不可继续用空库）
    """
    return download_db(dest_path)


def local_sha(db_path):
    """本地文件的 git blob SHA（与 GitHub 的 blob SHA 算法一致），
    便于把「当前这份数据」的指纹持久化，实现乐观锁基线。"""
    import hashlib

    with open(db_path, "rb") as f:
        data = f.read()
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()

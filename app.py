"""
客户管理平台 - Flask 主应用
功能路由:
  /              - 首页（仪表盘）
  /customers     - 客户列表与管理
  /map           - 地图视图
  /tasks         - 事项看板
  /reports       - 报告列表与生成
  /settings      - 设置（账号管理）

API 路由:
  /api/customers         - GET/POST 客户 CRUD
  /api/customers/<id>    - GET/PUT/DELETE 单个客户
  /api/tasks             - GET/POST 事项 CRUD
  /api/tasks/<id>        - PUT/DELETE 单个事项
  /api/nearby            - GET 附近客户查询
  /api/geocode           - GET 地址地理编码
  /api/settings          - GET/PUT 设置
  /api/register          - POST 手机号自助注册（待管理员审核）
  /api/change-password   - POST 修改密码
  /api/admin/pending     - GET 待审核注册列表（仅管理员）
  /api/admin/users       - GET 全部用户及状态（仅管理员）
  /api/admin/approve     - POST 通过审核（仅管理员）
  /api/admin/reject      - POST 拒绝并删除注册（仅管理员）
  /api/report/generate   - POST 生成报告
"""
import os
import csv
import io
import time
from datetime import datetime, timedelta


def _load_dotenv():
    """轻量 .env 加载器（无第三方依赖）。

    仅用于**本地开发**：当进程已处于 FC 环境（注入了 MYSQL_HOST）时，
    完全跳过文件读取——线上密钥统一来自 FC 函数环境变量，不依赖文件系统 .env，
    避免容器内残留 .env 被误读或打包。
    """
    if os.environ.get("MYSQL_HOST"):
        return  # FC 环境：密钥已在函数环境变量中，禁用本地 .env 加载
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
    except Exception:
        pass


_load_dotenv()
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, redirect, url_for, session, Response
import re
import os
import hashlib

# 从 mobile.js 读取 APP_VERSION，作为静态资源「路径版本号」（如 /static/v2017/...）。
# 目的：Android WebView 按路径缓存、忽略 ?v= 查询串，把版本号放进路径可强制拉最新。
APP_STATIC_VER = "0"
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static/js/mobile.js"), encoding="utf-8") as _vf:
        _vm = re.search(r"APP_VERSION\s*=\s*['\"]([\d.]+)['\"]", _vf.read())
        if _vm:
            APP_STATIC_VER = _vm.group(1).replace(".", "")
except Exception:
    pass


def get_static_ver():
    """静态资源版本号：基于关键静态文件（CSS/JS/图片）的修改时间实时计算，每次请求都重读。
    效果：改完文件「保存」即自动让 URL 版本号变化、浏览器缓存失效 —— 无需重启服务，
    也无需手动 bump APP_VERSION。APP_STATIC_VER 仅作盐，便于跨机器识别同一版本。
    注意：这只是静态资源（CSS/JS/图片）的缓存失效机制；改 app.py 本身（服务端逻辑）
    仍须重启 waitress 才会生效。"""
    h = hashlib.md5()
    if APP_STATIC_VER:
        h.update(APP_STATIC_VER.encode("utf-8"))
    _base = os.path.dirname(os.path.abspath(__file__))
    _tracked = (
        "static/css/style.css", "static/css/mobile.css",
        "static/js/app.js", "static/js/mobile.js", "static/js/biz-fields.js",
        "static/images", "static/img",
    )
    for _rel in _tracked:
        _fp = os.path.join(_base, _rel)
        try:
            if os.path.isdir(_fp):
                for _root, _dirs, _files in os.walk(_fp):
                    for _f in sorted(_files):
                        _full = os.path.join(_root, _f)
                        try:
                            h.update(("%s:%d" % (_full, int(os.path.getmtime(_full)))).encode("utf-8"))
                        except OSError:
                            pass
            else:
                h.update(("%s:%d" % (_fp, int(os.path.getmtime(_fp)))).encode("utf-8"))
        except OSError:
            pass
    return h.hexdigest()[:10]


from werkzeug.security import check_password_hash, generate_password_hash

from models import get_db, init_db, seed_sample_data, normalize_company, company_exists, _seed_user_settings
from geo_service import geocode, reverse_geocode, find_nearby_customers
from dingtalk_notify import notify_registration_pending, notify_registration_approved, notify_registration_rejected, notify_password_reset_pending  # 钉钉群机器人推送
from report_generator import generate_daily_report, REPORTS_DIR

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "customer-workspace-secret-2026")
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
# 跨域 session cookie：GitHub Pages / 其他静态托管访问 FC 后端时，浏览器要求 SameSite=None + Secure。
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True

# 确保数据库表结构存在。
# gunicorn 等 WSGI 服务器不会执行 __main__，必须在模块加载时初始化，
# 否则线上首个请求就会因表不存在而 500。init_db() 是幂等的（CREATE IF NOT EXISTS）。
try:
    init_db()
except Exception as _e:  # noqa: BLE001
    print(f"[WARN] init_db 失败: {_e}")


def recalc_priority(cid):
    """
    根据客户关联数据自动设置优先级（客户维度，与事项状态无关）：
    - 有进行中事项 → 高
    - 有业务 → 中
    - 其他 → 低
    """
    conn = get_db()
    has_tasks = conn.execute("""
        SELECT 1 FROM tasks WHERE customer_id = ? AND status = '进行中' LIMIT 1
    """, (cid,)).fetchone()
    if has_tasks:
        priority = "高"
    else:
        has_biz = conn.execute("SELECT 1 FROM businesses WHERE customer_id = ? LIMIT 1", (cid,)).fetchone()
        priority = "中" if has_biz else "低"
    conn.execute("UPDATE customers SET priority=?, updated_at=datetime('now','localtime') WHERE id=?", (priority, cid))
    conn.commit()
    conn.close()
    return priority


def cleanup_auto_imported_customer(cid):
    """
    业务关联变更/删除后，若该客户为「导入业务时自动添加的」(source='auto_business_import')
    且已无业务、无事项，则自动删除。手动建的客户（source 为空）不受影响。
    """
    if not cid:
        return False
    conn = get_db()
    try:
        c = conn.execute("SELECT source FROM customers WHERE id=?", (cid,)).fetchone()
        if not c or c["source"] != "auto_business_import":
            return False
        if conn.execute("SELECT 1 FROM businesses WHERE customer_id=? LIMIT 1", (cid,)).fetchone():
            return False
        if conn.execute("SELECT 1 FROM tasks WHERE customer_id=? LIMIT 1", (cid,)).fetchone():
            return False
        conn.execute("DELETE FROM customers WHERE id=?", (cid,))
        conn.commit()
        return True
    finally:
        conn.close()


@app.after_request
def caching_policy(response):
    """缓存策略（兼顾「改完立即生效」与「省流量/减少重复加载」）：

    - 带版本号的静态资源（路径 /assets/v<ver>/... 或查询串 ?v=...，手机端
      mobile.css/mobile.js、以及带 ?v= 的 style.css/app.js、about-logo 图片走这条）：
      内容由版本号决定，URL 不变内容就不变 → 允许浏览器长期缓存（1 年）。手机加载一次后
      留存本地，后续重载直接从本地取，不再重复请求，流量/加载几乎归零。
      版本号由 get_static_ver() 按静态文件修改时间实时计算，改完文件保存即自动失效缓存，
      无需重启、也无需手动 bump 版本号；手动 bump mobile.js 的 APP_VERSION 仍可强制刷新
      所有资源（URL 会随版本号变化）。
    - 其余（HTML、未带版本号的 /static/、API 响应）：禁止缓存，确保改完立即生效。
    """
    ct = response.content_type or ""
    # 注意：Flask 静态文件实际 content-type 是 text/javascript / text/css，
    # 而非 application/javascript，故用子串匹配。
    is_static_asset = ("javascript" in ct or "css" in ct or ct.startswith("image/"))
    has_version = request.path.startswith("/assets/v") or bool(request.args.get("v"))
    # 带版本的静态资源 -> 长期缓存（不再重复下载）
    if has_version and is_static_asset:
        response.headers["Cache-Control"] = "public, max-age=31536000"
        response.headers.pop("Pragma", None)
        response.headers.pop("Expires", None)
        return response
    # 其余 -> 禁止缓存
    if (ct.startswith("text/html") or is_static_asset):
        response.cache_control.no_store = True
        response.cache_control.no_cache = True
        response.cache_control.must_revalidate = True
        response.cache_control.max_age = 0
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.context_processor
def inject_static_ver():
    """把静态资源版本号注入所有模板。版本号由 get_static_ver() 实时计算（基于关键静态文件
    的修改时间），因此改完 CSS/JS/图片「保存」即可自动失效浏览器缓存，无需重启服务、
    也无需手动 bump 版本号。"""
    return dict(static_ver=get_static_ver())


# 带版本号的静态资源路由：版本号在路径中（/assets/v2017/css/mobile.css），
# 绕过 Android WebView 按路径缓存、忽略 ?v= 查询串导致的旧 CSS/JS 不更新问题。
# 用 /assets/ 前缀避开 Flask 默认 /static/ 路由的匹配冲突。
@app.route("/assets/v<string:ver>/<path:filename>")
def static_versioned(ver, filename):
    return send_from_directory("static", filename)


# ==================== 登录门禁（多用户：方案 B 独立账号） ====================
# 未登录访问受保护页面/API 时：页面跳登录页，API 返回 401。
# 所有业务数据按 session["user_id"] 严格隔离。

# 无需登录即可访问的路径前缀（白名单）
_PUBLIC_PREFIXES = (
    "/login",
    "/logout",
    "/api/login",
    "/api/logout",
    "/api/me",
    "/api/auth/login",       # 钉钉 H5 免登
    "/api/register",         # 手机号自助注册
    "/api/forgot-password",  # 忘记密码：未登录也可提交（待管理员审核）
    "/static/",
    "/assets/",              # 带路径版本号的静态资源（绕过 WebView 按路径缓存忽略 ?v）
    "/download",             # 项目下载
    "/download-project",
)


def current_user_id():
    """返回当前登录用户 id（未登录为 None）。"""
    return session.get("user_id")


# 跨域白名单：GitHub Pages 静态托管 + 本地开发。
_ALLOWED_ORIGINS = [
    "https://yhstc1.github.io",
    "http://localhost:5000",
    "http://localhost:8080",
]


@app.before_request
def _handle_cors_preflight():
    """在登录拦截之前响应 OPTIONS 预检，避免跨域 POST/PUT 被 401。"""
    if request.method != "OPTIONS":
        return None
    origin = request.headers.get("Origin", "")
    resp = jsonify({})
    if origin in _ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return resp


@app.after_request
def _add_cors_headers(response):
    """为跨域请求补 CORS 头。必须在 caching_policy 之后执行。"""
    origin = request.headers.get("Origin", "")
    if origin in _ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.before_request
def _require_login():
    path = request.path
    if any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
        return None
    if session.get("user_id"):
        return None
    # 未登录：页面请求跳登录页，API 请求返回 401
    if path.startswith("/api/"):
        return jsonify({"error": "未登录", "login_url": "/login"}), 401
    return redirect("/login")


def _login_as(user):
    """把 users 行写入 session，建立登录态。"""
    session.permanent = True
    session["user_id"] = user["id"]
    session["username"] = user.get("username")
    session["phone"] = user.get("phone")
    session["display_name"] = user.get("display_name")
    session["is_admin"] = bool(user.get("is_admin"))


def _require_admin():
    """管理员鉴权：未登录或非管理员返回错误响应，否则返回 None。"""
    if not session.get("user_id"):
        return jsonify({"error": "未登录"}), 401
    conn = get_db()
    row = conn.execute("SELECT is_admin FROM users WHERE id=?", (session["user_id"],)).fetchone()
    conn.close()
    if not row or not row["is_admin"]:
        return jsonify({"error": "无权限，仅管理员可操作"}), 403
    return None


# ==================== 钉钉 H5 免登辅助 ====================
import urllib.request as _urllib
import urllib.error as _urllib_err

_DING_APP_KEY = os.environ.get("DING_APP_KEY", "")
_DING_APP_SECRET = os.environ.get("DING_APP_SECRET", "")
_ding_token_cache = {"token": None, "exp": 0}


def _ding_get_app_token():
    """获取企业内部应用 access_token（带缓存）。"""
    now = time.time()
    if _ding_token_cache["token"] and _ding_token_cache["exp"] > now + 60:
        return _ding_token_cache["token"]
    url = "https://oapi.dingtalk.com/gettoken?appkey=%s&appsecret=%s" % (
        urllib.parse.quote(_DING_APP_KEY), urllib.parse.quote(_DING_APP_SECRET))
    req = _urllib.Request(url, headers={"Content-Type": "application/json"})
    with _urllib.urlopen(req, timeout=10) as resp:
        d = json.loads(resp.read().decode("utf-8"))
    if d.get("errcode") != 0:
        raise RuntimeError("dingtalk gettoken failed: %s" % d)
    _ding_token_cache["token"] = d["access_token"]
    _ding_token_cache["exp"] = now + int(d.get("expires_in", 7200))
    return d["access_token"]


def _ding_userid_by_code(auth_code):
    """用免登 authCode 换钉钉 userId（优先新版 topapi/v2/user/getuserinfo，兼容老接口）。"""
    token = _ding_get_app_token()
    # 新版
    req = _urllib.Request(
        "https://oapi.dingtalk.com/topapi/v2/user/getuserinfo?access_token=%s" % urllib.parse.quote(token),
        data=json.dumps({"code": auth_code}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with _urllib.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8"))
    except _urllib_err.URLError:
        d = {}
    if d.get("errcode") == 0 and d.get("result", {}).get("userid"):
        return d["result"]["userid"]
    # 兼容老接口
    url2 = "https://oapi.dingtalk.com/user/getuserinfo?access_token=%s&code=%s" % (
        urllib.parse.quote(token), urllib.parse.quote(auth_code))
    req2 = _urllib.Request(url2, headers={"Content-Type": "application/json"})
    with _urllib.urlopen(req2, timeout=10) as resp2:
        d2 = json.loads(resp2.read().decode("utf-8"))
    if d2.get("errcode") != 0:
        raise RuntimeError("dingtalk getuserinfo failed: %s / %s" % (d, d2))
    return d2.get("userid")


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """首页 - 自动识别移动端跳转（PC 端无仪表盘，落在事项看板，与移动端默认页一致）"""
    ua = request.headers.get("User-Agent", "").lower()
    if any(x in ua for x in ["mobile", "android", "iphone", "harmony", "phone"]):
        return redirect("/m")
    return redirect("/tasks")


@app.route("/customers")
def customers_page():
    """客户管理页"""
    return render_template("customers.html")


@app.route("/map")
def map_page():
    """地图视图页"""
    return render_template("map.html")


@app.route("/tasks")
def tasks_page():
    """事项看板页"""
    return render_template("tasks.html")


@app.route("/business")
def business_page():
    """业务管理页"""
    return render_template("business.html")


@app.route("/reports")
def reports_page():
    """报告页"""
    return render_template("reports.html")


@app.route("/settings")
def settings_page():
    """设置页"""
    return render_template("settings.html")


# ==================== 客户 API ====================

@app.route("/api/customers", methods=["GET"])
def get_customers():
    """获取客户列表"""
    conn = get_db()
    search = request.args.get("search", "")
    category = request.args.get("category", "")

    ym = _current_ym()
    sql = """SELECT c.*, COALESCE(ci.count, 0) AS checkin_month
             FROM customers c
             LEFT JOIN checkins ci ON ci.customer_id = c.id AND ci.year_month = ?
             WHERE c.user_id = ?"""
    params = [ym, current_user_id()]
    if search:
        sql += " AND (c.name LIKE ? OR c.company LIKE ? OR c.contact LIKE ? OR c.address LIKE ? OR c.phone LIKE ?)"
        params.extend([f"%{search}%"] * 5)
    if category:
        sql += " AND c.category = ?"
        params.append(category)
    sql += " ORDER BY CASE c.priority WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 ELSE 4 END, c.updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/customers/category-counts", methods=["GET"])
def customer_category_counts():
    """统计当前用户各客户分类数量（空分类归入普通客户），用于客户管理分类筛选显示数量"""
    conn = get_db()
    rows = conn.execute(
        "SELECT COALESCE(NULLIF(category, ''), '普通客户') AS cat, COUNT(*) AS n "
        "FROM customers WHERE user_id=? GROUP BY cat",
        (current_user_id(),)
    ).fetchall()
    conn.close()
    return jsonify({r["cat"]: r["n"] for r in rows})


@app.route("/api/customers/subtask-counts", methods=["GET"])
def customer_subtask_counts():
    """统计当前用户每个客户的子待办数量：{customer_id: count}，仅含有子待办的客户"""
    conn = get_db()
    rows = conn.execute(
        "SELECT t.customer_id AS cid, COUNT(s.id) AS cnt "
        "FROM subtasks s JOIN tasks t ON s.task_id = t.id "
        "WHERE t.user_id=? GROUP BY t.customer_id",
        (current_user_id(),)
    ).fetchall()
    conn.close()
    return jsonify({r["cid"]: r["cnt"] for r in rows})


@app.route("/api/customers", methods=["POST"])
def add_customer():
    """新增客户"""
    data = request.json
    conn = get_db()
    uid = current_user_id()

    # 去重：同一公司名（归一化后）已存在则直接拦截（仅当前用户名下）
    existing_id = company_exists(conn, data.get("company", ""), user_id=uid)
    if existing_id:
        conn.close()
        return jsonify({"error": "该客户已存在", "existing_id": existing_id}), 409

    # 如果没有经纬度，尝试地理编码
    if not data.get("latitude") or not data.get("longitude"):
        if data.get("address"):
            coords = geocode(data["address"])
            if coords:
                data["latitude"] = coords[0]
                data["longitude"] = coords[1]

    cur = conn.execute("""
        INSERT INTO customers (name, company, phone, email, address, latitude, longitude, category, priority, notes, contact, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name", ""), data.get("company", ""), data.get("phone", ""),
        data.get("email", ""), data.get("address", ""), data.get("latitude"),
        data.get("longitude"), data.get("category", ""),
        data.get("priority", "低"), data.get("notes", ""), data.get("contact", ""),
        uid
    ))
    conn.commit()
    cid = cur.lastrowid
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return jsonify(dict(customer)), 201


@app.route("/api/customers/<int:cid>", methods=["GET"])
def get_customer(cid):
    """获取单个客户（仅限本人）"""
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ? AND user_id = ?", (cid, current_user_id())
    ).fetchone()
    if not customer:
        conn.close()
        return jsonify({"error": "客户不存在"}), 404
    tasks = conn.execute("SELECT * FROM tasks WHERE customer_id = ? ORDER BY due_date", (cid,)).fetchall()
    conn.close()
    return jsonify({"customer": dict(customer), "tasks": [dict(t) for t in tasks]})


@app.route("/api/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    """更新客户（部分更新：仅覆盖请求中提供的字段，未提供的保留原值）"""
    data = request.json or {}
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM customers WHERE id = ? AND user_id = ?", (cid, current_user_id())
    ).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "客户不存在"}), 404

    cols = ("name", "company", "phone", "email", "address",
            "latitude", "longitude", "category", "priority", "notes", "contact")
    merged = {k: data.get(k, existing[k]) for k in cols}

    # 去重：若公司名被改成另一个已存在客户，则拦截（仅当前用户名下）
    if data.get("company") is not None and normalize_company(data.get("company")) != normalize_company(existing["company"]):
        dup_id = company_exists(conn, data.get("company"), exclude_id=cid, user_id=current_user_id())
        if dup_id:
            conn.close()
            return jsonify({"error": "该客户已存在", "existing_id": dup_id}), 409

    # 地址变化且无手动经纬度 -> 重新地理编码
    if data.get("address") and data.get("address") != existing["address"]:
        coords = geocode(data["address"])
        if coords:
            merged["latitude"], merged["longitude"] = coords[0], coords[1]

    conn.execute("""
        UPDATE customers SET
            name=?, company=?, phone=?, email=?, address=?, latitude=?, longitude=?,
            category=?, priority=?, notes=?, contact=?, updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        merged["name"], merged["company"], merged["phone"],
        merged["email"], merged["address"], merged["latitude"],
        merged["longitude"], merged["category"], merged["priority"], merged["notes"],
        merged["contact"], cid
    ))
    conn.commit()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return jsonify(dict(customer))


@app.route("/api/customers/<int:cid>", methods=["DELETE"])
def delete_customer(cid):
    """删除客户（仅限本人）。
    业务(businesses)/事项(tasks) 经外键 CASCADE 同步删除（get_db 已开 PRAGMA foreign_keys=ON）；
    打卡(checkins) 表无外键，需手动清除，否则残留指向已删客户的孤立记录。"""
    conn = get_db()
    conn.execute("DELETE FROM checkins WHERE customer_id = ?", (cid,))
    conn.execute("DELETE FROM customers WHERE id = ? AND user_id = ?", (cid, current_user_id()))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


# 客户导入模板列（顺序即 CSV 列顺序）
CUSTOMER_IMPORT_COLUMNS = ["公司名称", "法人", "联系人", "联系方式", "邮箱", "地址", "分类", "优先级", "备注"]


@app.route("/api/customers/template", methods=["GET"])
def customer_template():
    """下载客户批量导入 CSV 模板（UTF-8 with BOM，Excel 可直接打开）"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CUSTOMER_IMPORT_COLUMNS)
    # 示例行
    writer.writerow(["示例科技有限公司", "张三（法人）", "李四（联系人）", "138-0000-0000", "zhangsan@example.com",
                     "上海市浦东新区张江路100号", "核心要客", "高", "这是示例，可删除"])
    writer.writerow(["", "", "", "", "", "", "TOP20", "中", ""])
    csv_bytes = "\ufeff" + buf.getvalue()
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=customer_import_template.csv"}
    )


@app.route("/api/customers/import", methods=["POST"])
def customer_import():
    """批量导入客户（上传 CSV）"""
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "文件为空"}), 400

    raw = f.read()
    # 兼容 UTF-8(BOM) 与 GBK
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return jsonify({"error": "无法识别文件编码，请用 UTF-8 或 GBK 保存"}), 400

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return jsonify({"error": "文件无内容"}), 400

    header = [h.strip().replace('\ufeff', '') for h in rows[0]]
    valid_categories = {"核心要客", "TOP20", "普通客户"}
    conn = get_db()
    uid = current_user_id()
    success, failed, skipped, errors = 0, 0, 0, []

    # 已存在（数据库 + 本批次内）的归一化公司名集合，用于去重（仅当前用户名下）
    existing_norms = {
        n for n in (normalize_company(r["company"]) for r in
                    conn.execute("SELECT company FROM customers WHERE user_id=?", (uid,)).fetchall())
        if n
    }

    # 同一地址只地理编码一次（循环内 HTTP IO 去重），大幅减少外部请求次数
    geocoded_cache = {}

    for idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # 跳过空行
        record = _parse_csv_record(header, row)
        company = record.get("公司名称", "")
        legal = record.get("法人", "")
        contact = record.get("联系人", "")
        if not legal and not company:
            failed += 1
            errors.append(f"第{idx}行：公司名称和法人均为空，跳过")
            continue

        # 去重：同一公司名（归一化后）已存在则跳过，不报错
        norm = normalize_company(company)
        if norm and norm in existing_norms:
            skipped += 1
            errors.append(f"第{idx}行：客户「{company}」已存在，已跳过")
            continue

        category = (record.get("分类", "") or "").strip()
        if category not in valid_categories:
            category = "普通客户"  # 非法/留空分类统一归入普通客户
        priority = record.get("优先级", "中") or "中"
        if priority not in {"高", "中", "低"}:
            priority = "中"

        # 地址 -> 经纬度（最佳努力，失败不影响导入）
        lat = lon = None
        address = record.get("地址", "")
        if address:
            try:
                # 同一地址复用缓存结果，避免循环内重复发起 HTTP 地理编码请求
                if address in geocoded_cache:
                    coords = geocoded_cache[address]
                else:
                    coords = geocode(address)
                    geocoded_cache[address] = coords
                    time.sleep(0.3)  # 仅在实际发起请求时节流，避免触发地理编码服务限流
                if coords:
                    lat, lon = coords[0], coords[1]
            except Exception:
                pass

        try:
            conn.execute("""
                INSERT INTO customers (name, company, phone, email, address, latitude, longitude, category, priority, notes, contact, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                legal or company, company, record.get("联系方式", ""),
                record.get("邮箱", ""), address, lat, lon,
                category, priority, record.get("备注", ""), contact, uid
            ))
            success += 1
            if norm:
                existing_norms.add(norm)  # 本批次内也去重
        except Exception as e:
            failed += 1
            errors.append(f"第{idx}行：{e}")

    conn.commit()
    conn.close()
    msg = f"导入完成：成功 {success} 条，跳过重复 {skipped} 条，失败 {failed} 条"
    return jsonify({
        "message": msg,
        "success": success, "skipped": skipped, "failed": failed, "errors": errors[:20]
    })


# 业务导入模板列（顺序即 CSV 列顺序）
BUSINESS_IMPORT_COLUMNS = ["公司名称", "业务类型", "业务套餐", "合同编码", "业务号码", "合同金额", "开始时间", "结束时间", "业务地址", "备注"]


@app.route("/api/business/template", methods=["GET"])
def business_template():
    """下载业务批量导入 CSV 模板（UTF-8 with BOM，Excel 可直接打开）"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(BUSINESS_IMPORT_COLUMNS)
    # 示例行
    writer.writerow(["示例科技有限公司", "互联网专线", "标准套餐A", "HT-2026-001", "13800000000",
                     "120000", "2026-01-01", "2026-12-31", "上海市浦东新区张江路100号", "示例业务说明"])
    writer.writerow(["", "电路", "", "", "", "", "", "", "", ""])
    csv_bytes = "\ufeff" + buf.getvalue()
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=business_import_template.csv"}
    )


def _parse_csv_record(header, row):
    """把 CSV 一行转成 {中文列名: 值} 字典（按列名对齐；row 短于 header 时缺失列视为空串）。"""
    return dict(zip(header, (c.strip() for c in row)))


def _parse_business_record(header, row):
    """把 CSV 一行转成 {中文列名: 值} 字典。"""
    return _parse_csv_record(header, row)


def _decode_csv_file(f):
    """读取上传文件并解码为文本，兼容 UTF-8(BOM)/UTF-8/GBK。失败返回 None。"""
    raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def fuzzy_match_company(name, candidate_list, candidate_sets=None, limit=5):
    """对公司名做模糊匹配，返回候选客户列表（含相似度分数）。
    candidate_list: [(id, company), ...]（当前用户名下客户）。
    candidate_sets: 预计算结构 [(id, company, norm, norm_set), ...]，由调用方在批量匹配前构建一次，
                   避免对每一行重复归一化与构造集合（原为 O(行数×候选数) 的重复计算）。
    评分：精确 100；包含关系 90；否则按字符重叠率（>=0.5 才计入）。"""
    norm = normalize_company(name or "")
    if not norm or not candidate_list:
        return []
    norm_set = set(norm)
    # 向后兼容：未传预计算结构时，现场构造（行为一致，仅性能略差）
    if candidate_sets is None:
        candidate_sets = [(cid, comp, normalize_company(comp or ""), set(normalize_company(comp or "")))
                          for cid, comp in candidate_list]
    scored = []
    for cid, comp, cn, cn_set in candidate_sets:
        if not cn:
            continue
        if cn == norm:
            scored.append((100, cid, comp))
            continue
        if cn in norm or norm in cn:
            scored.append((90, cid, comp))
            continue
        inter = len(norm_set & cn_set)
        ratio = inter / max(len(norm), len(cn))
        if ratio >= 0.5:
            scored.append((int(ratio * 100), cid, comp))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": s[1], "company": s[2], "score": s[0]} for s in scored[:limit]]


@app.route("/api/business/import/preview", methods=["POST"])
def business_import_preview():
    """批量导入业务（第一阶段：解析 + 匹配分析，不写库）。
    返回每行的匹配状态：exact(精确匹配)/fuzzy(模糊候选)/new(需新增)/duplicate(业务号重复)/error。"""
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "文件为空"}), 400
    text = _decode_csv_file(f)
    if text is None:
        return jsonify({"error": "无法识别文件编码，请用 UTF-8 或 GBK 保存"}), 400

    # 流式读取：不把整张表 materialize 成 list，逐行迭代，内存只保留单行 + 解析结果
    reader = csv.reader(io.StringIO(text))
    try:
        first = next(reader)
    except StopIteration:
        return jsonify({"error": "文件无内容"}), 400
    header = [h.strip().replace('\ufeff', '') for h in first]
    conn = get_db()
    uid = current_user_id()

    # 去重依据：当前用户名下已有的业务号（按业务号去重）
    existing_bn = {
        bn for bn in ((r["number"] or "").strip() for r in
                      conn.execute("SELECT number FROM businesses WHERE user_id=?", (uid,)).fetchall())
        if bn
    }

    # 客户精确匹配表 + 模糊候选列表
    customers = conn.execute("SELECT id, company, name FROM customers WHERE user_id=?", (uid,)).fetchall()
    company_norm_to_id = {}
    for r in customers:
        n = normalize_company(r["company"] or "")
        if n and n not in company_norm_to_id:
            company_norm_to_id[n] = r["id"]
    candidate_list = [(r["id"], r["company"] or "") for r in customers]
    # 批量导入前一次性预计算候选归一化集合（O(候选数)），供每一行 fuzzy_match 复用，
    # 避免对每一行都重复归一化并构造集合（原为 O(行数×候选数) 的重复计算）。
    candidate_sets = [(cid, comp, normalize_company(comp or ""), set(normalize_company(comp or "")))
                      for cid, comp in candidate_list]

    result_rows = []
    for idx, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        rec = _parse_csv_record(header, row)
        company = rec.get("公司名称", "").strip()
        bn = rec.get("业务号码", "").strip()
        if not company:
            result_rows.append({"index": idx, "status": "error", "message": "公司名称为空", "record": rec})
            continue
        if bn and bn in existing_bn:
            result_rows.append({"index": idx, "status": "duplicate", "message": "业务号 %s 已存在，将跳过" % bn, "record": rec})
            continue
        norm = normalize_company(company)
        if norm in company_norm_to_id:
            result_rows.append({"index": idx, "status": "exact", "customer_id": company_norm_to_id[norm], "action": "merge", "record": rec})
            continue
        cands = fuzzy_match_company(company, candidate_list, candidate_sets)
        if cands:
            result_rows.append({"index": idx, "status": "fuzzy", "candidates": cands, "action": "merge", "record": rec})
        else:
            result_rows.append({"index": idx, "status": "new", "action": "new", "record": rec})

    conn.close()
    stats = {
        "total": len(result_rows),
        "exact": sum(1 for r in result_rows if r["status"] == "exact"),
        "fuzzy": sum(1 for r in result_rows if r["status"] == "fuzzy"),
        "new": sum(1 for r in result_rows if r["status"] == "new"),
        "duplicate": sum(1 for r in result_rows if r["status"] == "duplicate"),
        "error": sum(1 for r in result_rows if r["status"] == "error"),
    }
    return jsonify({"rows": result_rows, "stats": stats})


@app.route("/api/business/import/commit", methods=["POST"])
def business_import_commit():
    """批量导入业务（第二阶段：按用户在前端确认的方案落库）。
    每条 row 含 record(原始字段) + action(merge|new) + customer_id(merge 时)。
    去重依据为业务号；落库后对受影响客户重新计算优先级。"""
    data = request.json or {}
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "无导入数据"}), 400
    conn = get_db()
    uid = current_user_id()
    existing_bn = {
        bn for bn in ((r["number"] or "").strip() for r in
                      conn.execute("SELECT number FROM businesses WHERE user_id=?", (uid,)).fetchall())
        if bn
    }

    success = skipped = failed = 0
    errors = []
    affected = set()

    for item in rows:
        rec = item.get("record") or {}
        action = item.get("action", "new")
        company = (rec.get("公司名称", "") or "").strip()
        bn = (rec.get("业务号码", "") or "").strip()
        if not company:
            failed += 1
            errors.append("公司名称为空，跳过")
            continue
        if bn and bn in existing_bn:
            skipped += 1
            errors.append("业务号 %s 已存在，跳过" % bn)
            continue

        cid = None
        if action == "merge":
            cid = item.get("customer_id") or rec.get("customer_id")
            if cid is not None:
                hit = conn.execute("SELECT 1 FROM customers WHERE id=? AND user_id=?", (cid, uid)).fetchone()
                if not hit:
                    cid = None
        if action == "new" or not cid:
            cur = conn.execute(
                "INSERT INTO customers (company, name, category, priority, user_id, created_at, updated_at, source) "
                "VALUES (?, '', '普通客户', '低', ?, datetime('now','localtime'), datetime('now','localtime'), 'auto_business_import')",
                (company, uid),
            )
            cid = cur.lastrowid

        amount_raw = (rec.get("合同金额", "") or "").strip()
        contract_amount = None
        if amount_raw:
            try:
                contract_amount = float(amount_raw.replace(",", "").replace("¥", "").strip())
            except ValueError:
                contract_amount = None
        try:
            conn.execute(
                "INSERT INTO businesses (customer_id, company_name, business_address, number, "
                "contract_code, business_type, business_package, contract_amount, start_date, end_date, notes, user_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, company, rec.get("业务地址", ""), bn, rec.get("合同编码", ""),
                 rec.get("业务类型", ""), rec.get("业务套餐", ""), contract_amount,
                 rec.get("开始时间", ""), rec.get("结束时间", ""), rec.get("备注", ""),
                 uid),
            )
            success += 1
            affected.add(cid)
            if bn:
                existing_bn.add(bn)
        except Exception as e:
            failed += 1
            errors.append(str(e))

    conn.commit()
    for cid in affected:
        try:
            recalc_priority(cid)
        except Exception:
            pass
    conn.close()
    msg = "导入完成：成功 %d 条，跳过重复 %d 条，失败 %d 条；已重新计算 %d 个客户优先级" % (
        success, skipped, failed, len(affected))
    return jsonify({"message": msg, "success": success, "skipped": skipped, "failed": failed, "errors": errors[:20]})


@app.route("/api/customers/<int:cid>/businesses", methods=["GET"])
def get_customer_businesses(cid):
    """获取某客户的业务列表（仅限本人客户）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM businesses WHERE customer_id = ? AND user_id = ? ORDER BY start_date DESC, id DESC",
        (cid, current_user_id()),
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/customers/<int:cid>/bundle", methods=["GET"])
def get_customer_bundle(cid):
    """客户详情一站式数据：一次网络往返返回 客户+业务+事项+子待办，替代移动端原本最多 4 次并行请求。
    字段形状与既有端点保持一致：businesses=原始业务行（同 /businesses），tasks=本客户事项（同 /customers/<id>），
    subtasks=当前用户全部子待办（同 /tasks/subtasks）。"""
    conn = get_db()
    uid = current_user_id()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id = ? AND user_id = ?", (cid, uid)
    ).fetchone()
    if not customer:
        conn.close()
        return jsonify({"error": "客户不存在"}), 404
    businesses = conn.execute(
        "SELECT * FROM businesses WHERE customer_id = ? AND user_id = ? ORDER BY start_date DESC, id DESC",
        (cid, uid),
    ).fetchall()
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE customer_id = ? ORDER BY due_date", (cid,)
    ).fetchall()
    subtasks = conn.execute(
        "SELECT s.* FROM subtasks s JOIN tasks t ON s.task_id = t.id WHERE t.user_id = ?", (uid,)
    ).fetchall()
    conn.close()
    return jsonify({
        "customer": dict(customer),
        "businesses": [dict(b) for b in businesses],
        "tasks": [dict(t) for t in tasks],
        "subtasks": [dict(s) for s in subtasks],
    })


# ==================== 业务 API ====================

def _int_or_none(v):
    """把请求里的整数（如 parent_id）安全转为 int 或 None。"""
    if v in (None, "", 0):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


@app.route("/api/business", methods=["GET"])
def get_businesses():
    """获取业务列表（支持按公司名称/合同编码/号码/业务类型模糊搜索）"""
    conn = get_db()
    search = request.args.get("search", "")
    sql = """
        SELECT b.*, c.name AS customer_name
        FROM businesses b LEFT JOIN customers c ON b.customer_id = c.id
        WHERE b.user_id = ?
    """
    params = [current_user_id()]
    if search:
        sql += " AND (b.company_name LIKE ? OR b.contract_code LIKE ? OR b.number LIKE ? OR b.business_type LIKE ?)"
        params.extend([f"%{search}%"] * 4)
    sql += " ORDER BY b.updated_at DESC, b.id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/business", methods=["POST"])
def add_business():
    """新增业务"""
    data = request.json
    conn = get_db()
    uid = current_user_id()
    parent_id = _int_or_none(data.get("parent_id"))
    cur = conn.execute("""
        INSERT INTO businesses (customer_id, company_name, business_address, number,
            contract_code, business_type, contract_amount, start_date, end_date, notes,
            business_package, user_id, business_level, date, user_name, parent_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("customer_id") or None, data.get("company_name", ""),
        data.get("business_address", ""), (data.get("number") or data.get("business_number") or ""),
        data.get("contract_code", ""), data.get("business_type", ""),
        data.get("contract_amount"), data.get("start_date", ""),
        data.get("end_date", ""), data.get("notes", ""),
        data.get("business_package", ""), uid,
        data.get("business_level", ""), data.get("date", ""),
        data.get("user_name", ""), parent_id
            ))
    conn.commit()
    bid = cur.lastrowid
    cid = data.get("customer_id")
    if cid:
        recalc_priority(cid)
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route("/api/business/<int:bid>", methods=["GET"])
def get_business(bid):
    """获取单个业务（仅限本人）"""
    conn = get_db()
    row = conn.execute("SELECT * FROM businesses WHERE id = ? AND user_id = ?", (bid, current_user_id())).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "业务不存在"}), 404
    return jsonify(dict(row))


@app.route("/api/business/<int:bid>", methods=["PUT"])
def update_business(bid):
    """更新业务（部分更新：仅覆盖请求中提供的字段，未提供的保留原值）"""
    data = request.json or {}
    conn = get_db()
    existing = conn.execute("SELECT * FROM businesses WHERE id = ? AND user_id = ?", (bid, current_user_id())).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "业务不存在"}), 404
    cols = ("customer_id", "company_name", "business_address", "number",
            "contract_code", "business_type", "business_package", "contract_amount", "start_date",
            "end_date", "notes", "business_level", "date", "user_name", "parent_id")
    merged = {k: data.get(k, existing[k]) for k in cols}
    merged["parent_id"] = _int_or_none(data.get("parent_id", existing["parent_id"]))
    old_cid = existing["customer_id"]
    new_cid = merged["customer_id"] or None
    conn.execute("""
        UPDATE businesses SET
            customer_id=?, company_name=?, business_address=?, number=?,
            contract_code=?, business_type=?, business_package=?, contract_amount=?, start_date=?, end_date=?,
            notes=?, business_level=?, date=?, user_name=?, parent_id=?, updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        merged["customer_id"], merged["company_name"], merged["business_address"], merged["number"],
        merged["contract_code"], merged["business_type"], merged["business_package"],
        merged["contract_amount"], merged["start_date"],
        merged["end_date"], merged["notes"], merged["business_level"], merged["date"], merged["user_name"],
        merged["parent_id"], bid
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    # 重算关联客户的优先级（新旧都算）
    if new_cid:
        recalc_priority(new_cid)
    if old_cid and old_cid != new_cid:
        recalc_priority(old_cid)
        # 旧客户若为「导入业务时自动添加的」且变空则自动清理
        cleanup_auto_imported_customer(old_cid)
    return jsonify(dict(row))


@app.route("/api/business/<int:bid>", methods=["DELETE"])
def delete_business(bid):
    """删除业务（仅限本人）"""
    conn = get_db()
    row = conn.execute("SELECT customer_id FROM businesses WHERE id = ? AND user_id = ?", (bid, current_user_id())).fetchone()
    cid = row["customer_id"] if row else None
    conn.execute("DELETE FROM businesses WHERE id = ? AND user_id = ?", (bid, current_user_id()))
    conn.commit()
    conn.close()
    if cid:
        recalc_priority(cid)
        # 业务删除后，若客户为「导入业务时自动添加的」且变空则自动清理
        cleanup_auto_imported_customer(cid)
    return jsonify({"message": "已删除"})


# ==================== 台账 API（2.6.1 起：台账已并入 businesses，这里作为兼容适配层，读写均落在 businesses 上）====================

def _biz_to_ledger_dict(r, conn, parent_numbers=None):
    """把 businesses 一行转换为台账接口兼容的字段形状（company/package_name/package_type/parent_number）。

    parent_numbers: 可选 {business_id: number} 映射，用于批量预取父卡号，避免逐行查库（N+1）。
    传入时优先用映射，缺失才回退单查（兼容单条调用场景）。
    """
    d = dict(r)
    pid = d.get("parent_id")
    parent_number = ""
    if pid:
        if parent_numbers is not None:
            parent_number = parent_numbers.get(pid, "")
        else:
            pr = conn.execute("SELECT number FROM businesses WHERE id=?", (pid,)).fetchone()
            parent_number = pr["number"] if pr else ""
    return {
        "id": d["id"], "user_id": d.get("user_id"), "date": d.get("date"),
        "number": d.get("number"), "company": d.get("company_name"),
        "user_name": d.get("user_name"), "package_name": d.get("business_level"),
        "package_type": d.get("business_type"), "parent_number": parent_number,
        "customer_id": d.get("customer_id"), "created_at": d.get("created_at"),
        "updated_at": d.get("updated_at"),
    }


def _resolve_parent_id(conn, uid, parent_number, package_type):
    """把关联主卡号码（数智惠企/冰激凌 的 number）解析为 businesses.id。"""
    if not parent_number:
        return None
    pr = conn.execute(
        "SELECT id FROM businesses WHERE user_id=? AND number=? AND business_type IN ('数智惠企','冰激凌')",
        (uid, parent_number)
    ).fetchone()
    return pr["id"] if pr else None


@app.route("/api/ledgers", methods=["GET"])
def get_ledgers():
    """获取台账列表（兼容旧桌面端：从 businesses 读取并映射为台账字段）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM businesses WHERE user_id = ? ORDER BY created_at DESC",
        (current_user_id(),)
    ).fetchall()
    # 批量预取父卡号，避免 _biz_to_ledger_dict 逐行查库（N+1 -> 1 次查询）
    parent_ids = {r["parent_id"] for r in rows if r["parent_id"]}
    parent_numbers = {}
    if parent_ids:
        ph = ",".join("?" * len(parent_ids))
        parent_numbers = {
            pr["id"]: pr["number"]
            for pr in conn.execute(
                "SELECT id, number FROM businesses WHERE id IN (%s)" % ph,
                list(parent_ids)
            ).fetchall()
        }
    out = [_biz_to_ledger_dict(r, conn, parent_numbers) for r in rows]
    conn.close()
    return jsonify(out)


@app.route("/api/customers/<int:cid>/ledgers", methods=["GET"])
def get_customer_ledgers(cid):
    """获取某客户关联的台账（兼容旧桌面端）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM businesses WHERE user_id = ? AND customer_id = ? ORDER BY created_at DESC",
        (current_user_id(), cid)
    ).fetchall()
    parent_ids = {r["parent_id"] for r in rows if r["parent_id"]}
    parent_numbers = {}
    if parent_ids:
        ph = ",".join("?" * len(parent_ids))
        parent_numbers = {
            pr["id"]: pr["number"]
            for pr in conn.execute(
                "SELECT id, number FROM businesses WHERE id IN (%s)" % ph,
                list(parent_ids)
            ).fetchall()
        }
    out = [_biz_to_ledger_dict(r, conn, parent_numbers) for r in rows]
    conn.close()
    return jsonify(out)


@app.route("/api/ledgers", methods=["POST"])
def add_ledger():
    """新增台账记录（写入 businesses）"""
    data = request.json
    cid = data.get("customer_id")
    cid = int(cid) if cid not in (None, "", 0) else None
    conn = get_db()
    uid = current_user_id()
    package_type = data.get("package_type", "")
    parent_id = _resolve_parent_id(conn, uid, (data.get("parent_number") or "").strip(), package_type)
    cur = conn.execute("""
        INSERT INTO businesses (user_id, date, number, company_name, user_name, business_level,
            business_type, parent_id, customer_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        uid, data.get("date", ""), data.get("number", ""), data.get("company", ""),
        data.get("user_name", ""), data.get("package_name", ""),
        package_type, parent_id, cid
            ))
    conn.commit()
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (cur.lastrowid,)).fetchone()
    out = _biz_to_ledger_dict(row, conn)
    conn.close()
    return jsonify(out), 201


@app.route("/api/ledgers/<int:lid>", methods=["DELETE"])
def delete_ledger(lid):
    """删除台账记录（删除 businesses）"""
    conn = get_db()
    conn.execute("DELETE FROM businesses WHERE id = ? AND user_id = ?", (lid, current_user_id()))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


@app.route("/api/ledgers/<int:lid>", methods=["PUT"])
def update_ledger(lid):
    """更新台账记录（更新 businesses）"""
    data = request.json
    conn = get_db()
    cid = data.get("customer_id")
    cid = int(cid) if cid not in (None, "", 0) else None
    parent_id = _resolve_parent_id(conn, current_user_id(), (data.get("parent_number") or "").strip(), data.get("package_type", ""))
    conn.execute("""
        UPDATE businesses SET date=?, number=?, company_name=?, user_name=?, business_level=?,
            business_type=?, parent_id=?, customer_id=?, updated_at=datetime('now','localtime')
        WHERE id=? AND user_id=?
    """, (
        data.get("date", ""),
        data.get("number", ""),
        data.get("company", ""),
        data.get("user_name", ""),
        data.get("package_name", ""),
        data.get("package_type", ""),
        parent_id,
        cid,
        lid, current_user_id()
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (lid,)).fetchone()
    out = _biz_to_ledger_dict(row, conn)
    conn.close()
    return jsonify(out)


LEDGER_IMPORT_COLUMNS = ["日期", "号码", "公司", "使用人", "层级", "套餐类型", "关联主卡"]
LEDGER_ENUM = ['数智惠企', '冰激凌', '魔方卡', '副卡', '宽带', '固话']
LEDGER_MAIN_TYPES = ['数智惠企', '冰激凌']
LEDGER_CHILD_TYPES = ['副卡', '宽带', '固话']


def validate_ledger_import_row(rec, main_numbers):
    """校验单行导入数据。返回 (package_type, parent_number, error_msg)；
    error_msg 非空表示该行不合法。套餐类型必须为枚举，子卡必须关联已存在的主卡。"""
    package_type = (rec.get("套餐类型") or "").strip()
    parent_number = (rec.get("关联主卡") or "").strip()
    if package_type not in LEDGER_ENUM:
        return None, None, "套餐类型「%s」无效，必须是：%s" % (package_type or "(空)", " / ".join(LEDGER_ENUM))
    if package_type in LEDGER_CHILD_TYPES:
        if not parent_number:
            return None, None, "「%s」必须填写关联主卡（数智惠企/冰激凌 号码）" % package_type
        if parent_number not in main_numbers:
            return None, None, "关联主卡「%s」不存在（须为已录入的数智惠企/冰激凌 号码）" % parent_number
        return package_type, parent_number, None
    # 主卡 / 魔方卡：无需关联主卡，忽略所填值
    return package_type, "", None


@app.route("/api/ledgers/template", methods=["GET"])
def ledger_template():
    """下载台账批量导入 CSV 模板"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(LEDGER_IMPORT_COLUMNS)
    writer.writerow(["2026-07-13", "13800000000", "示例科技有限公司", "张三", "融合套餐", "融合", ""])
    writer.writerow(["2026-07-13", "13800000001", "示例科技有限公司", "李四", "副卡套餐", "副卡", "13800000000"])
    csv_bytes = "\ufeff" + buf.getvalue()
    return Response(
        csv_bytes,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ledger_import_template.csv"}
    )


@app.route("/api/ledgers/import/preview", methods=["POST"])
def ledger_import_preview():
    """台账批量导入：解析 CSV 预览"""
    if "file" not in request.files:
        return jsonify({"error": "未上传文件"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "文件为空"}), 400
    text = _decode_csv_file(f)
    if text is None:
        return jsonify({"error": "无法识别文件编码，请用 UTF-8 或 GBK 保存"}), 400

    # 流式读取：不把整表 materialize 成 list；下面两遍扫描各用一个 reader 迭代器（内存只保留单行）
    reader = csv.reader(io.StringIO(text))
    try:
        first = next(reader)
    except StopIteration:
        return jsonify({"error": "文件无内容"}), 400
    header = [h.strip().replace('\ufeff', '') for h in first]
    uid = current_user_id()

    conn = get_db()
    existing_nums = {
        n for n in ((r["number"] or "").strip() for r in
                    conn.execute("SELECT number FROM businesses WHERE user_id=?", (uid,)).fetchall())
        if n
    }

    # 第一遍：收集主卡号码（DB 已存 + 本批文件中类型为数智惠企/冰激凌 的号码），用于关联主卡校验
    main_numbers = {
        n for n in ((r["number"] or "").strip() for r in
                    conn.execute("SELECT number FROM businesses WHERE user_id=? AND business_type IN ('数智惠企','冰激凌')", (uid,)).fetchall())
        if n
    }
    for row in reader:
        if not any(c.strip() for c in row):
            continue
        rec = _parse_csv_record(header, row)
        pt = (rec.get("套餐类型") or "").strip()
        num = (rec.get("号码") or "").strip()
        if pt in LEDGER_MAIN_TYPES and num:
            main_numbers.add(num)

    # 第二遍：用新的流式 reader 重新扫描（不复用已消费掉的迭代器），避免整表落内存
    reader = csv.reader(io.StringIO(text))
    next(reader)  # 跳过表头
    result_rows = []
    for idx, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        rec = _parse_csv_record(header, row)
        number = rec.get("号码", "").strip()
        company = rec.get("公司", "").strip()
        if not company and not number:
            result_rows.append({"index": idx, "status": "error", "message": "公司和号码均为空", "record": rec})
            continue
        if number and number in existing_nums:
            result_rows.append({"index": idx, "status": "duplicate", "message": "号码 %s 已存在" % number, "record": rec})
            continue
        # 套餐类型 + 关联主卡 校验
        package_type, parent_number, err = validate_ledger_import_row(rec, main_numbers)
        if err:
            result_rows.append({"index": idx, "status": "error", "message": err, "record": rec})
            continue
        # 写回归一化后的值，供提交使用
        rec["套餐类型"] = package_type
        rec["关联主卡"] = parent_number
        result_rows.append({"index": idx, "status": "ok", "record": rec})

    conn.close()
    return jsonify({"rows": result_rows, "total": len(result_rows)})


@app.route("/api/ledgers/import/commit", methods=["POST"])
def ledger_import_commit():
    """台账批量导入：确认写入"""
    data = request.json or {}
    rows = data.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "无导入数据"}), 400
    conn = get_db()
    uid = current_user_id()
    imported = 0
    errors = []
    # 防御性校验：preview 已校验，这里再挡一道（防止绕过预览直接提交）
    main_numbers = {
        n for n in ((r["number"] or "").strip() for r in
                    conn.execute("SELECT number FROM businesses WHERE user_id=? AND business_type IN ('数智惠企','冰激凌')", (uid,)).fetchall())
        if n
    }
    batch_mains = set()
    for item in rows:
        rec = item.get("record", {})
        pt = (rec.get("套餐类型") or "").strip()
        num = (rec.get("号码") or "").strip()
        if pt in LEDGER_MAIN_TYPES and num:
            batch_mains.add(num)
    main_numbers |= batch_mains
    for item in rows:
        rec = item.get("record", {})
        package_type, parent_number, err = validate_ledger_import_row(rec, main_numbers)
        if err:
            errors.append("号码 %s: %s" % (rec.get("号码") or "?", err))
            continue
        date = rec.get("日期", "")
        number = rec.get("号码", "")
        company = rec.get("公司", "")
        user_name = rec.get("使用人", "")
        package_name = rec.get("层级", "") or rec.get("套餐", "")
        try:
            parent_id = _resolve_parent_id(conn, uid, parent_number, package_type)
            conn.execute(
                "INSERT INTO businesses (user_id, date, number, company_name, user_name, business_level, business_type, parent_id) VALUES (?,?,?,?,?,?,?,?)",
                (uid, date, number, company, user_name, package_name, package_type, parent_id)
            )
            imported += 1
        except Exception as e:
            errors.append(str(e))
    conn.commit()
    conn.close()
    msg = "导入成功，共 %d 条" % imported
    if errors:
        msg += "，%d 条错误" % len(errors)
    return jsonify({"message": msg, "imported": imported, "errors": errors})


# ==================== 打卡 API ====================

def _current_ym():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m")

@app.route("/api/customers/<int:cid>/checkin", methods=["GET"])
def get_checkin(cid):
    """获取客户当月打卡次数"""
    ym = _current_ym()
    conn = get_db()
    row = conn.execute("SELECT count FROM checkins WHERE customer_id=? AND year_month=?", (cid, ym)).fetchone()
    conn.close()
    return jsonify({"count": row[0] if row else 0, "year_month": ym})

@app.route("/api/customers/<int:cid>/checkin", methods=["POST"])
def do_checkin(cid):
    """打卡+1"""
    ym = _current_ym()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO checkins (customer_id, year_month, count, updated_at)
        VALUES (?, ?, 1, datetime('now', 'localtime'))
        ON CONFLICT(customer_id, year_month) DO UPDATE SET
            count = count + 1,
            updated_at = datetime('now', 'localtime')
    """, (cid, ym))
    conn.commit()
    row = conn.execute("SELECT count FROM checkins WHERE customer_id=? AND year_month=?", (cid, ym)).fetchone()
    conn.close()
    return jsonify({"count": row[0], "year_month": ym})

@app.route("/api/customers/<int:cid>/checkin", methods=["PUT"])
def update_checkin(cid):
    """编辑当月打卡次数"""
    data = request.get_json(force=True) or {}
    new_count = int(data.get("count", 0))
    if new_count < 0:
        return jsonify({"error": "次数不能为负"}), 400
    ym = _current_ym()
    conn = get_db()
    conn.execute("""
        INSERT INTO checkins (customer_id, year_month, count, updated_at)
        VALUES (?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(customer_id, year_month) DO UPDATE SET
            count = excluded.count,
            updated_at = datetime('now', 'localtime')
    """, (cid, ym, new_count))
    conn.commit()
    row = conn.execute("SELECT count FROM checkins WHERE customer_id=? AND year_month=?", (cid, ym)).fetchone()
    conn.close()
    return jsonify({"count": row[0] if row else new_count, "year_month": ym})


# ==================== 事项 API ====================

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    """获取事项列表（按置顶、截止日期排序）"""
    conn = get_db()
    status = request.args.get("status", "")

    sql = """
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id
        WHERE c.user_id = ?
    """
    params = [current_user_id()]
    if status:
        sql += " AND t.status = ?"
        params.append(status)
    sql += " ORDER BY t.pinned DESC, t.due_date, t.updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks", methods=["POST"])
def add_task():
    """新增事项"""
    data = request.json
    conn = get_db()
    uid = current_user_id()
    cur = conn.execute("""
        INSERT INTO tasks (customer_id, title, description, status, due_date, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        data.get("customer_id"), data.get("title", ""), data.get("description", ""),
        data.get("status", "进行中"),
        data.get("due_date"), uid
    ))
    conn.commit()
    task_id = cur.lastrowid
    task = conn.execute("""
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id WHERE t.id = ?
    """, (task_id,)).fetchone()
    conn.close()
    cid = task["customer_id"]
    if cid:
        recalc_priority(cid)
    return jsonify(dict(task)), 201


@app.route("/api/tasks/<int:tid>", methods=["PUT"])
def update_task(tid):
    """更新事项（部分更新：仅覆盖请求中提供的字段，未提供的保留原值）"""
    data = request.json or {}
    conn = get_db()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id())).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "事项不存在"}), 404
    cols = ("title", "description", "status", "due_date", "pinned")
    merged = {k: data.get(k, existing[k]) for k in cols}
    conn.execute("""
        UPDATE tasks SET
            title=?, description=?, status=?, due_date=?, pinned=?,
            updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        merged["title"], merged["description"], merged["status"],
        merged["due_date"], merged["pinned"], tid
    ))
    conn.commit()
    task = conn.execute("""
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id WHERE t.id = ?
    """, (tid,)).fetchone()
    conn.close()
    if task and task["customer_id"]:
        recalc_priority(task["customer_id"])
    return jsonify(dict(task))


@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
def delete_task(tid):
    """删除事项（仅限本人）"""
    conn = get_db()
    row = conn.execute("SELECT customer_id FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id())).fetchone()
    cid = row["customer_id"] if row else None
    conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id()))
    conn.commit()
    conn.close()
    if cid:
        recalc_priority(cid)
    return jsonify({"message": "已删除"})


# ==================== 子待办 API ====================

@app.route("/api/tasks/<int:tid>/subtasks", methods=["GET"])
def get_subtasks(tid):
    """获取事项的子待办列表（仅限本人事项）"""
    conn = get_db()
    if not conn.execute("SELECT 1 FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id())).fetchone():
        conn.close()
        return jsonify({"error": "事项不存在"}), 404
    rows = conn.execute("SELECT * FROM subtasks WHERE task_id = ? ORDER BY order_index, id", (tid,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks/subtasks", methods=["GET"])
def get_all_subtasks():
    """获取当前用户所有事项的子待办（供列表内嵌展示），返回 [{id, task_id, title, done}]"""
    conn = get_db()
    rows = conn.execute("""
        SELECT s.id, s.task_id, s.title, s.done
        FROM subtasks s
        JOIN tasks t ON s.task_id = t.id
        WHERE t.user_id = ?
        ORDER BY s.task_id, s.order_index, s.id
    """, (current_user_id(),)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks/<int:tid>/subtasks", methods=["POST"])
def add_subtask(tid):
    """新增子待办"""
    try:
        data = request.json or {}
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "子待办标题不能为空"}), 400
        conn = get_db()
        if not conn.execute("SELECT 1 FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id())).fetchone():
            conn.close()
            return jsonify({"error": "事项不存在"}), 404
        # 新子待办排到末尾（order_index = 当前最大+1）
        max_row = conn.execute("SELECT COALESCE(MAX(order_index), -1) AS m FROM subtasks WHERE task_id = ?", (tid,)).fetchone()
        next_idx = (max_row["m"] if max_row and max_row["m"] is not None else -1) + 1
        cur = conn.execute("INSERT INTO subtasks (task_id, title, order_index) VALUES (?, ?, ?)", (tid, title, next_idx))
        conn.commit()
        row = conn.execute("SELECT * FROM subtasks WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        return jsonify(dict(row)), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/tasks/<int:tid>/subtasks/<int:sid>", methods=["PUT"])
def update_subtask(tid, sid):
    """更新子待办（切换完成状态或修改标题）"""
    data = request.json
    conn = get_db()
    existing = conn.execute(
        "SELECT s.* FROM subtasks s JOIN tasks t ON s.task_id = t.id "
        "WHERE s.id = ? AND s.task_id = ? AND t.user_id = ?",
        (sid, tid, current_user_id()),
    ).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "子待办不存在"}), 404
    new_done = data.get("done", existing["done"])
    new_title = data.get("title", existing["title"])
    conn.execute("UPDATE subtasks SET done=?, title=?, updated_at=datetime('now','localtime') WHERE id=?",
                 (new_done, new_title, sid))
    # 勾选/取消子待办后，按完成情况同步事项状态：全完成→已完结，否则→进行中（已归档也同步回退/完成）
    all_subs = conn.execute("SELECT done FROM subtasks WHERE task_id=?", (tid,)).fetchall()
    all_done = all(len(s) > 0 and s["done"] for s in all_subs) if all_subs else False
    new_status = '已完结' if all_done else '进行中'
    conn.execute("UPDATE tasks SET status=?, updated_at=datetime('now','localtime') WHERE id=?", (new_status, tid))
    conn.commit()
    row = conn.execute("SELECT * FROM subtasks WHERE id = ?", (sid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route("/api/tasks/<int:tid>/subtasks/<int:sid>", methods=["DELETE"])
def delete_subtask(tid, sid):
    """删除子待办（仅限本人事项）"""
    conn = get_db()
    owner = conn.execute(
        "SELECT 1 FROM subtasks s JOIN tasks t ON s.task_id = t.id "
        "WHERE s.id = ? AND s.task_id = ? AND t.user_id = ?",
        (sid, tid, current_user_id()),
    ).fetchone()
    if not owner:
        conn.close()
        return jsonify({"error": "子待办不存在"}), 404
    conn.execute("DELETE FROM subtasks WHERE id = ? AND task_id = ?", (sid, tid))
    # 删除子待办后，按剩余子待办完成情况同步事项状态：全完成→已完结，否则→进行中
    remaining = conn.execute("SELECT done FROM subtasks WHERE task_id=?", (tid,)).fetchall()
    if remaining:
        all_done = all(r["done"] for r in remaining)
        new_status = '已完结' if all_done else '进行中'
    else:
        new_status = '进行中'
    conn.execute("UPDATE tasks SET status=?, updated_at=datetime('now','localtime') WHERE id=?", (new_status, tid))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


@app.route("/api/tasks/<int:tid>/subtasks/reorder", methods=["PUT"])
def reorder_subtasks(tid):
    """重排子待办顺序：请求体 {"order": [id1, id2, ...]} 按顺序写入 order_index"""
    data = request.json or {}
    order = data.get("order") or []
    conn = get_db()
    if not conn.execute("SELECT 1 FROM tasks WHERE id = ? AND user_id = ?", (tid, current_user_id())).fetchone():
        conn.close()
        return jsonify({"error": "事项不存在"}), 404
    conn.executemany(
        "UPDATE subtasks SET order_index=? WHERE id=? AND task_id=?",
        [(i, sid, tid) for i, sid in enumerate(order)],
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "ok"})


@app.route("/api/tasks/<int:tid>/done", methods=["POST"])
def toggle_task_done(tid):
    """一键完成/取消完成事项：级联切换其全部子待办，并同步事项状态（已完结 / 进行中）"""
    data = request.json or {}
    done = bool(data.get("done", True))
    conn = get_db()
    task = conn.execute(
        "SELECT t.* FROM tasks t WHERE t.id = ? AND t.user_id = ?",
        (tid, current_user_id()),
    ).fetchone()
    if not task:
        conn.close()
        return jsonify({"error": "事项不存在"}), 404
    # 级联切换全部子待办
    conn.execute(
        "UPDATE subtasks SET done=?, updated_at=datetime('now','localtime') WHERE task_id=?",
        (1 if done else 0, tid),
    )
    # 同步事项状态：完成→已完结，取消→进行中
    new_status = "已完结" if done else "进行中"
    conn.execute(
        "UPDATE tasks SET status=?, updated_at=datetime('now','localtime') WHERE id=?",
        (new_status, tid),
    )
    conn.commit()
    subs = conn.execute("SELECT * FROM subtasks WHERE task_id=? ORDER BY id", (tid,)).fetchall()
    updated = conn.execute(
        "SELECT t.*, c.name as customer_name, c.company as customer_company "
        "FROM tasks t JOIN customers c ON t.customer_id = c.id WHERE t.id = ?",
        (tid,),
    ).fetchone()
    conn.close()
    return jsonify({"task": dict(updated), "subtasks": [dict(s) for s in subs]})


# ==================== 地图 & 附近客户 API ====================

@app.route("/api/nearby", methods=["GET"])
def get_nearby():
    """查询附近客户（按距离排序，已移除半径筛选）"""
    lat = float(request.args.get("lat", 0))
    lon = float(request.args.get("lon", 0))

    conn = get_db()
    customers = [dict(r) for r in conn.execute(
        "SELECT * FROM customers WHERE user_id = ?", (current_user_id(),)
    ).fetchall()]
    conn.close()

    # 半径筛选已移除：返回全部含坐标客户，按距离排序
    nearby = find_nearby_customers(lat, lon, customers)
    return jsonify(nearby)


@app.route("/api/geocode", methods=["GET"])
def geocode_address():
    """地址转经纬度"""
    address = request.args.get("address", "")
    if not address:
        return jsonify({"error": "请提供地址"}), 400
    coords = geocode(address)
    if coords:
        return jsonify({"latitude": coords[0], "longitude": coords[1]})
    return jsonify({"error": "无法解析地址"}), 404


@app.route("/api/reverse_geocode", methods=["GET"])
def reverse_geocode_address():
    """经纬度转地址名称"""
    try:
        lat = float(request.args.get("lat", 0))
        lon = float(request.args.get("lon", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "请提供有效的经纬度"}), 400
    if not lat or not lon:
        return jsonify({"error": "请提供经纬度参数 (lat, lon)"}), 400
    address = reverse_geocode(lat, lon)
    if address:
        return jsonify({"address": address})
    return jsonify({"error": "无法解析该位置"}), 404


# ==================== 设置 API ====================

@app.route("/api/settings", methods=["GET"])
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings WHERE user_id = ?", (current_user_id(),)).fetchall()
    conn.close()
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/settings", methods=["PUT"])
def update_settings():
    data = request.json
    uid = current_user_id()
    conn = get_db()
    conn.executemany(
        "INSERT OR REPLACE INTO settings (key, user_id, value) VALUES (?, ?, ?)",
        [(key, uid, str(value)) for key, value in data.items()],
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "设置已保存"})


# ==================== 报告 API ====================

@app.route("/api/report/generate", methods=["POST"])
def api_generate_report():
    """一键生成报告（当前用户）"""
    filepath = generate_daily_report(current_user_id())
    filename = os.path.basename(filepath)
    return jsonify({"message": "报告已生成", "filename": filename, "url": f"/reports/{filename}"})


@app.route("/api/reports", methods=["GET"])
def list_reports():
    """列出当前用户的报告"""
    if not os.path.exists(REPORTS_DIR):
        return jsonify([])
    uid = current_user_id()
    prefix = f"daily_report_{uid}_"
    files = sorted(os.listdir(REPORTS_DIR), reverse=True)
    reports = []
    for f in files:
        if f.endswith(".html") and f.startswith(prefix):
            stat = os.stat(os.path.join(REPORTS_DIR, f))
            reports.append({
                "filename": f,
                "url": f"/reports/{f}",
                "size": f"{stat.st_size / 1024:.1f} KB",
                "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
    return jsonify(reports)


@app.route("/reports/<path:filename>")
def serve_report(filename):
    """提供报告文件访问（仅限本人报告）"""
    if not filename.startswith(f"daily_report_{current_user_id()}_"):
        return jsonify({"error": "无权访问"}), 403
    return send_from_directory(REPORTS_DIR, filename)


# ==================== 项目下载（导出到本地 PC） ====================

@app.route("/download-project")
def download_project():
    """
    打包并下载整个项目（含数据库）
    用于在云端沙箱环境下，把项目导出到本地 PC
    """
    import shutil
    import zipfile
    import tempfile

    project_dir = os.path.dirname(os.path.abspath(__file__))
    # 跨平台临时目录（Windows 下为 %TEMP%，不再写死 /tmp）
    zip_path = os.path.join(tempfile.gettempdir(), "customer-workspace-export.zip")

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # 导出时剪枝：虚拟环境 venv(2GB+)、依赖缓存、版本库、回收站等不进包，
        # 只保留源码+数据+模板。否则一次 /download-project 就会下载整个项目目录，体积过大。
        _exclude_dirs = {"__pycache__", "venv", "node_modules", ".git",
                         ".idea", "_cleanup_回收站"}
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [d for d in dirs if d not in _exclude_dirs]
            for f in files:
                if f.endswith(".pyc"):
                    continue
                if f.startswith("screenshot_"):
                    continue
                full = os.path.join(root, f)
                arcname = os.path.relpath(full, os.path.dirname(project_dir))
                zf.write(full, arcname)

    return send_file(
        zip_path,
        as_attachment=True,
        download_name="customer-workspace.zip"
    )


@app.route("/download")
def download_page():
    """下载引导页（云端沙箱导出用）"""
    return render_template("download.html")


# ==================== 仪表盘统计 API ====================

@app.route("/api/dashboard", methods=["GET"])
def dashboard_stats():
    """仪表盘统计数据（仅当前用户）"""
    conn = get_db()
    uid = current_user_id()
    today = datetime.now().strftime("%Y-%m-%d")

    total_customers = conn.execute("SELECT COUNT(*) FROM customers WHERE user_id=?", (uid,)).fetchone()[0]
    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=?", (uid,)).fetchone()[0]
    in_progress = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='进行中'", (uid,)).fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE user_id=? AND status='已完结'", (uid,)).fetchone()[0]
    overdue = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE user_id=? AND due_date < ? AND status != '已完结'",
        (uid, today),
    ).fetchone()[0]
    vip = conn.execute("SELECT COUNT(*) FROM customers WHERE user_id=? AND category='核心要客'", (uid,)).fetchone()[0]

    # 最近事项
    recent_tasks = [dict(r) for r in conn.execute("""
        SELECT t.*, c.company as customer_company, c.name as customer_name
        FROM tasks t JOIN customers c ON t.customer_id = c.id
        WHERE t.user_id = ?
        ORDER BY t.updated_at DESC LIMIT 5
    """, (uid,)).fetchall()]

    conn.close()

    return jsonify({
        "total_customers": total_customers,
        "total_tasks": total_tasks,
        "in_progress": in_progress,
        "completed": completed,
        "overdue": overdue,
        "vip": vip,
        "completion_rate": round(completed / max(total_tasks, 1) * 100, 1),
        "recent_tasks": recent_tasks,
    })


# ==================== 登录 / 登出 / 注册 / 改密码路由 ====================

@app.route("/api/login", methods=["POST"])
def api_login():
    """账号密码登录"""
    data = request.json or {}
    username = (data.get("phone") or data.get("username") or "").strip()
    password = data.get("password") or ""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE phone=? OR username=?", (username, username)).fetchone()
    conn.close()
    if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "用户名或密码错误"}), 401
    if row["status"] == "pending":
        return jsonify({"error": "账号待管理员审核，暂无法登录", "code": "pending"}), 403
    _login_as(dict(row))
    return jsonify({
        "ok": True,
        "user": {"id": row["id"], "username": row["username"], "display_name": row["display_name"]},
    })


@app.route("/api/logout", methods=["POST", "GET"])
def api_logout():
    """退出登录（API）"""
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me", methods=["GET"])
def api_me():
    """返回当前登录用户信息"""
    if not session.get("user_id"):
        return jsonify({"error": "未登录"}), 401
    return jsonify({
        "user": {
            "id": session["user_id"],
            "username": session.get("username"),
            "phone": session.get("phone"),
            "display_name": session.get("display_name"),
            "is_admin": bool(session.get("is_admin")),
        }
    })


@app.route("/api/auth/login", methods=["POST"])
def api_dingtalk_auth_login():
    """钉钉 H5 免登：用前端传来的免登 authCode 换钉钉 userId，匹配本地账号后种 session。"""
    data = request.json or {}
    auth_code = (data.get("authCode") or data.get("code") or "").strip()
    if not auth_code:
        return jsonify({"error": "缺少 authCode"}), 400
    if not _DING_APP_KEY or not _DING_APP_SECRET:
        return jsonify({"error": "服务端未配置钉钉应用密钥"}), 500
    try:
        ding_uid = _ding_userid_by_code(auth_code)
    except Exception as e:
        return jsonify({"error": "钉钉免登失败：%s" % str(e)}), 502
    if not ding_uid:
        return jsonify({"error": "无法获取钉钉用户身份"}), 502
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE dingtalk_user_id=?", (ding_uid,)).fetchone()
    # 兜底：若钉钉 userId 未绑定任何账号，但 URL 带了 ?phone= 且匹配管理员，则自动绑定（首次免登一键打通）
    if not row:
        bind_phone = (data.get("phone") or "").strip()
        if bind_phone:
            row = conn.execute(
                "SELECT * FROM users WHERE phone=? OR username=?", (bind_phone, bind_phone)).fetchone()
            if row:
                conn.execute("UPDATE users SET dingtalk_user_id=? WHERE id=?", (ding_uid, row["id"]))
                conn.commit()
    conn.close()
    if not row:
        return jsonify({"error": "该钉钉账号未绑定系统用户，请先用手机号密码登录一次", "code": "unbound"}), 401
    if row["status"] == "pending":
        return jsonify({"error": "账号待管理员审核，暂无法登录", "code": "pending"}), 403
    _login_as(dict(row))
    return jsonify({
        "ok": True,
        "user": {"id": row["id"], "username": row["username"], "display_name": row["display_name"]},
    })


@app.route("/api/change-phone", methods=["POST"])
def api_change_phone():
    """修改当前登录用户的手机号（登录标识）。需校验格式（11 位）与唯一性（不与任何现有 phone 重复）。同步更新 username 保持与手机号一致。"""
    if not session.get("user_id"):
        return jsonify({"error": "未登录"}), 401
    import re as _re
    data = request.json or {}
    new_phone = (data.get("phone") or "").strip()
    if not _re.match(r"^1\d{10}$", new_phone):
        return jsonify({"error": "请输入有效的 11 位手机号"}), 400
    old = session.get("phone")
    if old and new_phone == old:
        return jsonify({"error": "新手机号与当前相同"}), 400
    conn = get_db()
    # 仅手机号唯一（username 始终等于手机号，无需单独校验）
    clash = conn.execute(
        "SELECT id FROM users WHERE phone=? AND id<>?",
        (new_phone, session["user_id"]),
    ).fetchone()
    if clash:
        conn.close()
        return jsonify({"error": "该手机号已被占用，请换一个"}), 409
    conn.execute(
        "UPDATE users SET phone=?, username=? WHERE id=?",
        (new_phone, new_phone, session["user_id"]),
    )
    conn.commit()
    conn.close()
    session["phone"] = new_phone
    session["username"] = new_phone
    return jsonify({"ok": True, "phone": new_phone, "message": "手机号已更新"})


@app.route("/api/register", methods=["POST"])
def api_register():
    """自助注册：仅手机号（必填），默认密码 123456。注册后为待审核状态，需管理员通过。username 列等于手机号。"""
    import re as _re
    data = request.json or {}
    phone = (data.get("phone") or "").strip()
    if not _re.match(r"^1\d{10}$", phone):
        return jsonify({"error": "请输入有效的 11 位手机号"}), 400
    conn = get_db()
    if conn.execute("SELECT id FROM users WHERE phone=?", (phone,)).fetchone():
        conn.close()
        return jsonify({"error": "该手机号已注册，请直接登录", "code": "exists"}), 409
    cur = conn.execute(
        "INSERT INTO users (username, phone, password_hash, display_name, is_admin, status) VALUES (?,?,?,?,0,'pending')",
        (phone, phone, generate_password_hash("123456", method="pbkdf2:sha256"), phone),
    )
    uid = cur.lastrowid
    _seed_user_settings(cur, uid)  # 预置默认位置设置，审核通过后地图功能可用
    conn.commit()
    conn.close()
    notify_registration_pending(phone, phone)  # 经钉钉群机器人推送（注册待审核）
    return jsonify({
        "ok": True,
        "pending": True,
        "message": "注册成功，等待管理员审核后即可登录",
    }), 201


@app.route("/api/admin/pending", methods=["GET"])
def admin_pending():
    """列出待审核注册（仅管理员）"""
    denied = _require_admin()
    if denied:
        return denied
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, created_at FROM users WHERE status='pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return jsonify({"pending": [dict(r) for r in rows]})


@app.route("/api/admin/users", methods=["GET"])
def admin_list_users():
    """列出全部用户及状态（仅管理员）"""
    denied = _require_admin()
    if denied:
        return denied
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, display_name, is_admin, status, created_at FROM users ORDER BY is_admin DESC, id"
    ).fetchall()
    conn.close()
    return jsonify({"users": [dict(r) for r in rows]})


@app.route("/api/admin/approve", methods=["POST"])
def admin_approve():
    """通过审核（仅管理员）：将待审核账号置为 active。"""
    denied = _require_admin()
    if denied:
        return denied
    data = request.json or {}
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "缺少 user_id"}), 400
    conn = get_db()
    row = conn.execute("SELECT id, status, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "用户不存在"}), 404
    if row["status"] != "pending":
        conn.close()
        return jsonify({"error": "该用户无需审核"}), 400
    conn.execute("UPDATE users SET status='active' WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    notify_registration_approved(row["username"])  # 经钉钉群机器人推送（审核通过）
    return jsonify({"ok": True, "message": "已通过审核"})


@app.route("/api/admin/reject", methods=["POST"])
def admin_reject():
    """拒绝审核（仅管理员）：删除待审核账号及其设置。"""
    denied = _require_admin()
    if denied:
        return denied
    data = request.json or {}
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "缺少 user_id"}), 400
    conn = get_db()
    row = conn.execute("SELECT id, status, is_admin, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "用户不存在"}), 404
    if row["is_admin"]:
        conn.close()
        return jsonify({"error": "不能拒绝管理员账号"}), 400
    if row["status"] != "pending":
        conn.close()
        return jsonify({"error": "该用户无需审核"}), 400
    conn.execute("DELETE FROM settings WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    notify_registration_rejected(row["username"])  # 经钉钉群机器人推送（审核拒绝）
    return jsonify({"ok": True, "message": "已拒绝并删除该注册申请"})


@app.route("/api/admin/delete-user", methods=["POST"])
def admin_delete_user():
    """删除用户（仅管理员）：级联清理其全部业务数据与设置。
    保护：不能删自己；不能删最后一个管理员账号。"""
    denied = _require_admin()
    if denied:
        return denied
    data = request.json or {}
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "缺少 user_id"}), 400
    try:
        uid = int(uid)
    except (ValueError, TypeError):
        return jsonify({"error": "user_id 无效"}), 400
    current_uid = session.get("user_id")
    if isinstance(current_uid, str):
        try:
            current_uid = int(current_uid)
        except ValueError:
            current_uid = None
    if uid == current_uid:
        return jsonify({"error": "不能删除当前登录的账号"}), 400
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT id, is_admin, username FROM users WHERE id=?", (uid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "用户不存在"}), 404
    if row["is_admin"]:
        admin_cnt = cur.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin=1 AND id<>?", (uid,)
        ).fetchone()[0]
        if admin_cnt == 0:
            conn.close()
            return jsonify({"error": "不能删除最后一个管理员账号"}), 400
    # 级联清理业务数据
    cust_ids = [r[0] for r in cur.execute("SELECT id FROM customers WHERE user_id=?", (uid,)).fetchall()]
    task_ids = [r[0] for r in cur.execute("SELECT id FROM tasks WHERE user_id=?", (uid,)).fetchall()]
    if cust_ids:
        ph = ",".join("?" * len(cust_ids))
        cur.execute(f"DELETE FROM checkins WHERE customer_id IN ({ph})", cust_ids)
    if task_ids:
        ph = ",".join("?" * len(task_ids))
        cur.execute(f"DELETE FROM subtasks WHERE task_id IN ({ph})", task_ids)
    cur.execute("DELETE FROM customers WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM tasks WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM businesses WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM settings WHERE user_id=?", (uid,))
    cur.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": f"已删除用户 {row['username']} 及其全部数据"})


@app.route("/api/admin/password-resets", methods=["GET"])
def admin_password_resets():
    """列出待审核的密码重置申请（仅管理员）"""
    denied = _require_admin()
    if denied:
        return denied
    conn = get_db()
    rows = conn.execute(
        "SELECT r.id, r.user_id, r.created_at, u.username, u.phone, u.display_name "
        "FROM password_resets r JOIN users u ON u.id=r.user_id "
        "WHERE r.status='pending' ORDER BY r.created_at"
    ).fetchall()
    conn.close()
    return jsonify({"resets": [dict(r) for r in rows]})


@app.route("/api/admin/reset-approve", methods=["POST"])
def admin_reset_approve():
    """通过密码重置（仅管理员）：将用户密码置为申请中的新密码。"""
    denied = _require_admin()
    if denied:
        return denied
    data = request.json or {}
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "缺少 user_id"}), 400
    conn = get_db()
    r = conn.execute(
        "SELECT new_password_hash FROM password_resets WHERE user_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
        (uid,),
    ).fetchone()
    if not r:
        conn.close()
        return jsonify({"error": "无待审核的重置申请"}), 404
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (r["new_password_hash"], uid))
    conn.execute("UPDATE password_resets SET status='done' WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "密码已重置"})


@app.route("/api/admin/reset-reject", methods=["POST"])
def admin_reset_reject():
    """拒绝密码重置（仅管理员）：删除待审核申请。"""
    denied = _require_admin()
    if denied:
        return denied
    data = request.json or {}
    uid = data.get("user_id")
    if not uid:
        return jsonify({"error": "缺少 user_id"}), 400
    conn = get_db()
    conn.execute("DELETE FROM password_resets WHERE user_id=? AND status='pending'", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "已拒绝密码重置申请"})


@app.route("/api/change-password", methods=["POST"])
def api_change_password():
    """修改当前登录用户密码（需提供当前密码）。"""
    if not session.get("user_id"):
        return jsonify({"error": "未登录"}), 401
    data = request.json or {}
    old_pw = data.get("old_password") or ""
    new_pw = data.get("new_password") or ""
    if len(new_pw) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    if not row or not row["password_hash"] or not check_password_hash(row["password_hash"], old_pw):
        conn.close()
        return jsonify({"error": "当前密码不正确"}), 400
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw, method="pbkdf2:sha256"), session["user_id"]))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "密码修改成功"})


@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    """忘记密码：提交用户名/手机号 + 新密码，生成待管理员审核的重置申请。"""
    import re as _re
    data = request.json or {}
    identifier = (data.get("identifier") or "").strip()
    new_pw = data.get("new_password") or ""
    confirm_pw = data.get("confirm_password") or ""
    if not identifier:
        return jsonify({"error": "请填写用户名或手机号"}), 400
    if len(new_pw) < 6:
        return jsonify({"error": "新密码至少 6 位"}), 400
    if new_pw != confirm_pw:
        return jsonify({"error": "两次输入的密码不一致"}), 400
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=? OR phone=?", (identifier, identifier)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "未找到该账号"}), 404
    if row["status"] == "pending":
        conn.close()
        return jsonify({"error": "账号待管理员审核，暂无法重置密码"}), 403
    # 同账号只保留一条待审申请（先清旧）
    conn.execute("DELETE FROM password_resets WHERE user_id=?", (row["id"],))
    conn.execute(
        "INSERT INTO password_resets (user_id, new_password_hash, status) VALUES (?,?, 'pending')",
        (row["id"], generate_password_hash(new_pw, method="pbkdf2:sha256")),
    )
    conn.commit()
    conn.close()
    notify_password_reset_pending(row["username"], row["phone"] or "")
    return jsonify({"ok": True, "pending": True, "message": "已提交，等待管理员审核通过后新密码生效"})


@app.route("/login")
def login_page():
    """登录页（手机号+密码 或 手机号自助注册）"""
    # 已登录直接回首页
    if session.get("user_id"):
        return redirect("/")
    return render_template("login.html")


@app.route("/logout")
def logout():
    """退出登录（页面跳转）"""
    session.clear()
    return redirect("/login")


@app.route("/m")
def mobile_entry():
    """移动端入口（直接浏览器访问）"""
    ua = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in ua for x in ["mobile", "android", "iphone", "harmony", "phone"])
    if is_mobile:
        return render_template("mobile_index.html")
    return redirect("/")


# ==================== 启动 ====================

if __name__ == "__main__":
    init_db()
    # 注意：不再自动填充示例数据（用户已清空并进入真实使用）。
    # 如需重新生成演示数据，可手动执行 `python models.py`。
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 60)
    print("  客户管理平台已启动")
    print(f"  本地访问:    http://localhost:{port}")
    print(f"  移动端入口:  http://localhost:{port}/m")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# Flask 由 tools/start_preview.cmd 循环保活（见 Launch-App.cmd / register_autostart.py）。


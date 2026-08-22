# -*- coding: utf-8 -*-
"""钉钉小程序后端（FC 版 Flask）。

与现有 PC 版 app.py 的差异：
1. 数据库从 sqlite3 换成 RDS MySQL（经 db.py 封装，业务 SQL 几乎不变）。
2. 登录态从 Flask session 换成 JWT（FC 无状态）。
3. 新增 /api/auth/login 走钉钉免登（authCode -> userId）。
4. 其余业务路由（tasks / business / ledgers / import / admin ...）按下方
   已实现的 customers 模板平移即可，隔离统一用 g.user_id。

部署：阿里云 FC 选「Flask 框架」或自定义运行时，HTTP 触发器，入口指向本文件 app 实例。
"""
import json
import time
import os
from flask import Flask, request, jsonify, g, send_from_directory, render_template
from werkzeug.security import check_password_hash
import db
import auth
import config

app = Flask(__name__, template_folder="templates", static_folder=None)
app.config["JSON_AS_ASCII"] = False


def _now():
    """本地时间字符串，对齐 schema 中 TEXT 时间戳（由应用层写，避免 MySQL 时区错位）。"""
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _int_or_none(v):
    try:
        if v is None or v == "":
            return None
        return int(v)
    except Exception:
        return None

_ensured = False


@app.before_request
def _auth():
    global _ensured
    if not _ensured:
        try:
            db.ensure_dingtalk_column()
        except Exception:
            pass
        _ensured = True

    g.user_id = None
    g.is_admin = False

    # CORS
    if request.method == "OPTIONS":
        return _cors(jsonify({"ok": True}))

    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.args.get("token")
        if not token and request.get_json(silent=True):
            token = request.get_json(silent=True).get("token")

    if token:
        payload = auth.parse_jwt(token)
        if payload:
            g.user_id = payload.get("uid")
            g.is_admin = payload.get("adm", False)

    # 公开路径
    public = ("/api/auth/login", "/api/healthz")
    if request.path in public:
        return None
    if request.path.startswith(("/api/auth",)):
        return None
    if not g.user_id:
        return _cors(jsonify({"error": "未登录", "code": "unauthorized"})), 401


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = config.ALLOW_ORIGIN
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


def _ok(data=None, **kw):
    """标准成功信封：{ code: 0, data: <payload>, ...extra }。
    前端 request.js 依赖 res.data.code===0 且 res.data.data 为业务负载。"""
    payload = {"code": 0, "data": data if data is not None else {}}
    payload.update(kw)
    return _cors(jsonify(payload))


def _err(message, code=1, http=400):
    return _cors(jsonify({"code": code, "message": message})), http


@app.route("/api/healthz")
def healthz():
    return jsonify({"ok": True, "db": bool(config.DB_HOST)})


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """钉钉免登：authCode -> 钉钉 userId -> 本地 user -> 签发 JWT。"""
    data = request.json or {}
    auth_code = (data.get("authCode") or data.get("code") or "").strip()
    if not auth_code:
        return _err("缺少 authCode")
    try:
        ding_uid = auth.get_userid_by_code(auth_code)
    except Exception as e:
        return _err("钉钉免登失败: %s" % e, http=502)
    if not ding_uid:
        return _err("无法获取钉钉用户", http=502)

    row = auth.dingtalk_userid_to_local(ding_uid)
    if not row:
        return _err("该钉钉账号未绑定，请联系管理员", code="unbound", http=403)

    token = auth.make_jwt(row["id"], bool(row.get("is_admin")))
    return _ok({"token": token, "user": {"id": row["id"], "is_admin": bool(row.get("is_admin"))}})


@app.route("/api/password-login", methods=["POST"])
def api_password_login():
    """手机号+密码登录（H5 微应用非钉钉环境兜底，或用户主动用密码登录）。
    校验通过后签发与钉钉免登相同的 JWT，前端统一存 localStorage 由 api() 带 Authorization。"""
    data = request.json or {}
    username = (data.get("phone") or data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return _err("请输入手机号和密码")
    row = db.query(
        "SELECT id, phone, username, display_name, is_admin, password_hash, status FROM users WHERE phone=%s OR username=%s",
        (username, username), one=True)
    if not row or not row.get("password_hash") or not check_password_hash(row["password_hash"], password):
        return _err("手机号或密码错误", http=401)
    if row.get("status") == "pending":
        return _err("账号待管理员审核，暂无法登录", code="pending", http=403)
    token = auth.make_jwt(row["id"], bool(row.get("is_admin")))
    return _ok({"token": token, "user": {"id": row["id"], "username": row.get("username"),
                                          "display_name": row.get("display_name"), "is_admin": bool(row.get("is_admin"))}})


# ==================== H5 移动端托管（前端静态资源） ====================
# 把 PC 版的 templates/ 和 static/ 一并打进 FC 部署包，使函数既能跑 API 又能托管 H5，
# 手机钉钉 H5 微应用主页直接指向本函数域名 /m，彻底脱离本地 PC / ngrok。
_STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
_TEMPLATE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


@app.route("/m")
def h5_mobile_entry():
    ua = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in ua for x in ["mobile", "android", "iphone", "harmony", "phone"])
    if not is_mobile:
        # 桌面浏览器访问 /m 也允许预览（便于调试），不强制跳转
        pass
    try:
        return render_template("mobile_index.html")
    except Exception:
        return _err("H5 页面未部署，请检查 FC 部署包是否包含 templates/mobile_index.html", http=404)


@app.route("/static/<path:filename>")
def h5_static(filename):
    return send_from_directory(_STATIC_ROOT, filename)


@app.route("/assets/<path:filename>")
def h5_assets(filename):
    # 移动端静态资源走 /assets/v{ver}/...，与 PC 版路径一致
    return send_from_directory(_STATIC_ROOT, filename)


@app.route("/")
def h5_root():
    return render_template("mobile_index.html") if os.path.exists(os.path.join(_TEMPLATE_ROOT, "mobile_index.html")) else jsonify({"ok": True, "msg": "CRM API"})



    row = db.query("SELECT id, username, phone, display_name, is_admin FROM users WHERE id=?",
                   (g.user_id,), one=True)
    if not row:
        return _err("用户不存在", http=404)
    return _ok({"user": {"id": row["id"], "username": row["username"], "phone": row["phone"],
                         "display_name": row["display_name"], "is_admin": bool(row["is_admin"])}})


@app.route("/api/customers", methods=["GET"])
def api_customers():
    keyword = request.args.get("keyword", "")
    sql = "SELECT * FROM customers WHERE user_id=%s"
    params = [g.user_id]
    if keyword:
        sql += " AND (company LIKE %s OR name LIKE %s OR phone LIKE %s)"
        params.extend([f"%{keyword}%"] * 3)
    rows = db.query(sql + " ORDER BY id DESC", params)
    return _ok({"customers": rows, "count": len(rows)})


@app.route("/api/customers/<int:cid>", methods=["GET"])
def api_customer_detail(cid):
    row = db.query("SELECT * FROM customers WHERE id=%s AND user_id=%s", (cid, g.user_id), one=True)
    if not row:
        return _err("客户不存在或无权限", http=404)
    return _ok({"customer": row})


@app.route("/api/settings", methods=["GET"])
def api_settings():
    rows = db.query("SELECT `key`, value FROM settings WHERE user_id=?", (g.user_id,))
    out = {r["key"]: r["value"] for r in rows}
    return _ok({"settings": out})


@app.route("/api/nearby", methods=["GET"])
def api_nearby():
    """附近客户：经 geo 模块算真实距离（优先腾讯地图驾车距离）。"""
    import geo
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius = request.args.get("radius", 5000, type=int)
    if lat is None or lng is None:
        return _err("缺少坐标")
    rows = geo.nearby_customers(g.user_id, lat, lng, radius=radius, limit=20)
    return _ok({"nearby": rows, "count": len(rows)})


# ============ 事项 API ============

@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    """事项列表（按置顶、截止日期、更新时间排序）。"""
    status = request.args.get("status", "")
    customer_id = request.args.get("customer_id", type=int)
    sql = """
        SELECT t.*, c.name AS customer_name, c.company AS customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id
        WHERE c.user_id = %s
    """
    params = [g.user_id]
    if status:
        sql += " AND t.status = %s"
        params.append(status)
    if customer_id:
        sql += " AND t.customer_id = %s"
        params.append(customer_id)
    sql += " ORDER BY t.pinned DESC, t.due_date, t.updated_at DESC"
    rows = db.query(sql, params)
    return _ok({"tasks": rows, "count": len(rows)})


@app.route("/api/tasks", methods=["POST"])
def api_add_task():
    """新增事项。"""
    data = request.json or {}
    tid = db.execute("""
        INSERT INTO tasks (customer_id, title, description, status, due_date, user_id, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        data.get("customer_id"), data.get("title", ""), data.get("description", ""),
        data.get("status", "进行中"), data.get("due_date"), g.user_id, _now(), _now()
    ))
    task = db.query("SELECT * FROM tasks WHERE id=%s", (tid,), one=True)
    return _ok({"task": task}), 201


@app.route("/api/tasks/<int:tid>", methods=["PUT"])
def api_update_task(tid):
    """更新事项（部分更新）。"""
    data = request.json or {}
    existing = db.query("SELECT * FROM tasks WHERE id=%s AND user_id=%s", (tid, g.user_id), one=True)
    if not existing:
        return _err("事项不存在或无权限", http=404)
    cols = ("title", "description", "status", "due_date", "pinned")
    merged = {k: data.get(k, existing[k]) for k in cols}
    db.execute("""
        UPDATE tasks SET title=%s, description=%s, status=%s, due_date=%s, pinned=%s, updated_at=%s
        WHERE id=%s
    """, (merged["title"], merged["description"], merged["status"], merged["due_date"],
          merged["pinned"], _now(), tid))
    task = db.query("SELECT * FROM tasks WHERE id=%s", (tid,), one=True)
    return _ok({"task": task})


@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
def api_delete_task(tid):
    """删除事项（仅本人）。"""
    db.execute("DELETE FROM tasks WHERE id=%s AND user_id=%s", (tid, g.user_id))
    return _ok({"message": "已删除"})


# ============ 子待办 API ============

@app.route("/api/tasks/<int:tid>/subtasks", methods=["GET"])
def api_subtasks(tid):
    rows = db.query("SELECT * FROM subtasks WHERE task_id=%s ORDER BY order_index, id", (tid,))
    return _ok({"subtasks": rows})


@app.route("/api/tasks/subtasks", methods=["GET"])
def api_all_subtasks():
    rows = db.query("""
        SELECT s.id, s.task_id, s.title, s.done
        FROM subtasks s JOIN tasks t ON s.task_id = t.id
        WHERE t.user_id = %s
        ORDER BY s.task_id, s.order_index, s.id
    """, (g.user_id,))
    return _ok({"subtasks": rows})


@app.route("/api/tasks/<int:tid>/subtasks", methods=["POST"])
def api_add_subtask(tid):
    data = request.json or {}
    title = (data.get("title") or "").strip()
    if not title:
        return _err("子待办标题不能为空")
    max_row = db.query("SELECT COALESCE(MAX(order_index), -1) AS m FROM subtasks WHERE task_id=%s", (tid,), one=True)
    next_idx = (max_row["m"] if max_row and max_row["m"] is not None else -1) + 1
    sid = db.execute("INSERT INTO subtasks (task_id, title, order_index) VALUES (%s, %s, %s)",
                     (tid, title, next_idx))
    row = db.query("SELECT * FROM subtasks WHERE id=%s", (sid,), one=True)
    return _ok({"subtask": row}), 201


@app.route("/api/tasks/<int:tid>/subtasks/<int:sid>", methods=["PUT"])
def api_update_subtask(tid, sid):
    data = request.json or {}
    existing = db.query(
        "SELECT s.* FROM subtasks s JOIN tasks t ON s.task_id = t.id "
        "WHERE s.id=%s AND s.task_id=%s AND t.user_id=%s",
        (sid, tid, g.user_id), one=True)
    if not existing:
        return _err("子待办不存在", http=404)
    title = data.get("title", existing["title"])
    done = data.get("done", existing["done"])
    db.execute("UPDATE subtasks SET title=%s, done=%s WHERE id=%s", (title, done, sid))
    row = db.query("SELECT * FROM subtasks WHERE id=%s", (sid,), one=True)
    return _ok({"subtask": row})


# ============ 业务台账 API ============

@app.route("/api/business", methods=["GET"])
def api_businesses():
    """业务列表（支持按公司名/合同编码/号码/业务类型模糊搜索）。"""
    search = request.args.get("search", "")
    sql = """
        SELECT b.*, c.name AS customer_name
        FROM businesses b LEFT JOIN customers c ON b.customer_id = c.id
        WHERE b.user_id = %s
    """
    params = [g.user_id]
    if search:
        sql += " AND (b.company_name LIKE %s OR b.contract_code LIKE %s OR b.number LIKE %s OR b.business_type LIKE %s)"
        params.extend([f"%{search}%"] * 4)
    sql += " ORDER BY b.updated_at DESC, b.id DESC"
    rows = db.query(sql, params)
    return _ok({"businesses": rows, "count": len(rows)})


@app.route("/api/business", methods=["POST"])
def api_add_business():
    data = request.json or {}
    parent_id = _int_or_none(data.get("parent_id"))
    bid = db.execute("""
        INSERT INTO businesses (customer_id, company_name, business_address, number,
            contract_code, business_type, contract_amount, start_date, end_date, notes,
            business_package, user_id, business_level, date, user_name, parent_id, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        data.get("customer_id") or None, data.get("company_name", ""),
        data.get("business_address", ""), (data.get("number") or data.get("business_number") or ""),
        data.get("contract_code", ""), data.get("business_type", ""),
        data.get("contract_amount"), data.get("start_date", ""),
        data.get("end_date", ""), data.get("notes", ""),
        data.get("business_package", ""), g.user_id,
        data.get("business_level", ""), data.get("date", ""),
        data.get("user_name", ""), parent_id, _now(), _now()
    ))
    row = db.query("SELECT * FROM businesses WHERE id=%s", (bid,), one=True)
    return _ok({"business": row}), 201


@app.route("/api/business/<int:bid>", methods=["GET"])
def api_business_detail(bid):
    row = db.query("SELECT * FROM businesses WHERE id=%s AND user_id=%s", (bid, g.user_id), one=True)
    if not row:
        return _err("业务不存在", http=404)
    return _ok({"business": row})


@app.route("/api/business/<int:bid>", methods=["PUT"])
def api_update_business(bid):
    data = request.json or {}
    existing = db.query("SELECT * FROM businesses WHERE id=%s AND user_id=%s", (bid, g.user_id), one=True)
    if not existing:
        return _err("业务不存在", http=404)
    cols = ("customer_id", "company_name", "business_address", "number",
            "contract_code", "business_type", "business_package", "contract_amount", "start_date",
            "end_date", "notes", "business_level", "date", "user_name", "parent_id")
    merged = {k: data.get(k, existing[k]) for k in cols}
    merged["parent_id"] = _int_or_none(data.get("parent_id", existing["parent_id"]))
    db.execute("""
        UPDATE businesses SET
            customer_id=%s, company_name=%s, business_address=%s, number=%s,
            contract_code=%s, business_type=%s, business_package=%s, contract_amount=%s, start_date=%s, end_date=%s,
            notes=%s, business_level=%s, date=%s, user_name=%s, parent_id=%s, updated_at=%s
        WHERE id=%s
    """, (
        merged["customer_id"], merged["company_name"], merged["business_address"], merged["number"],
        merged["contract_code"], merged["business_type"], merged["business_package"],
        merged["contract_amount"], merged["start_date"], merged["end_date"],
        merged["notes"], merged["business_level"], merged["date"], merged["user_name"],
        merged["parent_id"], _now(), bid
    ))
    row = db.query("SELECT * FROM businesses WHERE id=%s", (bid,), one=True)
    return _ok({"business": row})


@app.route("/api/business/<int:bid>", methods=["DELETE"])
def api_delete_business(bid):
    db.execute("DELETE FROM businesses WHERE id=%s AND user_id=%s", (bid, g.user_id))
    return _ok({"message": "已删除"})


# ============ 设置 API ============

@app.route("/api/settings", methods=["PUT"])
def api_update_settings():
    """批量保存设置（先删后插，避免依赖 unique 约束）。"""
    data = request.json or {}
    if not data:
        return _ok({"message": "空设置"})
    keys = list(data.keys())
    placeholders = ",".join(["%s"] * len(keys))
    db.execute("DELETE FROM settings WHERE user_id=%s AND `key` IN (%s)" % placeholders, [g.user_id] + keys)
    db.executemany("INSERT INTO settings (`key`, user_id, value) VALUES (%s, %s, %s)",
                   [(k, g.user_id, str(v)) for k, v in data.items()])
    return _ok({"message": "设置已保存"})


# ============ 导出 / 导入 / 报告 API ============

@app.route("/api/export", methods=["POST"])
def api_export():
    """导出数据：生成 CSV/JSON 上传 OSS，返回签名下载 URL。"""
    import export as export_mod
    import oss as oss_mod
    data = request.json or {}
    fmt = (data.get("format") or "csv").lower()
    kind = (data.get("kind") or "customers").lower()
    ts = time.strftime("%Y%m%d%H%M%S")

    if kind == "customers":
        text = export_mod.export_customers_csv(g.user_id)
        fname = "customers_%s.csv" % ts
        ctype = "text/csv"
    elif kind == "business":
        text = export_mod.export_business_csv(g.user_id)
        fname = "business_%s.csv" % ts
        ctype = "text/csv"
    elif kind == "all":
        text = export_mod.export_json(g.user_id)
        fname = "crm_backup_%s.json" % ts
        ctype = "application/json"
    else:
        return _err("未知导出类型")

    res = oss_mod.upload_text(fname, text, content_type=ctype)
    if "error" in res:
        # OSS 未配置时，直接返回内容（前端可本地下载）
        return _ok({"warning": "OSS 未配置，返回原始内容", "content": text[:5000]})
    return _ok({"url": res["url"], "object_key": res["object_key"]})


@app.route("/api/import", methods=["POST"])
def api_import():
    """导入 CSV（客户 / 业务）。从上传内容导入，kind 决定类型。
    返回 { imported, skipped, skipped_details, kind }，skipped_details 为被去重/过滤的明细。"""
    import export as export_mod
    data = request.json or {}
    kind = (data.get("kind") or "customers").lower()
    csv_text = data.get("csv") or ""
    if not csv_text.strip():
        return _err("缺少 csv 内容")
    if kind == "business":
        res = export_mod.import_business_csv(g.user_id, csv_text)
    else:
        res = export_mod.import_customers_csv(g.user_id, csv_text)
    res["kind"] = kind
    return _ok(res)


@app.route("/api/report", methods=["GET"])
def api_report():
    """生成汇总报告（周报用）。"""
    import export as export_mod
    rep = export_mod.generate_report(g.user_id)
    return _ok({"report": rep})


# ============ admin：审核 / 用户管理（仅管理员） ============

@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    if not g.is_admin:
        return _err("无权限", http=403)
    rows = db.query("SELECT id, username, phone, display_name, is_admin, status FROM users ORDER BY id")
    return _ok({"users": rows})


@app.route("/api/admin/users/<int:uid>/status", methods=["PUT"])
def api_admin_user_status(uid):
    if not g.is_admin:
        return _err("无权限", http=403)
    data = request.json or {}
    status = data.get("status", "")
    if status not in ("active", "pending", "disabled"):
        return _err("状态非法")
    db.execute("UPDATE users SET status=%s WHERE id=%s", (status, uid))
    return _ok({"message": "已更新"})


@app.route("/api/admin/bind-dingtalk", methods=["POST"])
def api_admin_bind_dingtalk():
    """管理员把钉钉 userId 绑定到本地账号（首次建账号用）。"""
    if not g.is_admin:
        return _err("无权限", http=403)
    data = request.json or {}
    uid = _int_or_none(data.get("user_id"))
    ding = (data.get("dingtalk_user_id") or "").strip()
    if not uid or not ding:
        return _err("缺少参数")
    db.execute("UPDATE users SET dingtalk_user_id=%s WHERE id=%s", (ding, uid))
    return _ok({"message": "已绑定"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

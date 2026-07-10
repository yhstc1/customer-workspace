"""
客户管理工作空间 - Flask 主应用
功能路由:
  /              - 首页（仪表盘）
  /customers     - 客户列表与管理
  /map           - 地图视图
  /tasks         - 事项看板
  /reports       - 报告列表与生成
  /settings      - 设置（我的位置）
  /dingtalk      - 钉钉入口（移动端适配）

API 路由:
  /api/customers         - GET/POST 客户 CRUD
  /api/customers/<id>    - GET/PUT/DELETE 单个客户
  /api/tasks             - GET/POST 事项 CRUD
  /api/tasks/<id>        - PUT/DELETE 单个事项
  /api/nearby            - GET 附近客户查询
  /api/geocode           - GET 地址地理编码
  /api/settings          - GET/PUT 设置
  /api/report/generate   - POST 生成报告
  /api/dingtalk/*        - 钉钉相关 API
"""
import os
import csv
import io
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory, send_file, redirect, url_for, session, Response

from models import get_db, init_db, seed_sample_data
from geo_service import geocode, find_nearby_customers
from report_generator import generate_daily_report, REPORTS_DIR
from dingtalk_config import (
    get_config_info, is_configured,
    DINGTALK_APP_KEY, DINGTALK_LOGIN_REDIRECT, DINGTALK_OAUTH2_AUTH_URL,
)
from dingtalk_service import (
    get_user_by_authcode, get_login_user_by_oauth2,
    test_connection, send_work_notification,
)

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "customer-workspace-secret-2026")

# 确保数据库表结构存在。
# gunicorn 等 WSGI 服务器不会执行 __main__，必须在模块加载时初始化，
# 否则线上首个请求就会因表不存在而 500。init_db() 是幂等的（CREATE IF NOT EXISTS）。
try:
    init_db()
except Exception as _e:  # noqa: BLE001
    print(f"[WARN] init_db 失败: {_e}")


# ==================== 登录门禁 ====================
# 未登录访问受保护页面时，自动跳到扫码登录页。
# 说明：若钉钉未配置（没填 AppKey/AppSecret），则不启用门禁，
#       本地部署可直接使用，不会被登录页挡住。

# 无需登录即可访问的路径前缀（白名单）
_PUBLIC_PREFIXES = (
    "/login",
    "/logout",
    "/api/dingtalk/oauth",   # 扫码回调 + 授权地址
    "/api/dingtalk/status",  # 前端探测配置状态
    "/static/",
    "/reports/",             # 已生成的报告静态文件
    "/download",             # 项目下载
)


@app.before_request
def _require_login():
    # 钉钉未配置 -> 不启用登录门禁，直接放行（本地无鉴权模式）
    if not is_configured():
        return None
    path = request.path
    if any(path == p or path.startswith(p) for p in _PUBLIC_PREFIXES):
        return None
    if session.get("dingtalk_user"):
        return None
    # 未登录：页面请求跳登录页，API 请求返回 401
    if path.startswith("/api/"):
        return jsonify({"error": "未登录", "login_url": "/login"}), 401
    return redirect("/login")


# ==================== 页面路由 ====================

@app.route("/")
def index():
    """仪表盘首页"""
    return render_template("index.html")


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

    sql = "SELECT * FROM customers WHERE 1=1"
    params = []
    if search:
        sql += " AND (name LIKE ? OR company LIKE ? OR address LIKE ? OR phone LIKE ?)"
        params.extend([f"%{search}%"] * 4)
    if category:
        sql += " AND category = ?"
        params.append(category)
    sql += " ORDER BY priority DESC, updated_at DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/customers", methods=["POST"])
def add_customer():
    """新增客户"""
    data = request.json
    conn = get_db()

    # 如果没有经纬度，尝试地理编码
    if not data.get("latitude") or not data.get("longitude"):
        if data.get("address"):
            coords = geocode(data["address"])
            if coords:
                data["latitude"] = coords[0]
                data["longitude"] = coords[1]

    cur = conn.execute("""
        INSERT INTO customers (name, company, phone, email, address, latitude, longitude, category, priority, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("name", ""), data.get("company", ""), data.get("phone", ""),
        data.get("email", ""), data.get("address", ""), data.get("latitude"),
        data.get("longitude"), data.get("category", ""),
        data.get("priority", "中"), data.get("notes", "")
    ))
    conn.commit()
    customer_id = cur.lastrowid
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    conn.close()
    return jsonify(dict(customer)), 201


@app.route("/api/customers/<int:cid>", methods=["GET"])
def get_customer(cid):
    """获取单个客户"""
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    if not customer:
        conn.close()
        return jsonify({"error": "客户不存在"}), 404
    tasks = conn.execute("SELECT * FROM tasks WHERE customer_id = ? ORDER BY due_date", (cid,)).fetchall()
    conn.close()
    return jsonify({"customer": dict(customer), "tasks": [dict(t) for t in tasks]})


@app.route("/api/customers/<int:cid>", methods=["PUT"])
def update_customer(cid):
    """更新客户"""
    data = request.json
    conn = get_db()

    # 如果地址变了且没有手动改经纬度，重新地理编码
    if data.get("address"):
        existing = conn.execute("SELECT address, latitude, longitude FROM customers WHERE id = ?", (cid,)).fetchone()
        if existing and existing["address"] != data["address"]:
            coords = geocode(data["address"])
            if coords:
                data["latitude"] = coords[0]
                data["longitude"] = coords[1]

    conn.execute("""
        UPDATE customers SET
            name=?, company=?, phone=?, email=?, address=?, latitude=?, longitude=?,
            category=?, priority=?, notes=?, updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        data.get("name"), data.get("company"), data.get("phone"),
        data.get("email"), data.get("address"), data.get("latitude"),
        data.get("longitude"), data.get("category", ""),
        data.get("priority", "中"), data.get("notes", ""), cid
    ))
    conn.commit()
    customer = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    conn.close()
    return jsonify(dict(customer))


@app.route("/api/customers/<int:cid>", methods=["DELETE"])
def delete_customer(cid):
    """删除客户"""
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id = ?", (cid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


# 客户导入模板列（顺序即 CSV 列顺序）
CUSTOMER_IMPORT_COLUMNS = ["公司名称", "联系人", "联系方式", "邮箱", "地址", "分类", "优先级", "备注"]


@app.route("/api/customers/template", methods=["GET"])
def customer_template():
    """下载客户批量导入 CSV 模板（UTF-8 with BOM，Excel 可直接打开）"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CUSTOMER_IMPORT_COLUMNS)
    # 示例行
    writer.writerow(["示例科技有限公司", "张三", "138-0000-0000", "zhangsan@example.com",
                     "上海市浦东新区张江路100号", "核心要客", "高", "这是示例，可删除"])
    writer.writerow(["", "", "", "", "", "TOP20", "中", ""])
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

    header = [h.strip() for h in rows[0]]
    valid_categories = {"核心要客", "TOP20", ""}
    conn = get_db()
    success, failed, errors = 0, 0, []

    for idx, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # 跳过空行
        record = {header[i]: (row[i].strip() if i < len(row) else "") for i in range(len(header))}
        company = record.get("公司名称", "")
        name = record.get("联系人", "")
        if not name and not company:
            failed += 1
            errors.append(f"第{idx}行：公司名称和联系人均为空，跳过")
            continue
        category = record.get("分类", "")
        if category not in valid_categories:
            category = ""  # 非法分类置空
        priority = record.get("优先级", "中") or "中"
        if priority not in {"高", "中", "低"}:
            priority = "中"
        try:
            conn.execute("""
                INSERT INTO customers (name, company, phone, email, address, category, priority, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name or company, company, record.get("联系方式", ""),
                record.get("邮箱", ""), record.get("地址", ""),
                category, priority, record.get("备注", "")
            ))
            success += 1
        except Exception as e:
            failed += 1
            errors.append(f"第{idx}行：{e}")

    conn.commit()
    conn.close()
    return jsonify({
        "message": f"导入完成：成功 {success} 条，失败 {failed} 条",
        "success": success, "failed": failed, "errors": errors[:20]
    })


@app.route("/api/customers/<int:cid>/businesses", methods=["GET"])
def get_customer_businesses(cid):
    """获取某客户的业务列表（用于客户详情展示）"""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM businesses WHERE customer_id = ? ORDER BY start_date DESC, id DESC", (cid,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ==================== 业务 API ====================

@app.route("/api/business", methods=["GET"])
def get_businesses():
    """获取业务列表（支持按公司名称/合同编码/业务号码模糊搜索）"""
    conn = get_db()
    search = request.args.get("search", "")
    sql = """
        SELECT b.*, c.name AS customer_name
        FROM businesses b LEFT JOIN customers c ON b.customer_id = c.id
        WHERE 1=1
    """
    params = []
    if search:
        sql += " AND (b.company_name LIKE ? OR b.contract_code LIKE ? OR b.business_number LIKE ? OR b.business_type LIKE ?)"
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
    cur = conn.execute("""
        INSERT INTO businesses (customer_id, company_name, business_address, business_number,
            contract_code, business_type, contract_amount, start_date, end_date, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("customer_id") or None, data.get("company_name", ""),
        data.get("business_address", ""), data.get("business_number", ""),
        data.get("contract_code", ""), data.get("business_type", ""),
        data.get("contract_amount"), data.get("start_date", ""),
        data.get("end_date", ""), data.get("notes", "")
    ))
    conn.commit()
    bid = cur.lastrowid
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201


@app.route("/api/business/<int:bid>", methods=["GET"])
def get_business(bid):
    """获取单个业务"""
    conn = get_db()
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "业务不存在"}), 404
    return jsonify(dict(row))


@app.route("/api/business/<int:bid>", methods=["PUT"])
def update_business(bid):
    """更新业务"""
    data = request.json
    conn = get_db()
    conn.execute("""
        UPDATE businesses SET
            customer_id=?, company_name=?, business_address=?, business_number=?,
            contract_code=?, business_type=?, contract_amount=?, start_date=?, end_date=?,
            notes=?, updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        data.get("customer_id") or None, data.get("company_name", ""),
        data.get("business_address", ""), data.get("business_number", ""),
        data.get("contract_code", ""), data.get("business_type", ""),
        data.get("contract_amount"), data.get("start_date", ""),
        data.get("end_date", ""), data.get("notes", ""), bid
    ))
    conn.commit()
    row = conn.execute("SELECT * FROM businesses WHERE id = ?", (bid,)).fetchone()
    conn.close()
    return jsonify(dict(row))


@app.route("/api/business/<int:bid>", methods=["DELETE"])
def delete_business(bid):
    """删除业务"""
    conn = get_db()
    conn.execute("DELETE FROM businesses WHERE id = ?", (bid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


# ==================== 事项 API ====================

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    """获取事项列表"""
    conn = get_db()
    status = request.args.get("status", "")

    sql = """
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id
    """
    params = []
    if status:
        sql += " WHERE t.status = ?"
        params.append(status)
    sql += " ORDER BY CASE t.priority WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 END, t.due_date"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/tasks", methods=["POST"])
def add_task():
    """新增事项"""
    data = request.json
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO tasks (customer_id, title, description, status, priority, progress, due_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("customer_id"), data.get("title", ""), data.get("description", ""),
        data.get("status", "待处理"), data.get("priority", "中"),
        data.get("progress", 0), data.get("due_date")
    ))
    conn.commit()
    task_id = cur.lastrowid
    task = conn.execute("""
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id WHERE t.id = ?
    """, (task_id,)).fetchone()
    conn.close()
    return jsonify(dict(task)), 201


@app.route("/api/tasks/<int:tid>", methods=["PUT"])
def update_task(tid):
    """更新事项"""
    data = request.json
    conn = get_db()
    conn.execute("""
        UPDATE tasks SET
            title=?, description=?, status=?, priority=?, progress=?, due_date=?,
            updated_at=datetime('now','localtime')
        WHERE id=?
    """, (
        data.get("title"), data.get("description"), data.get("status"),
        data.get("priority"), data.get("progress", 0), data.get("due_date"), tid
    ))
    conn.commit()
    task = conn.execute("""
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t JOIN customers c ON t.customer_id = c.id WHERE t.id = ?
    """, (tid,)).fetchone()
    conn.close()
    return jsonify(dict(task))


@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
def delete_task(tid):
    """删除事项"""
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
    conn.commit()
    conn.close()
    return jsonify({"message": "已删除"})


# ==================== 地图 & 附近客户 API ====================

@app.route("/api/nearby", methods=["GET"])
def get_nearby():
    """查询附近客户"""
    lat = float(request.args.get("lat", 0))
    lon = float(request.args.get("lon", 0))
    radius = float(request.args.get("radius", 10))

    conn = get_db()
    customers = [dict(r) for r in conn.execute("SELECT * FROM customers").fetchall()]
    conn.close()

    nearby = find_nearby_customers(lat, lon, customers, radius)
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


# ==================== 设置 API ====================

@app.route("/api/settings", methods=["GET"])
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/settings", methods=["PUT"])
def update_settings():
    data = request.json
    conn = get_db()
    for key, value in data.items():
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()
    return jsonify({"message": "设置已保存"})


# ==================== 报告 API ====================

@app.route("/api/report/generate", methods=["POST"])
def api_generate_report():
    """一键生成报告"""
    filepath = generate_daily_report()
    filename = os.path.basename(filepath)
    return jsonify({"message": "报告已生成", "filename": filename, "url": f"/reports/{filename}"})


@app.route("/api/reports", methods=["GET"])
def list_reports():
    """列出所有报告"""
    if not os.path.exists(REPORTS_DIR):
        return jsonify([])
    files = sorted(os.listdir(REPORTS_DIR), reverse=True)
    reports = []
    for f in files:
        if f.endswith(".html"):
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
    """提供报告文件访问"""
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

    # 打包目标：/workspace/customer-workspace
    project_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = "/tmp/customer-workspace-export.zip"

    if os.path.exists(zip_path):
        os.remove(zip_path)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            # 排除缓存
            if "__pycache__" in root:
                continue
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
    """仪表盘统计数据"""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    total_customers = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='待处理'").fetchone()[0]
    in_progress = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='进行中'").fetchone()[0]
    completed = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='已完成'").fetchone()[0]
    overdue = conn.execute("SELECT COUNT(*) FROM tasks WHERE due_date < ? AND status != '已完成'", (today,)).fetchone()[0]
    vip = conn.execute("SELECT COUNT(*) FROM customers WHERE category='核心要客'").fetchone()[0]

    # 最近事项
    recent_tasks = [dict(r) for r in conn.execute("""
        SELECT t.*, c.name as customer_name
        FROM tasks t JOIN customers c ON t.customer_id = c.id
        ORDER BY t.updated_at DESC LIMIT 5
    """).fetchall()]

    # 优先级分布
    priority_dist = [dict(r) for r in conn.execute("""
        SELECT priority, COUNT(*) as count FROM tasks WHERE status != '已完成' GROUP BY priority
    """).fetchall()]

    conn.close()

    return jsonify({
        "total_customers": total_customers,
        "total_tasks": total_tasks,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "overdue": overdue,
        "vip": vip,
        "completion_rate": round(completed / max(total_tasks, 1) * 100, 1),
        "recent_tasks": recent_tasks,
        "priority_dist": priority_dist,
    })


# ==================== 钉钉集成路由 ====================

@app.route("/login")
def login_page():
    """扫码登录页（内嵌钉钉二维码）"""
    # 已登录直接回首页
    if session.get("dingtalk_user"):
        return redirect("/")
    return render_template(
        "login.html",
        configured=is_configured(),
        app_key=DINGTALK_APP_KEY,
        redirect_uri=DINGTALK_LOGIN_REDIRECT,
        auth_base=DINGTALK_OAUTH2_AUTH_URL,
    )


@app.route("/logout")
def logout():
    """退出登录"""
    session.clear()
    return redirect("/login")


@app.route("/api/dingtalk/oauth/callback")
def dingtalk_oauth_callback():
    """
    扫码登录回调：钉钉授权成功后前端带 authCode 跳到这里。
    换取用户身份 -> 写 session -> 回首页。
    """
    auth_code = request.args.get("authCode") or request.args.get("code")
    if not auth_code:
        return redirect("/login?error=" + "缺少授权码")

    user_info = get_login_user_by_oauth2(auth_code)
    if user_info:
        session["dingtalk_user"] = user_info
        session["login_source"] = "dingtalk_scan"
        return redirect("/")
    return redirect("/login?error=" + "登录失败，请重试")


@app.route("/dingtalk")
def dingtalk_entry():
    """
    钉钉微应用入口
    钉钉客户端打开应用时会带上 ?authCode=xxx 参数
    这里获取用户身份后跳转到首页
    """
    auth_code = request.args.get("authCode") or request.args.get("code")
    if auth_code and is_configured():
        # 用 authCode 换取用户身份
        user_info = get_user_by_authcode(auth_code)
        if user_info:
            session["dingtalk_user"] = user_info
            session["login_source"] = "dingtalk"

    # 判断是否为移动端
    ua = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in ua for x in ["mobile", "android", "iphone", "harmony", "phone"])

    if is_mobile:
        return render_template("mobile_index.html", dingtalk_user=session.get("dingtalk_user"))
    return redirect("/")


@app.route("/m")
def mobile_entry():
    """移动端入口（非钉钉场景，直接浏览器访问）"""
    ua = request.headers.get("User-Agent", "").lower()
    is_mobile = any(x in ua for x in ["mobile", "android", "iphone", "harmony", "phone"])
    if is_mobile:
        return render_template("mobile_index.html")
    return redirect("/")


@app.route("/api/dingtalk/auth", methods=["POST"])
def dingtalk_auth():
    """钉钉免登接口：前端拿到 authCode 后调此接口换取用户信息"""
    auth_code = request.json.get("authCode")
    if not auth_code:
        return jsonify({"error": "缺少 authCode"}), 400

    user_info = get_user_by_authcode(auth_code)
    if user_info:
        session["dingtalk_user"] = user_info
        session["login_source"] = "dingtalk"
        return jsonify({"user": user_info})
    return jsonify({"error": "免登失败"}), 401


@app.route("/api/dingtalk/status", methods=["GET"])
def dingtalk_status():
    """获取钉钉配置状态"""
    return jsonify({
        "configured": is_configured(),
        "config": get_config_info(),
        "current_user": session.get("dingtalk_user"),
    })


@app.route("/api/dingtalk/test", methods=["POST"])
def dingtalk_test():
    """测试钉钉连接"""
    result = test_connection()
    return jsonify(result)


@app.route("/api/dingtalk/notify", methods=["POST"])
def dingtalk_notify():
    """推送消息到钉钉（如报告生成通知）"""
    data = request.json
    user_id = data.get("user_id") or session.get("dingtalk_user", {}).get("userid")
    if not user_id:
        return jsonify({"error": "未指定接收人，请先通过钉钉登录"}), 400

    title = data.get("title", "客户工作空间通知")
    content = data.get("content", "")
    url = data.get("url", "")

    ok = send_work_notification(user_id, title, content, url)
    if ok:
        return jsonify({"message": "消息已推送"})
    return jsonify({"error": "推送失败"}), 500


# ==================== 启动 ====================

if __name__ == "__main__":
    init_db()
    # 注意：不再自动填充示例数据（用户已清空并进入真实使用）。
    # 如需重新生成演示数据，可手动执行 `python models.py`。
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 60)
    print("  客户管理工作空间已启动")
    print(f"  本地访问:    http://localhost:{port}")
    print(f"  移动端入口:  http://localhost:{port}/m")
    print(f"  钉钉入口:    http://localhost:{port}/dingtalk")
    if is_configured():
        print(f"  钉钉集成:    已配置 ✓")
    else:
        print(f"  钉钉集成:    未配置（见 dingtalk_config.py）")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

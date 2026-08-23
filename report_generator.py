"""
每日客户报告生成器
- 生成 HTML 格式的专属客户报告
- 内容：今日概览、待办事项、附近客户、事项统计
"""
import os
from collections import Counter
from datetime import datetime
from models import get_db
from geo_service import find_nearby_customers

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def generate_daily_report(user_id=None):
    """
    生成今日客户报告（按用户隔离）
    返回: 报告文件路径
    """
    conn = get_db()
    cur = conn.cursor()

    uid = user_id if user_id is not None else 0

    # 获取我的位置（当前用户）
    settings = {row["key"]: row["value"] for row in
                cur.execute("SELECT key, value FROM settings WHERE user_id=?", (uid,)).fetchall()}

    my_lat = float(settings.get("my_latitude", 31.2036))
    my_lon = float(settings.get("my_longitude", 121.6040))
    my_location_name = settings.get("my_location_name", "未设置")
    radius_km = float(settings.get("default_radius_km", 10))

    # 获取当前用户的客户
    customers = [dict(row) for row in cur.execute(
        "SELECT * FROM customers WHERE user_id=? ORDER BY priority DESC, updated_at DESC", (uid,)
    ).fetchall()]

    # 获取当前用户的事项
    all_tasks = [dict(row) for row in cur.execute("""
        SELECT t.*, c.name as customer_name, c.company as customer_company
        FROM tasks t
        JOIN customers c ON t.customer_id = c.id
        WHERE t.user_id = ?
        ORDER BY
            CASE t.status WHEN '进行中' THEN 1 WHEN '已归档' THEN 2 WHEN '已完结' THEN 3 ELSE 4 END,
            t.due_date
    """, (uid,)).fetchall()]

    # 查找附近客户
    nearby_customers = find_nearby_customers(my_lat, my_lon, [dict(c) for c in customers], radius_km)

    # 统计数据：原生聚合（Counter 单遍计数 + sum 生成器），避免手写累加循环
    today = datetime.now().strftime("%Y-%m-%d")
    status_counts = Counter(t["status"] for t in all_tasks)
    in_progress_tasks = status_counts.get("进行中", 0)
    completed_tasks = status_counts.get("已完结", 0)
    archived_tasks = status_counts.get("已归档", 0)
    vip_count = sum(1 for c in customers if c["category"] == "VIP客户")
    # 逾期事项（仍需列表用于表格渲染，此处直接复用其长度作为统计）
    overdue_tasks = [t for t in all_tasks if t["due_date"] and t["due_date"] < today and t["status"] != "已完结"]
    stats = {
        "total_customers": len(customers),
        "total_tasks": len(all_tasks),
        "in_progress_tasks": in_progress_tasks,
        "completed_tasks": completed_tasks,
        "archived_tasks": archived_tasks,
        "overdue_tasks": len(overdue_tasks),
        "nearby_count": len(nearby_customers),
        "vip_count": vip_count,
    }

    # 今日到期事项
    today_tasks = [t for t in all_tasks if t["due_date"] == today]

    # 生成 HTML
    html = build_report_html(today, my_location_name, stats, nearby_customers,
                             all_tasks, overdue_tasks, today_tasks, radius_km)

    # 保存文件（文件名带 user_id 以隔离不同用户的报告）
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = f"daily_report_{uid}_{today}.html"
    filepath = os.path.join(REPORTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)

    conn.close()
    print(f"[OK] 报告已生成: {filepath}")
    return filepath


def build_report_html(date, location, stats, nearby, tasks, overdue, today_tasks, radius):
    """构建报告 HTML"""
    # 附近客户表格行
    nearby_rows = ""
    for i, c in enumerate(nearby[:15], 1):
        nearby_rows += f"""
            <tr>
                <td>{i}</td>
                <td><strong>{c['name']}</strong></td>
                <td>{c.get('company', '')}</td>
                <td>{c.get('category', '')}</td>
                <td><span class="badge badge-distance">{c['distance_km']} km</span></td>
                <td>{c.get('phone', '')}</td>
            </tr>
        """
    if not nearby_rows:
        nearby_rows = '<tr><td colspan="6" class="empty">附近 {radius} 公里内暂无客户</td></tr>'.format(radius=radius)

    # 待办事项表格行（进行中 + 已归档）
    pending_tasks = [t for t in tasks if t["status"] in ("进行中", "已归档")]
    task_rows = ""
    for i, t in enumerate(pending_tasks[:20], 1):
        status_class = f"status-{t['status']}"
        overdue_flag = ""
        if t["due_date"] and t["due_date"] < date and t["status"] != "已完结":
            overdue_flag = '<span class="overdue-flag">⚠ 逾期</span>'

        task_rows += f"""
            <tr>
                <td>{i}</td>
                <td><strong>{t['customer_name']}</strong><br><small>{t.get('customer_company', '')}</small></td>
                <td>{t['title']}</td>
                <td><span class="badge {status_class}">{t['status']}</span></td>
                <td>{t['due_date'] or '-'} {overdue_flag}</td>
            </tr>
        """
    if not task_rows:
        task_rows = '<tr><td colspan="5" class="empty">暂无待办事项 🎉</td></tr>'

    # 逾期事项
    overdue_rows = ""
    for t in overdue:
        overdue_rows += f"""
            <tr>
                <td><strong>{t['customer_name']}</strong></td>
                <td>{t['title']}</td>
                <td>{t['due_date']}</td>
                <td><span class="badge status-{t['status']}">{t['status']}</span></td>
            </tr>
        """
    if not overdue_rows:
        overdue_rows = '<tr><td colspan="4" class="empty">无逾期事项 ✅</td></tr>'

    completion_rate = round(stats["completed_tasks"] / max(stats["total_tasks"], 1) * 100, 1)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>客户日报 - {date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
            background: #f0f2f5;
            color: #333;
            line-height: 1.6;
            padding: 20px;
        }}
        .report {{
            max-width: 900px;
            margin: 0 auto;
            background: #fff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        }}
        .report-header {{
            background: linear-gradient(135deg, #007FFF 0%, #0055B3 100%);
            color: #fff;
            padding: 30px 40px;
        }}
        .report-header h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .report-header .meta {{ opacity: 0.9; font-size: 14px; }}
        .report-body {{ padding: 30px 40px; }}

        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 16px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #f8f9fc;
            border-radius: 10px;
            padding: 18px;
            text-align: center;
            border-left: 4px solid #007FFF;
        }}
        .stat-card.danger {{ border-left-color: #e74c3c; }}
        .stat-card.success {{ border-left-color: #27ae60; }}
        .stat-card.warning {{ border-left-color: #f39c12; }}
        .stat-value {{ font-size: 28px; font-weight: 700; color: #333; }}
        .stat-label {{ font-size: 13px; color: #888; margin-top: 4px; }}

        h2 {{
            font-size: 18px;
            color: #333;
            margin: 25px 0 15px;
            padding-bottom: 8px;
            border-bottom: 2px solid #eee;
        }}
        h2 .icon {{ margin-right: 8px; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        th {{
            background: #f8f9fc;
            padding: 12px 10px;
            text-align: left;
            font-weight: 600;
            color: #555;
            border-bottom: 2px solid #e0e0e0;
        }}
        td {{
            padding: 10px;
            border-bottom: 1px solid #f0f0f0;
        }}
        tr:hover td {{ background: #fafbfc; }}
        .empty {{ text-align: center; color: #aaa; padding: 30px; }}

        .badge {{
            display: inline-block;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }}
        .badge-distance {{ background: #e8f5e9; color: #2e7d32; }}
        .status-进行中 {{ background: #e3f2fd; color: #1565c0; }}
        .status-已完结 {{ background: #e8f5e9; color: #2e7d32; }}
        .status-已归档 {{ background: #f5f5f5; color: #9e9e9e; }}

        .overdue-flag {{ color: #e74c3c; font-size: 12px; margin-left: 4px; }}

        .alert-box {{
            background: #fff3e0;
            border: 1px solid #ffe0b2;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 20px;
        }}
        .alert-box h3 {{ color: #e65100; font-size: 15px; margin-bottom: 8px; }}

        .report-footer {{
            text-align: center;
            padding: 20px;
            color: #aaa;
            font-size: 12px;
            border-top: 1px solid #f0f0f0;
        }}

        @media print {{
            body {{ background: #fff; padding: 0; }}
            .report {{ box-shadow: none; max-width: 100%; }}
        }}
    </style>
</head>
<body>
    <div class="report">
        <div class="report-header">
            <h1>📊 每日客户跟进报告</h1>
            <div class="meta">
                📅 {date} &nbsp;|&nbsp;
                📍 我的位置：{location} &nbsp;|&nbsp;
                🔍 附近 {radius} 公里内有 <strong>{stats['nearby_count']}</strong> 位客户
            </div>
        </div>

        <div class="report-body">
            <!-- 统计概览 -->
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-value">{stats['total_customers']}</div>
                    <div class="stat-label">客户总数</div>
                </div>
                <div class="stat-card warning">
                    <div class="stat-value">{stats['in_progress_tasks']}</div>
                    <div class="stat-label">进行中事项</div>
                </div>
                <div class="stat-card success">
                    <div class="stat-value">{stats['completed_tasks']}</div>
                    <div class="stat-label">已完结事项</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">{completion_rate}%</div>
                    <div class="stat-label">完成率</div>
                </div>
            </div>

            <!-- 逾期警告 -->
            {"" if not overdue else f'''
            <div class="alert-box">
                <h3>⚠️ 有 {len(overdue)} 个逾期事项需要关注</h3>
                <table>
                    <thead><tr><th>客户</th><th>事项</th><th>截止日期</th><th>状态</th></tr></thead>
                    <tbody>{overdue_rows}</tbody>
                </table>
            </div>
            '''}

            <!-- 附近客户 -->
            <h2><span class="icon">🗺️</span>附近客户（{radius}公里内）</h2>
            <table>
                <thead>
                    <tr><th>#</th><th>客户</th><th>公司</th><th>分类</th><th>距离</th><th>电话</th></tr>
                </thead>
                <tbody>{nearby_rows}</tbody>
            </table>

            <!-- 待办事项 -->
            <h2><span class="icon">📝</span>待办事项（进行中 + 已归档）</h2>
            <table>
                <thead>
                    <tr><th>#</th><th>客户</th><th>事项</th><th>状态</th><th>截止</th></tr>
                </thead>
                <tbody>{task_rows}</tbody>
            </table>

            <!-- 今日小结 -->
            <h2><span class="icon">💡</span>今日建议</h2>
            <div style="background: #f8f9fc; padding: 16px; border-radius: 8px; font-size: 14px;">
                <p>• 共有 <strong>{stats['in_progress_tasks']}</strong> 个进行中事项，建议优先跟进；<strong>{stats['archived_tasks']}</strong> 个已归档事项可评估是否恢复</p>
                <p>• 有 <strong>{len(overdue)}</strong> 个逾期事项，请尽快跟进</p>
                <p>• 附近有 <strong>{stats['nearby_count']}</strong> 位客户，可考虑安排线下拜访</p>
                <p>• 当前整体完成率为 <strong>{completion_rate}%</strong></p>
            </div>
        </div>

        <div class="report-footer">
            本报告由客户管理平台自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </div>
    </div>
</body>
</html>"""
    return html


if __name__ == "__main__":
    filepath = generate_daily_report()
    print(f"报告路径: {filepath}")

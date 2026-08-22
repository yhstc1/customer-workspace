# -*- coding: utf-8 -*-
"""数据导出 / 导入 / 报告生成。

导出：生成 CSV 或 JSON，上传到 OSS 并返回签名 URL（前端 export 页轮询下载）。
导入：从上传的 CSV 批量写入（customers / businesses）。
报告：基于现有 report_generator 逻辑，生成周报文本/JSON。
"""
import io
import csv
import json
import time
import config
import db


def export_customers_csv(user_id):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "company", "name", "phone", "address", "business_type",
                     "importance", "tier", "latitude", "longitude", "notes", "created_at"])
    rows = db.query("SELECT * FROM customers WHERE user_id=%s ORDER BY id", (user_id,))
    for r in rows:
        writer.writerow([r.get("id"), r.get("company"), r.get("name"), r.get("phone"),
                         r.get("address"), r.get("business_type"), r.get("importance"),
                         r.get("tier"), r.get("latitude"), r.get("longitude"),
                         r.get("notes"), r.get("created_at")])
    return buf.getvalue()


def export_business_csv(user_id):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "customer_id", "company_name", "business_type", "business_level",
                     "number", "contract_code", "contract_amount", "start_date", "end_date",
                     "business_address", "date", "user_name", "parent_id", "notes"])
    rows = db.query("SELECT * FROM businesses WHERE user_id=%s ORDER BY id", (user_id,))
    for r in rows:
        writer.writerow([r.get("id"), r.get("customer_id"), r.get("company_name"),
                         r.get("business_type"), r.get("business_level"), r.get("number"),
                         r.get("contract_code"), r.get("contract_amount"), r.get("start_date"),
                         r.get("end_date"), r.get("business_address"), r.get("date"),
                         r.get("user_name"), r.get("parent_id"), r.get("notes")])
    return buf.getvalue()


def export_json(user_id):
    """全量导出为 JSON（含客户+业务+事项），供备份/恢复。"""
    data = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "customers": db.query("SELECT * FROM customers WHERE user_id=%s", (user_id,)),
        "businesses": db.query("SELECT * FROM businesses WHERE user_id=%s", (user_id,)),
        "tasks": db.query(
            "SELECT t.* FROM tasks t JOIN customers c ON t.customer_id=c.id WHERE c.user_id=%s",
            (user_id,)),
    }
    return json.dumps(data, ensure_ascii=False, default=str)


def import_customers_csv(user_id, csv_text):
    """从 CSV 批量导入客户（跳过表头，按列映射）。
    去重键：company（同一 user 下公司名相同视为重复，跳过并计入剔除明细）。
    返回 { imported, skipped, skipped_details:[{line, key, reason}] }。"""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"imported": 0, "skipped": 0, "skipped_details": []}
    header = [h.strip() for h in rows[0]]
    idx = {col: header.index(col) if col in header else -1 for col in
           ("company", "name", "phone", "address", "business_type", "importance", "tier", "notes")}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    # 已有客户名集合（去重用）
    existing = db.query("SELECT company FROM customers WHERE user_id=%s", (user_id,))
    seen = set((r.get("company") or "").strip() for r in existing if r.get("company"))
    imported = 0
    skipped = 0
    skipped_details = []
    file_seen = set()
    for i, r in enumerate(rows[1:], start=2):  # 行号从 2 起（含表头）
        if not r:
            continue
        get = lambda k: r[idx[k]].strip() if idx.get(k, -1) >= 0 and idx[k] < len(r) else ""
        company = get("company")
        if not company:
            skipped += 1
            skipped_details.append({"line": i, "key": "", "reason": "公司名为空，跳过"})
            continue
        # 文件内重复
        if company in file_seen:
            skipped += 1
            skipped_details.append({"line": i, "key": company, "reason": "同一文件内公司名重复，跳过"})
            continue
        # 库内已存在
        if company in seen:
            skipped += 1
            skipped_details.append({"line": i, "key": company, "reason": "库内已存在同名客户，跳过"})
            continue
        file_seen.add(company)
        seen.add(company)
        cid = db.execute(
            "INSERT INTO customers (company, name, phone, address, business_type, "
            "importance, tier, notes, user_id, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (company, get("name"), get("phone"), get("address"), get("business_type"),
             get("importance"), get("tier"), get("notes"), user_id, now, now))
        if cid:
            imported += 1
        else:
            skipped += 1
            skipped_details.append({"line": i, "key": company, "reason": "写入失败，跳过"})
    return {"imported": imported, "skipped": skipped, "skipped_details": skipped_details}


def import_business_csv(user_id, csv_text):
    """从 CSV 批量导入业务台账（跳过表头，按列映射）。
    去重键：number + company_name（业务号码 + 公司名，同一 user 下相同视为重复）。
    号码为空时仅按 company_name 判断（空号码通常无法唯一标识，仍按 number+company 组合跳过）。
    返回 { imported, skipped, skipped_details:[{line, key, reason}] }。"""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"imported": 0, "skipped": 0, "skipped_details": []}
    header = [h.strip() for h in rows[0]]
    cols = ("customer_id", "company_name", "business_type", "business_level", "number",
            "contract_code", "contract_amount", "start_date", "end_date",
            "business_address", "date", "user_name", "parent_id", "notes")
    idx = {c: (header.index(c) if c in header else -1) for c in cols}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    # 已有业务去重键集合：(number||'', company_name)
    existing = db.query("SELECT number, company_name FROM businesses WHERE user_id=%s", (user_id,))
    seen = set(((r.get("number") or "").strip(), (r.get("company_name") or "").strip()) for r in existing)
    imported = 0
    skipped = 0
    skipped_details = []
    file_seen = set()
    for i, r in enumerate(rows[1:], start=2):
        if not r or not r[0].strip():
            continue
        get = lambda k: r[idx[k]].strip() if idx.get(k, -1) >= 0 and idx[k] < len(r) else ""
        company = get("company_name")
        if not company:
            skipped += 1
            skipped_details.append({"line": i, "key": "", "reason": "公司名为空，跳过"})
            continue
        number = get("number")
        # 号码填了但格式异常（如含空格）保持原样匹配；组合键
        dup_key = (number, company)
        if dup_key in file_seen:
            skipped += 1
            skipped_details.append({"line": i, "key": "%s / %s" % (company, number or "(空号码)"),
                                    "reason": "同一文件内业务重复，跳过"})
            continue
        if dup_key in seen:
            skipped += 1
            skipped_details.append({"line": i, "key": "%s / %s" % (company, number or "(空号码)"),
                                    "reason": "库内已存在相同业务（号码+公司名），跳过"})
            continue
        file_seen.add(dup_key)
        seen.add(dup_key)
        try:
            amount = float(get("contract_amount")) if get("contract_amount") else None
        except Exception:
            amount = None
        try:
            cid = int(get("customer_id")) if get("customer_id") else None
        except Exception:
            cid = None
        try:
            pid = int(get("parent_id")) if get("parent_id") else None
        except Exception:
            pid = None
        bid = db.execute(
            "INSERT INTO businesses (customer_id, company_name, business_type, business_level, "
            "number, contract_code, contract_amount, start_date, end_date, business_address, "
            "date, user_name, parent_id, notes, user_id, created_at, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (cid, company, get("business_type"), get("business_level"), number,
             get("contract_code"), amount, get("start_date"), get("end_date"),
             get("business_address"), get("date"), get("user_name"), pid, get("notes"),
             user_id, now, now))
        if bid:
            imported += 1
        else:
            skipped += 1
            skipped_details.append({"line": i, "key": "%s / %s" % (company, number or "(空号码)"),
                                    "reason": "写入失败，跳过"})
    return {"imported": imported, "skipped": skipped, "skipped_details": skipped_details}


def generate_report(user_id):
    """周报/汇总：统计客户数、业务数、进行中事项，输出文本。"""
    c_count = db.query("SELECT COUNT(*) AS c FROM customers WHERE user_id=%s", (user_id,), one=True)["c"]
    b_count = db.query("SELECT COUNT(*) AS c FROM businesses WHERE user_id=%s", (user_id,), one=True)["c"]
    t_open = db.query(
        "SELECT COUNT(*) AS c FROM tasks t JOIN customers c ON t.customer_id=c.id "
        "WHERE c.user_id=%s AND t.status NOT IN ('已完结','已挂起')", (user_id,), one=True)["c"]
    t_done = db.query(
        "SELECT COUNT(*) AS c FROM tasks t JOIN customers c ON t.customer_id=c.id "
        "WHERE c.user_id=%s AND t.status='已完结'", (user_id,), one=True)["c"]
    return {
        "customer_count": c_count,
        "business_count": b_count,
        "task_open": t_open,
        "task_done": t_done,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

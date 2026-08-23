"""
一次性维护脚本：客户去重 + 地址地理编码回填
- 去重：按归一化公司名去重，保留最小 id（即最早导入的一条），删除其余重复
- 地理编码：为缺少经纬度的客户调用 geo_service.geocode（Nominatim -> photon 回退）补坐标

用法（在 Windows 主机上，用项目 venv 运行）：
    venv/Scripts/python.exe dedup_geocode.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import get_db, normalize_company
from geo_service import geocode

conn = get_db()

# ---------- 1) 去重 ----------
rows = conn.execute("SELECT id, company FROM customers ORDER BY id").fetchall()
seen = {}
to_delete = []
for r in rows:
    n = normalize_company(r["company"])
    if not n:
        continue
    if n in seen:
        to_delete.append(r["id"])
    else:
        seen[n] = r["id"]

before = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
if to_delete:
    conn.executemany("DELETE FROM customers WHERE id = ?", [(i,) for i in to_delete])
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    print(f"[去重] 删除重复客户 {len(to_delete)} 条，剩余 {after} 条（原 {before} 条）")
else:
    after = before
    print(f"[去重] 无重复客户，共 {before} 条")

# ---------- 2) 地理编码回填 ----------
missing = conn.execute(
    "SELECT id, company, address FROM customers WHERE latitude IS NULL OR longitude IS NULL"
).fetchall()
print(f"[地理编码] 待处理 {len(missing)} 条")
ok = fail = 0
for c in missing:
    if not c["address"]:
        fail += 1
        print(f"  跳过(无地址): {c['company']}")
        continue
    coords = geocode(c["address"])
    if coords:
        conn.execute(
            "UPDATE customers SET latitude=?, longitude=?, updated_at=datetime('now','localtime') WHERE id=?",
            (coords[0], coords[1], c["id"]),
        )
        conn.commit()
        ok += 1
        print(f"  OK   {c['company']} -> ({coords[0]:.5f}, {coords[1]:.5f})")
    else:
        fail += 1
        print(f"  FAIL {c['company']} : {c['address']}")
    time.sleep(0.5)  # 礼貌节流，避免触发地理编码服务限流

conn.close()
print(f"[完成] 地理编码成功 {ok} 条，失败 {fail} 条")

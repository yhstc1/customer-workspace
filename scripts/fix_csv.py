"""将桌面 CSV 模板的列：
    公司名称,联系人,联系方式,邮箱,地址,分类,优先级,备注
改写为：
    公司名称,法人,联系人,联系方式,邮箱,地址,分类,优先级,备注
原「联系人」列（即法定代表人）整体移入新增的「法人」列，「联系人」列留空。
"""
import csv

src = r"D:/Users/User185984/Desktop/customer_import_template.csv"
new_header = ["公司名称", "法人", "联系人", "联系方式", "邮箱", "地址", "分类", "优先级", "备注"]

# 原始文件为 GBK 编码（含中文），读取用 gbk；输出改为 UTF-8 with BOM，
# 既能正确保存中文，又兼容 Excel，且 app 的导入路由优先按 utf-8-sig 解析。
with open(src, encoding="gbk", newline="") as f:
    rows = list(csv.reader(f))

out_rows = [new_header]
for r in rows[1:]:
    if not any(c.strip() for c in r):
        continue
    while len(r) < 8:
        r.append("")
    company, legal, phone, email, address, cat, prio, note = (
        r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7]
    )
    out_rows.append([company, legal, "", phone, email, address, cat, prio, note])

with open(src, "w", encoding="utf-8-sig", newline="") as f:
    csv.writer(f).writerows(out_rows)

print(f"已重写 CSV，共 {len(out_rows) - 1} 条数据行。")

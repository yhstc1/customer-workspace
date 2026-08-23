import sqlite3, os, re

db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "customers.db")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT id, company, latitude, longitude FROM customers").fetchall()
print("total rows:", len(rows))

def norm(n):
    if not n: return ""
    s = n.strip().lower()
    s = s.replace("（", "(").replace("）", ")").replace("【", "[").replace("】", "]")
    s = re.sub(r"\s+", "", s)
    return s

from collections import Counter
c = Counter(norm(r["company"]) for r in rows)
dups = {k: v for k, v in c.items() if v > 1 and k}
print("duplicate companies (normalized):", len(dups))
for k, v in dups.items():
    print("  DUP x%d: %r" % (v, k))

geo = sum(1 for r in rows if r["latitude"] and r["longitude"])
print("rows with coordinates:", geo)
conn.close()

"""
客户管理平台 —— 隔离冒烟/集成测试套件

设计要点：
- 使用标准库 unittest，无需安装 pytest。
- 在导入 app 之前，把 models.DB_PATH 指向一个临时 SQLite 文件，
  并临时替换 report_generator.REPORTS_DIR 为临时目录，
  从而完全不触碰真实的 data/customers.db 与 reports/。
- 通过 Flask 的 test_client 走完整的 HTTP 路由，覆盖核心 API 与页面渲染。
- 网络相关（Nominatim 地理编码）不在自动化范围内；geo 部分只测纯函数。

运行方式（项目根目录）：
    venv/Scripts/python.exe -m unittest tests.test_app -v
或  venv/Scripts/python.exe tests/test_app.py
"""
import os
import sys
import io
import atexit
import tempfile
import shutil
import unittest
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT)

# ---- 隔离真实数据库与报告目录（必须在 import app 之前） ----
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
_tmp_reports = tempfile.mkdtemp(prefix="cw_reports_")

import models
import report_generator

models.DB_PATH = _tmp_db.name
report_generator.REPORTS_DIR = _tmp_reports

# 现在才导入主应用（触发 init_db() 在临时库上建表）
import app  # noqa: E402
from geo_service import find_nearby_customers, haversine  # noqa: E402  (纯函数，供测试直接调用)

# 向临时库填充示例数据，让 dashboard / 报告有内容可查
models.seed_sample_data()

app.app.config["TESTING"] = True
client = app.app.test_client()

# 测试中禁用钉钉真实推送，避免注册/审核用例污染钉钉群消息
app.notify_registration_pending = lambda *a, **k: None
app.notify_registration_approved = lambda *a, **k: None
app.notify_registration_rejected = lambda *a, **k: None

# 多用户改造后，所有受保护接口需鉴权：以管理员手机号登录，
# 其拥有 seed_sample_data 注入的示例数据。Flask 测试客户端会保持会话 Cookie。
_login = client.post("/api/login", json={"username": "18607184641", "password": "123456"})
assert _login.status_code == 200, _login.get_data(as_text=True)


def _cleanup():
    try:
        if os.path.exists(_tmp_db.name):
            os.remove(_tmp_db.name)
    except OSError:
        pass
    try:
        shutil.rmtree(_tmp_reports, ignore_errors=True)
    except OSError:
        pass


atexit.register(_cleanup)


class GeoPureTests(unittest.TestCase):
    """纯函数：不依赖网络，确定性校验。"""

    def test_haversine_known_distance(self):
        # 同一点的距离应为 0
        self.assertAlmostEqual(
            haversine(31.2036, 121.6040, 31.2036, 121.6040), 0.0, places=4
        )
        # 上海张江到人民广场（约 13km 量级）
        d = haversine(31.2036, 121.6040, 31.2304, 121.4737)
        self.assertTrue(10 < d < 16, f"距离应在 10~16km 之间，实际 {d:.2f}")

    def test_find_nearby_filters_by_radius(self):
        from geo_service import find_nearby_customers, haversine

        me = (31.2036, 121.6040)
        customers = [
            {"id": 1, "name": "近处", "latitude": 31.2040, "longitude": 121.6045},
            {"id": 2, "name": "远处", "latitude": 0.0, "longitude": 0.0},
        ]
        nearby = find_nearby_customers(me[0], me[1], customers, radius_km=5)
        names = [c["name"] for c in nearby]
        self.assertIn("近处", names)
        self.assertNotIn("远处", names)
        # 应带上 distance_km 字段且升序
        self.assertIn("distance_km", nearby[0])
        self.assertEqual(nearby[0]["name"], "近处")


class DashboardTests(unittest.TestCase):
    def test_dashboard_returns_stats(self):
        r = client.get("/api/dashboard")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertIn("total_customers", data)
        self.assertIn("completion_rate", data)
        # 至少包含 7 个示例客户（测试间共享同一临时库，可能叠加更多）
        self.assertGreaterEqual(data["total_customers"], 7)
        self.assertGreaterEqual(data["total_tasks"], 1)


class CustomerApiTests(unittest.TestCase):
    def _create(self, **over):
        payload = {
            "name": "测试客户",
            "company": "测试公司",
            "phone": "13800000000",
            "address": "上海市浦东新区张江路1号",
            "latitude": 31.2040,
            "longitude": 121.6045,
            "category": "核心要客",
            "priority": "高",
            "notes": "自动化测试创建",
        }
        payload.update(over)
        return client.post("/api/customers", json=payload)

    def test_customer_crud(self):
        # 创建
        r = self._create()
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        cid = r.get_json()["id"]
        self.assertIsInstance(cid, int)

        # 列表
        r = client.get("/api/customers")
        self.assertEqual(r.status_code, 200)
        ids = [c["id"] for c in r.get_json()]
        self.assertIn(cid, ids)

        # 详情（含 tasks 键）
        r = client.get(f"/api/customers/{cid}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("tasks", r.get_json())

        # 更新
        r = client.put(f"/api/customers/{cid}", json={"name": "改名客户", "priority": "低"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["name"], "改名客户")

        # 删除
        r = client.delete(f"/api/customers/{cid}")
        self.assertEqual(r.status_code, 200)
        r = client.get(f"/api/customers/{cid}")
        self.assertEqual(r.status_code, 404)

    def test_customer_search_filter(self):
        self._create(name="独一无二的客户XYZ")
        r = client.get("/api/customers?search=XYZ")
        self.assertEqual(r.status_code, 200)
        names = [c["name"] for c in r.get_json()]
        self.assertTrue(all("XYZ" in n for n in names))
        self.assertIn("独一无二的客户XYZ", names)


class TaskApiTests(unittest.TestCase):
    def setUp(self):
        r = client.post("/api/customers", json={
            "name": "事项宿主", "latitude": 31.20, "longitude": 121.60
        })
        self.cid = r.get_json()["id"]

    def test_task_crud(self):
        r = client.post("/api/tasks", json={
            "customer_id": self.cid, "title": "跟进电话", "status": "进行中"
        })
        self.assertEqual(r.status_code, 201)
        tid = r.get_json()["id"]

        r = client.get("/api/tasks")
        self.assertEqual(r.status_code, 200)
        self.assertIn(tid, [t["id"] for t in r.get_json()])

        r = client.put(f"/api/tasks/{tid}", json={
            "customer_id": self.cid, "title": "跟进电话", "description": "准备方案",
            "status": "已完结", "due_date": ""
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "已完结")

        r = client.get("/api/tasks?status=已完结")
        self.assertEqual(r.status_code, 200)
        self.assertIn(tid, [t["id"] for t in r.get_json()])

        r = client.delete(f"/api/tasks/{tid}")
        self.assertEqual(r.status_code, 200)


class BusinessApiTests(unittest.TestCase):
    def setUp(self):
        r = client.post("/api/customers", json={
            "name": "业务宿主", "latitude": 31.20, "longitude": 121.60
        })
        self.cid = r.get_json()["id"]

    def test_business_crud(self):
        r = client.post("/api/business", json={
            "customer_id": self.cid, "company_name": "业务公司", "business_type": "专线"
        })
        self.assertEqual(r.status_code, 201)
        bid = r.get_json()["id"]

        r = client.get("/api/business")
        self.assertEqual(r.status_code, 200)
        biz_list = r.get_json()  # 只解析一次响应体（Werkzeug 测试响应体为可消费流）
        self.assertIn(bid, [b["id"] for b in biz_list])

        r = client.get(f"/api/business/{bid}")
        self.assertEqual(r.status_code, 200)

        r = client.put(f"/api/business/{bid}", json={"business_type": "SDH"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["business_type"], "SDH")

        # 客户详情下的业务列表
        r = client.get(f"/api/customers/{self.cid}/businesses")
        self.assertEqual(r.status_code, 200)
        self.assertIn(bid, [b["id"] for b in r.get_json()])

        r = client.delete(f"/api/business/{bid}")
        self.assertEqual(r.status_code, 200)

    def test_business_update_recalc_priority(self):
        """编辑业务改关联客户后，新旧客户优先级都应重算（有信息客户不删除）"""
        cid_a = client.post("/api/customers", json={"company": "优先级甲", "name": "法人甲"}).get_json()["id"]
        cid_b = client.post("/api/customers", json={"company": "优先级乙", "name": "法人乙"}).get_json()["id"]
        bid = client.post("/api/business", json={"customer_id": cid_a, "company_name": "优先级甲"}).get_json()["id"]
        # 甲有业务 -> 中
        self.assertEqual(client.get(f"/api/customers/{cid_a}").get_json()["customer"]["priority"], "中")
        # 改关联到乙
        client.put(f"/api/business/{bid}", json={"customer_id": cid_b})
        # 乙 -> 中；甲 -> 低（有信息，未被删）
        self.assertEqual(client.get(f"/api/customers/{cid_b}").get_json()["customer"]["priority"], "中")
        resp_a = client.get(f"/api/customers/{cid_a}")
        self.assertEqual(resp_a.status_code, 200)
        self.assertEqual(resp_a.get_json()["customer"]["priority"], "低")

    def test_auto_imported_customer_cleanup_on_reassociate(self):
        """导入业务时自动添加的客户，改关联后被自动删除"""
        cid_a = client.post("/api/customers", json={"company": "自动添加甲", "name": ""}).get_json()["id"]
        cid_b = client.post("/api/customers", json={"company": "保留乙", "name": "法人乙"}).get_json()["id"]
        # 标记甲为「导入业务时自动添加」
        _cn = sqlite3.connect(models.DB_PATH)
        _cn.execute("UPDATE customers SET source='auto_business_import' WHERE id=?", (cid_a,))
        _cn.commit()
        _cn.close()
        bid = client.post("/api/business", json={"customer_id": cid_a, "company_name": "自动添加甲"}).get_json()["id"]
        client.put(f"/api/business/{bid}", json={"customer_id": cid_b})
        # 甲被清理；乙保留
        self.assertEqual(client.get(f"/api/customers/{cid_a}").status_code, 404)
        self.assertEqual(client.get(f"/api/customers/{cid_b}").status_code, 200)

    def test_auto_imported_customer_cleanup_on_delete(self):
        """删除业务后，导入业务时自动添加的客户被自动删除"""
        cid_a = client.post("/api/customers", json={"company": "自动添加删除甲", "name": ""}).get_json()["id"]
        _cn = sqlite3.connect(models.DB_PATH)
        _cn.execute("UPDATE customers SET source='auto_business_import' WHERE id=?", (cid_a,))
        _cn.commit()
        _cn.close()
        bid = client.post("/api/business", json={"customer_id": cid_a, "company_name": "自动添加删除甲"}).get_json()["id"]
        client.delete(f"/api/business/{bid}")
        self.assertEqual(client.get(f"/api/customers/{cid_a}").status_code, 404)

    def test_manual_customer_not_cleaned_on_delete(self):
        """手动建的客户（非导入业务自动添加）删除业务后不被删除，即使信息为空"""
        cid_a = client.post("/api/customers", json={"company": "手动空壳甲", "name": ""}).get_json()["id"]
        bid = client.post("/api/business", json={"customer_id": cid_a, "company_name": "手动空壳甲"}).get_json()["id"]
        client.delete(f"/api/business/{bid}")
        self.assertEqual(client.get(f"/api/customers/{cid_a}").status_code, 200)


class NearbyApiTests(unittest.TestCase):
    def test_nearby_api(self):
        # 在“我的位置”附近放一个，远处放一个
        client.post("/api/customers", json={
            "name": "附近客户", "latitude": 31.2040, "longitude": 121.6045
        })
        client.post("/api/customers", json={
            "name": "远方客户", "latitude": 20.0, "longitude": 110.0
        })
        r = client.get("/api/nearby?lat=31.2036&lon=121.6040")
        self.assertEqual(r.status_code, 200)
        names = [c["name"] for c in r.get_json()]
        # 半径筛选已移除：返回全部含坐标客户（按距离排序），远近都在
        self.assertIn("附近客户", names)
        self.assertIn("远方客户", names)


class SettingsApiTests(unittest.TestCase):
    def test_settings_put_get(self):
        r = client.put("/api/settings", json={"my_location_name": "测试位置"})
        self.assertEqual(r.status_code, 200)
        r = client.get("/api/settings")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json().get("my_location_name"), "测试位置")


class ReportTests(unittest.TestCase):
    def test_generate_and_list(self):
        r = client.post("/api/report/generate")
        self.assertEqual(r.status_code, 200)
        filename = r.get_json()["filename"]
        self.assertTrue(filename.startswith("daily_report_"))

        r = client.get("/api/reports")
        self.assertEqual(r.status_code, 200)
        filenames = [x["filename"] for x in r.get_json()]
        self.assertIn(filename, filenames)

        # 报告文件确实落到了临时目录
        self.assertTrue(os.path.exists(os.path.join(_tmp_reports, filename)))


class CsvTests(unittest.TestCase):
    def test_template_download(self):
        r = client.get("/api/customers/template")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("Content-Type", ""))

    def test_import_csv(self):
        header = "公司名称,联系人,联系方式,邮箱,地址,分类,优先级,备注"
        row = "导入测试公司,导入测试人,13900000000,a@b.com,上海市浦东新区张江路9号,核心要客,高,导入备注"
        content = (header + "\n" + row + "\n").encode("utf-8-sig")
        r = client.post(
            "/api/customers/import",
            data={"file": (io.BytesIO(content), "import.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(body["success"], 1)

    def test_business_import_csv(self):
        # 先确认模板下载接口可用
        r = client.get("/api/business/template")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers.get("Content-Type", ""))

        header = "公司名称,业务类型,业务套餐,合同编码,业务号码,合同金额,开始时间,结束时间,业务地址,备注"
        row = "业务导入专用公司BIZTEST,互联网专线,标准套餐A,HT-2026-999,13900000000,120000,2026-01-01,2026-12-31,上海市浦东新区,导入业务备注"
        content = (header + "\n" + row + "\n").encode("utf-8-sig")

        # 第一阶段：解析预览
        r = client.post(
            "/api/business/import/preview",
            data={"file": (io.BytesIO(content), "biz_import.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 200)
        prev = r.get_json()
        self.assertGreaterEqual(prev["stats"]["total"], 1)

        # 第二阶段：按预览方案确认导入（精确/模糊 -> 合并；无匹配 -> 新增客户）
        rows = []
        for item in prev["rows"]:
            if item["status"] in ("duplicate", "error"):
                continue
            if item["status"] == "fuzzy":
                action, cid = "merge", item["candidates"][0]["id"]
            elif item["status"] == "exact":
                action, cid = "merge", item["customer_id"]
            else:
                action, cid = "new", None
            rows.append({"record": item["record"], "action": action, "customer_id": cid})

        r = client.post("/api/business/import/commit", json={"rows": rows})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertGreaterEqual(body["success"], 1)


class PageRouteTests(unittest.TestCase):
    PAGES = ["/", "/customers", "/map", "/tasks", "/business",
             "/reports", "/settings", "/login", "/download"]

    def test_pages_render(self):
        for path in self.PAGES:
            with self.subTest(path=path):
                r = client.get(path)
                # / 与 /login 在已登录态下会 302 跳走（/ → /m 或 /tasks；/login → /），其余页面均 200
                if path in ("/login", "/"):
                    self.assertIn(r.status_code, (200, 302), f"{path} 返回 {r.status_code}")
                else:
                    self.assertEqual(r.status_code, 200, f"{path} 返回 {r.status_code}")

    def test_mobile_entry_renders_with_mobile_ua(self):
        # /m 对非移动端 UA 会重定向到 /，对移动端 UA 渲染移动首页
        ua = ("Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
              "AppleWebKit/605.1.15 Mobile/15E148")
        r = client.get("/m", headers={"User-Agent": ua})
        self.assertEqual(r.status_code, 200)


class AuthTests(unittest.TestCase):
    def test_register_creates_pending_and_no_autologin(self):
        c = app.app.test_client()
        r = c.post("/api/register", json={"phone": "13800000000"})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.get_json()["ok"])
        self.assertTrue(r.get_json()["pending"])
        # 注册后不应自动登录：未登录态访问受保护接口应 401
        me = c.get("/api/me")
        self.assertEqual(me.status_code, 401)

    def test_pending_user_cannot_login(self):
        c = app.app.test_client()
        c.post("/api/register", json={"phone": "13700000000"})
        r = c.post("/api/login", json={"username": "13700000000", "password": "123456"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json().get("code"), "pending")

    def test_register_duplicate_phone(self):
        c = app.app.test_client()
        c.post("/api/register", json={"phone": "13900000000"})
        r2 = c.post("/api/register", json={"phone": "13900000000"})
        self.assertEqual(r2.status_code, 409)

    def test_register_invalid_phone(self):
        c = app.app.test_client()
        r = c.post("/api/register", json={"phone": "123"})
        self.assertEqual(r.status_code, 400)

    def test_change_password_requires_current(self):
        r = client.post("/api/change-password", json={"old_password": "wrong", "new_password": "654321"})
        self.assertEqual(r.status_code, 400)
        # 恢复管理员密码，保持后续用例一致
        client.post("/api/change-password", json={"old_password": "123456", "new_password": "123456"})


class AdminApprovalTests(unittest.TestCase):
    def _admin_login(self, c):
        return c.post("/api/login", json={"username": "18607184641", "password": "123456"})

    def test_non_admin_cannot_list_pending(self):
        # 注册一个新用户（待审核），其登录应被拒，更不应能查看审核列表
        c = app.app.test_client()
        c.post("/api/register", json={"phone": "13611112222"})
        # 未审核用户拿不到登录态；直接用未登录会话访问应 401
        r = c.get("/api/admin/pending")
        self.assertIn(r.status_code, (401, 403))

    def test_admin_approve_and_reject_flow(self):
        admin = app.app.test_client()
        self._admin_login(admin)

        # 注册两个待审核用户
        u1 = app.app.test_client()
        r1 = u1.post("/api/register", json={"phone": "13522223333"})
        self.assertEqual(r1.status_code, 201)
        u2 = app.app.test_client()
        r2 = u2.post("/api/register", json={"phone": "13544445555"})
        self.assertEqual(r2.status_code, 201)

        # 管理员看到 2 个待审核
        pend = admin.get("/api/admin/pending").get_json()["pending"]
        phones = {p["username"] for p in pend}
        self.assertEqual(phones, {"13522223333", "13544445555"})

        # 通过其中一个
        uid1 = next(p["id"] for p in pend if p["username"] == "13522223333")
        ap = admin.post("/api/admin/approve", json={"user_id": uid1})
        self.assertEqual(ap.status_code, 200)
        self.assertTrue(ap.get_json()["ok"])

        # 被通过的账号现在可以登录
        login_ok = u1.post("/api/login", json={"username": "13522223333", "password": "123456"})
        self.assertEqual(login_ok.status_code, 200)

        # 通过后，待审列表只剩另一个
        pend_mid = admin.get("/api/admin/pending").get_json()["pending"]
        self.assertEqual({p["username"] for p in pend_mid}, {"13544445555"})

        # 拒绝另一个（删除）
        uid2 = next(p["id"] for p in pend if p["username"] == "13544445555")
        rj = admin.post("/api/admin/reject", json={"user_id": uid2})
        self.assertEqual(rj.status_code, 200)
        self.assertTrue(rj.get_json()["ok"])

        # 拒绝后待审列表为空
        pend2 = admin.get("/api/admin/pending").get_json()["pending"]
        self.assertEqual({p["username"] for p in pend2}, set())

        # 被拒绝的账号已不存在，登录应 401
        login_rej = u2.post("/api/login", json={"username": "13544445555", "password": "123456"})
        self.assertEqual(login_rej.status_code, 401)

    def test_approve_non_pending_is_rejected(self):
        admin = app.app.test_client()
        self._admin_login(admin)
        # 管理员自身已是 active，重复审核应被拒
        me = admin.get("/api/me").get_json()["user"]
        r = admin.post("/api/admin/approve", json={"user_id": me["id"]})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
数据库模型与初始化
- customers: 客户信息表
- tasks: 客户事项跟进表
- settings: 用户设置表（我的位置等）
"""
import sqlite3
import os
from datetime import datetime

# 数据目录：默认放在项目内 data/（本地运行）；容器化时通过 DATA_DIR 指向持久卷。
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
DB_PATH = os.path.join(DATA_DIR, "customers.db")

# 确保数据目录存在（云端容器首次部署时数据目录可能不存在）
os.makedirs(DATA_DIR, exist_ok=True)


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    cur = conn.cursor()

    # 客户表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,                  -- 客户名称
            company TEXT,                        -- 公司
            phone TEXT,                          -- 电话
            email TEXT,                          -- 邮箱
            address TEXT,                        -- 地址（文本）
            latitude REAL,                       -- 纬度
            longitude REAL,                      -- 经度
            category TEXT DEFAULT '普通客户',     -- 客户分类
            priority TEXT DEFAULT '中',           -- 优先级：高/中/低
            notes TEXT,                          -- 备注
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 事项跟进表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            title TEXT NOT NULL,                 -- 事项标题
            description TEXT,                    -- 详细描述
            status TEXT DEFAULT '待处理',         -- 待处理/进行中/已完成/已搁置
            priority TEXT DEFAULT '中',           -- 优先级
            progress INTEGER DEFAULT 0,          -- 进度 0-100
            due_date TEXT,                       -- 截止日期
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
        )
    """)

    # 设置表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # 业务表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,                       -- 关联客户
            company_name TEXT,                         -- 公司名称（冗余存储便于展示）
            business_address TEXT,                     -- 业务地址
            business_number TEXT,                      -- 业务号码
            contract_code TEXT,                        -- 合同编码
            business_type TEXT,                        -- 业务类型
            contract_amount REAL,                      -- 合同金额
            start_date TEXT,                           -- 开始时间
            end_date TEXT,                             -- 结束时间
            notes TEXT,                                -- 备注
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
        )
    """)

    # 插入默认设置
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("my_location_name", "上海市浦东新区张江高科技园区"))
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("my_latitude", "31.2036"))
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("my_longitude", "121.6040"))
    cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                ("default_radius_km", "10"))

    # 兼容已有数据：旧分类映射为新分类（核心要客 / TOP20 / 空）
    cur.execute("UPDATE customers SET category='核心要客' WHERE category='VIP客户'")
    cur.execute("UPDATE customers SET category='TOP20' WHERE category='重要客户'")
    cur.execute("UPDATE customers SET category='' WHERE category='普通客户'")

    conn.commit()
    conn.close()
    print(f"[OK] 数据库初始化完成: {DB_PATH}")


def seed_sample_data():
    """填充示例客户数据"""
    conn = get_db()
    cur = conn.cursor()

    # 检查是否已有数据
    count = cur.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    if count > 0:
        print(f"[SKIP] 数据库已有 {count} 条客户数据，跳过填充")
        conn.close()
        return

    # 示例客户数据（上海张江附近）
    sample_customers = [
        {
            "name": "张伟", "company": "芯创科技有限公司", "phone": "138-0013-8000",
            "email": "zhangwei@xin.com", "address": "上海市浦东新区张江路1399号",
            "latitude": 31.2040, "longitude": 121.5980,
            "category": "核心要客", "priority": "高",
            "notes": "年度合同续签客户，重点关注"
        },
        {
            "name": "李娜", "company": "云图数据科技", "phone": "139-0013-9000",
            "email": "lina@yuntu.com", "address": "上海市浦东新区博云路2号",
            "latitude": 31.1880, "longitude": 121.6150,
            "category": "TOP20", "priority": "高",
            "notes": "新项目洽谈中"
        },
        {
            "name": "王强", "company": "智联安防", "phone": "137-0013-7000",
            "email": "wangqiang@zlaf.com", "address": "上海市浦东新区金科路2889号",
            "latitude": 31.2150, "longitude": 121.6080,
            "category": "", "priority": "中",
            "notes": "设备采购需求"
        },
        {
            "name": "陈芳", "company": "绿能环保科技", "phone": "136-0013-6000",
            "email": "chenfang@lvneng.com", "address": "上海市浦东新区蔡伦路1690号",
            "latitude": 31.1920, "longitude": 121.6220,
            "category": "TOP20", "priority": "高",
            "notes": "季度回访客户"
        },
        {
            "name": "刘洋", "company": "未来医疗装备", "phone": "135-0013-5000",
            "email": "liuyang@weilai.com", "address": "上海市浦东新区哈雷路998号",
            "latitude": 31.2010, "longitude": 121.6300,
            "category": "核心要客", "priority": "高",
            "notes": "大型采购意向，需重点跟进"
        },
        {
            "name": "赵敏", "company": "蓝海信息技术", "phone": "134-0013-4000",
            "email": "zhaomin@lanhai.com", "address": "上海市浦东新区居里路100号",
            "latitude": 31.1860, "longitude": 121.6350,
            "category": "", "priority": "低",
            "notes": "技术支持需求"
        },
        {
            "name": "孙磊", "company": "宏达制造", "phone": "133-0013-3000",
            "email": "sunlei@hongda.com", "address": "上海市浦东新区龙东大道3000号",
            "latitude": 31.2280, "longitude": 121.5900,
            "category": "TOP20", "priority": "中",
            "notes": "工厂自动化改造项目"
        },
    ]

    for c in sample_customers:
        cur.execute("""
            INSERT INTO customers (name, company, phone, email, address, latitude, longitude, category, priority, notes)
            VALUES (:name, :company, :phone, :email, :address, :latitude, :longitude, :category, :priority, :notes)
        """, c)
        customer_id = cur.lastrowid

        # 为每个客户添加示例事项
        sample_tasks = generate_sample_tasks(c["name"], c["priority"])
        for t in sample_tasks:
            t["customer_id"] = customer_id
            cur.execute("""
                INSERT INTO tasks (customer_id, title, description, status, priority, progress, due_date)
                VALUES (:customer_id, :title, :description, :status, :priority, :progress, :due_date)
            """, t)

    conn.commit()
    conn.close()
    print(f"[OK] 已填充 {len(sample_customers)} 个示例客户及其事项")


def generate_sample_tasks(customer_name, priority):
    """为示例客户生成事项"""
    today = datetime.now().strftime("%Y-%m-%d")
    from datetime import timedelta
    soon = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    later = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
    overdue = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

    return [
        {
            "title": f"与{customer_name}的合同续签谈判",
            "description": "准备续签方案，确认价格条款",
            "status": "进行中",
            "priority": priority,
            "progress": 60,
            "due_date": soon
        },
        {
            "title": f"{customer_name}项目需求确认",
            "description": "收集客户需求文档，整理需求清单",
            "status": "待处理",
            "priority": "中",
            "progress": 0,
            "due_date": later
        },
        {
            "title": f"{customer_name}季度回访",
            "description": "电话回访，了解使用情况",
            "status": "已完成",
            "priority": "低",
            "progress": 100,
            "due_date": overdue
        },
    ]


if __name__ == "__main__":
    init_db()
    seed_sample_data()

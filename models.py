"""
数据库模型与初始化
- customers: 客户信息表
- tasks: 客户事项跟进表
- settings: 用户设置表（我的位置等）
"""
import sqlite3
import os
import re
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

# pymysql 为 MySQL 持久化可选依赖（FC requirements.txt 已含；本地 SQLite 模式不依赖）
try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:  # pragma: no cover
    pymysql = None

# 统一使用 pbkdf2:sha256：兼容性最好（阿里云 FC 的 Python3.10 运行时
# 底层 OpenSSL 不支持 werkzeug 默认的 scrypt，会导致 check_password_hash 抛
# "unsupported hash type scrypt" 而 500）。所有生成/校验都走此常量。
PWD_METHOD = "pbkdf2:sha256"


def make_password_hash(pwd):
    return generate_password_hash(pwd, method=PWD_METHOD)

DB_PATH = os.environ.get("CUSTOMER_DB_PATH") or os.path.join(os.path.dirname(__file__), "data", "customers.db")

# 确保数据目录存在（云端容器首次部署时 data/ 可能不存在）
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


# ============================================================
# MySQL 持久化适配层（可选）
# ------------------------------------------------------------
# 设置环境变量 MYSQL_HOST 即启用 MySQL；否则回退 SQLite（本地开发）。
# 应用层(app.py)的 SQL 大量使用 SQLite 语法(? 占位符、datetime('now','localtime')、
# ON CONFLICT...excluded、INSERT OR REPLACE/IGNORE、PRAGMA)，这里在执行前统一翻译为
# MySQL 等价写法，保持业务代码零改动。行以 dict 形式返回(row["col"] / dict(row) 兼容)。
# ============================================================
USE_MYSQL = bool(os.environ.get("MYSQL_HOST")) and pymysql is not None


def _mysql_cfg():
    return dict(
        host=os.environ.get("MYSQL_HOST"),
        port=int(os.environ.get("MYSQL_PORT", 3306)),
        user=os.environ.get("MYSQL_USER"),
        password=os.environ.get("MYSQL_PASSWORD"),
        database=os.environ.get("MYSQL_DB"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        # 统一会话时区为 +08:00，使 NOW() 与下方 _local_now() 字面量一致（中国时区）
        init_command="SET time_zone='+08:00'",
    )


def _local_now():
    """对齐原 SQLite datetime('now','localtime') 的"本地时间"语义（UTC+8）。

    应用实际运行于中国时区；用 utcnow+8 保证与 MySQL NOW()(+08:00) 一致，
    不受容器系统时区(可能为 UTC)影响。
    """
    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def _is_pragma(sql):
    return bool(re.match(r"^\s*PRAGMA\b", sql, re.IGNORECASE))


def _translate(sql):
    """把 SQLite 风格 SQL 翻译为 MySQL 等价写法。"""
    s = sql
    # 保留字列名加反引号（year_month / key / count 是 MySQL 保留字，裸用会报 1064）。
    # 仅匹配小写 key/COUNT，避免误伤 ON DUPLICATE KEY UPDATE 中的大写 KEY 与 COUNT() 聚合。
    # 负向前瞻 (?!\s*\() 排除 count( 这类函数调用，避免把 COUNT(*) 也加上反引号。
    # 负向前瞻/后顾保证不会重复包裹已存在的反引号（避免 ``key``）。
    s = re.sub(r"(?<!`)\b(year_month|key|count)\b(?!`)(?!\s*\()", r"`\1`", s)
    # datetime('now','localtime') -> 当前 +08:00 时间字面量（单引号）
    s = re.sub(r"datetime\('now',\s*'localtime'\)", "'" + _local_now() + "'", s)
    # INSERT OR IGNORE / INSERT OR REPLACE
    s = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\b", "INSERT IGNORE", s, flags=re.IGNORECASE)
    s = re.sub(r"^\s*INSERT\s+OR\s+REPLACE\b", "REPLACE", s, flags=re.IGNORECASE)
    # ON CONFLICT(cols) DO UPDATE SET ... -> ON DUPLICATE KEY UPDATE ...
    s = re.sub(r"ON\s+CONFLICT\s*\([^)]*\)\s+DO\s+UPDATE\s+SET",
               "ON DUPLICATE KEY UPDATE", s, flags=re.IGNORECASE)
    # excluded.col -> VALUES(col)
    s = re.sub(r"excluded\.(\w+)", r"VALUES(\1)", s)
    # ? 占位符 -> %s
    s = s.replace("?", "%s")
    return s


class _MySQLCursor:
    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        return self._raw.execute(_translate(sql), params)

    def executemany(self, sql, seq):
        return self._raw.executemany(_translate(sql), seq)

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    @property
    def rowcount(self):
        return self._raw.rowcount

    def close(self):
        return self._raw.close()


class _NullCursor:
    """PRAGMA 等无操作语句的占位游标。"""

    def execute(self, *a, **k):
        return self

    def executemany(self, *a, **k):
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    lastrowid = 0
    rowcount = 0


class _MySQLConnection:
    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _MySQLCursor(self._raw.cursor())

    def execute(self, sql, params=None):
        if _is_pragma(sql):
            return _NullCursor()
        cur = self._raw.cursor()
        cur.execute(_translate(sql), params)
        return _MySQLCursor(cur)

    def executemany(self, sql, seq):
        if _is_pragma(sql):
            return _NullCursor()
        cur = self._raw.cursor()
        cur.executemany(_translate(sql), seq)
        return _MySQLCursor(cur)

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()


# 各表的时间戳列（用于 MySQL BEFORE INSERT/UPDATE 触发器自动填充；
# SQLite 走列 DEFAULT，MySQL 用触发器等价实现，避免缺失列变 NULL）。
_TS_TRIGGERS = {
    "customers": ("created_at", "updated_at"),
    "businesses": ("created_at", "updated_at"),
    "tasks": ("created_at", "updated_at"),
    "subtasks": ("created_at", "updated_at"),
    "users": ("created_at",),
    "password_resets": ("created_at",),
    "checkins": ("updated_at",),
}


def get_db():
    """获取数据库连接（MySQL 或 SQLite，取决于 USE_MYSQL）"""
    if USE_MYSQL:
        try:
            raw = pymysql.connect(**_mysql_cfg())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"MySQL 连接失败: {e}")
        return _MySQLConnection(raw)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL 模式 + 写忙等待：避免多请求并发（waitress 多线程）下出现
    # "database is locked"，并让写冲突时等待而非直接报错。
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def normalize_company(name):
    """
    客户去重用的公司名归一化：
    - 去首尾空白、转小写
    - 全角括号 （）【】 转半角 ()[]
    - 去除所有内部空白（含全/半角空格、制表符）
    目的：让 "一彬丰田合成（武汉）汽车零部件有限公司" 与
          "一彬丰田合成(武汉)汽车零部件有限公司" 被判定为同一客户。
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("【", "[").replace("】", "]")
    s = re.sub(r"\s+", "", s)
    return s


def company_exists(conn, company, exclude_id=None, user_id=None):
    """
    判断归一化后的公司名是否已存在于 customers 表。
    exclude_id 用于编辑场景（排除自身）。
    user_id 用于多用户隔离：仅在该用户名下查重（None 表示不限）。
    返回已存在客户的 id，不存在返回 False。
    """
    norm = normalize_company(company)
    if not norm:
        return False
    rows = conn.execute("SELECT id, company, user_id FROM customers").fetchall()
    for r in rows:
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if user_id is not None and r["user_id"] != user_id:
            continue
        if normalize_company(r["company"]) == norm:
            return r["id"]
    return False


def _ensure_mysql_triggers(cur):
    """为各表创建 created_at/updated_at 自动填充触发器（幂等：先删后建）。"""
    for tbl, cols in _TS_TRIGGERS.items():
        bi, bu = f"trg_{tbl}_bi", f"trg_{tbl}_bu"
        cur.execute(f"DROP TRIGGER IF EXISTS `{bi}`")
        cur.execute(f"DROP TRIGGER IF EXISTS `{bu}`")
        set_bi = "; ".join(
            f"IF NEW.`{c}` IS NULL OR NEW.`{c}`='' THEN SET NEW.`{c}`=NOW(); END IF"
            for c in cols
        )
        cur.execute(
            f"CREATE TRIGGER `{bi}` BEFORE INSERT ON `{tbl}` "
            f"FOR EACH ROW BEGIN {set_bi}; END"
        )
        if "updated_at" in cols:
            cur.execute(
                f"CREATE TRIGGER `{bu}` BEFORE UPDATE ON `{tbl}` "
                f"FOR EACH ROW BEGIN "
                f"IF NEW.`updated_at` IS NULL OR NEW.`updated_at`='' "
                f"THEN SET NEW.`updated_at`=NOW(); END IF; END"
            )


def _init_db_mysql():
    """MySQL 模式下的幂等初始化（不跑 SQLite DDL）。

    仅做必要的"数据健康"保障：时间戳触发器、scrypt 密码哈希重写、
    管理员账号与孤儿行归属。表结构与存量数据由迁移脚本负责。
    """
    raw = pymysql.connect(**_mysql_cfg())
    try:
        cur = raw.cursor()
        # 触发器创建失败(如账号无 TRIGGER 权限)不应阻断关键修复
        try:
            _ensure_mysql_triggers(cur)
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] MySQL 触发器创建失败(仅影响新记录时间戳自动填充): {e}")

        # FC Py3.10 底层 OpenSSL 不支持 scrypt，存量 scrypt 哈希会导致登录 500。
        # 统一重写为 pbkdf2:sha256（默认密码 123456，与系统现状一致）。
        ph = make_password_hash("123456")
        cur.execute(
            "UPDATE users SET password_hash=%s "
            "WHERE password_hash LIKE %s OR password_hash IS NULL OR password_hash=''",
            (ph, "scrypt%"),
        )
        # 管理员账号保障（幂等）
        cur.execute(
            "UPDATE users SET is_admin=1, status='active', dingtalk_user_id=%s "
            "WHERE username=%s",
            ("03683725397487", "18607184641"),
        )
        # 孤儿行归属管理员（幂等）
        cur.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id LIMIT 1")
        owner = cur.fetchone()
        if owner:
            oid = owner["id"]
            for t in ("customers", "tasks", "businesses"):
                cur.execute(
                    f"UPDATE `{t}` SET user_id=%s WHERE user_id IS NULL OR user_id=0", (oid,)
                )
            cur.execute(
                "UPDATE settings SET user_id=%s WHERE user_id IS NULL OR user_id=0", (oid,)
            )
        raw.commit()
        print("[OK] MySQL 初始化完成")
    finally:
        raw.close()


def init_db():
    """初始化数据库表结构（MySQL 或 SQLite）"""
    if USE_MYSQL:
        _init_db_mysql()
        return
    conn = get_db()
    cur = conn.cursor()

    # 客户表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,                  -- 法人（法定代表人）
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

    # 兼容已有数据库：新增「联系人」列（与「法人」区分，可为空）
    try:
        cur.execute("ALTER TABLE customers ADD COLUMN contact TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在则忽略

    # 事项跟进表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            title TEXT NOT NULL,                 -- 事项标题
            description TEXT,                    -- 详细描述
            status TEXT DEFAULT '进行中',         -- 进行中/已完结/已归档
            priority TEXT DEFAULT '重要不紧急',   -- 优先级：重要且紧急/重要不紧急/紧急不重要/不重要不紧急（前端已不再使用，保留列仅兼容旧数据）
            progress INTEGER DEFAULT 0,          -- 进度 0-100（前端已不再使用，保留列仅兼容旧数据）
            pinned INTEGER DEFAULT 0,            -- 置顶：1=置顶 0=普通
            due_date TEXT,                       -- 截止日期
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE
        )
    """)

    # 子待办表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subtasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            done INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
        )
    """)

    # 设置表（多用户：主键改为 (key, user_id)）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 0,
            value TEXT,
            PRIMARY KEY (key, user_id)
        )
    """)

    # 用户表（多用户架构：方案 B 独立账号 + 数据隔离 + 手机号注册）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,       -- 手机号
            password_hash TEXT,
            display_name TEXT,
            is_admin INTEGER DEFAULT 0,          -- 1 = 管理员账号
            status TEXT DEFAULT 'active',        -- active=已启用 / pending=待管理员审核
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 迁移：users 加 phone 列（username=登录名；phone=手机号，二者独立）
    try:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 回填：历史数据中 username 即手机号，迁移到 phone；新注册 username/phone 各自独立
    try:
        cur.execute("UPDATE users SET phone = username WHERE phone IS NULL OR phone = ''")
    except Exception:
        pass

    # 密码重置申请表（忘记密码 → 待管理员审核）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            new_password_hash TEXT NOT NULL,
            status TEXT DEFAULT 'pending',        -- pending=待审核 / done=已处理
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    """)

    # 业务表（2.6.1 起合并 businesses + ledgers 为单表 businesses，超集字段池）
    cur.execute("""
        CREATE TABLE IF NOT EXISTS businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER,                       -- 关联客户
            user_id INTEGER,                           -- 归属用户（数据隔离）
            company_name TEXT,                         -- 公司名称（冗余存储便于展示）
            business_type TEXT,                        -- 业务类型：互联网专线/电路/算网项目/U+产品/数智惠企/冰激凌/魔方卡/副卡/宽带/固话
            business_level TEXT,                       -- 业务层级（原台账 package_name「层级」）
            number TEXT,                               -- 号码（合同类 business_number / 台账 number 统一）
            contract_code TEXT,                        -- 合同编码
            contract_amount REAL,                      -- 合同金额
            start_date TEXT,                           -- 开始时间
            end_date TEXT,                             -- 结束时间
            business_address TEXT,                     -- 业务地址
            date TEXT,                                 -- 办理日期（原台账 date）
            user_name TEXT,                            -- 使用人（原台账 user_name）
            parent_id INTEGER,                         -- 关联主卡（FK→businesses.id；原 parent_number 串号升级，选 B 方案）
            business_package TEXT,                     -- 业务套餐（兼容旧合同数据，新表单不再渲染）
            notes TEXT,                                -- 备注
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers (id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES businesses (id) ON DELETE SET NULL
        )
    """)

    # 兼容已有数据：旧分类映射为新分类（核心要客 / TOP20）
    cur.execute("UPDATE customers SET category='核心要客' WHERE category='VIP客户'")
    cur.execute("UPDATE customers SET category='TOP20' WHERE category='重要客户'")
    # '普通客户' 现为正式分类（见上方列 DEFAULT），不再清空为空。

    # 迁移：添加 business_package 列
    try:
        cur.execute("ALTER TABLE businesses ADD COLUMN business_package TEXT")
    except Exception:
        pass  # 列已存在

    # 迁移：为隔离加 user_id 列（幂等）
    for tbl in ("customers", "tasks", "businesses"):
        try:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass  # 列已存在

    # 迁移：tasks 加 pinned 列（幂等）
    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN pinned INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在

    # 迁移：事项状态枚举重构（待处理+进行中→进行中；已完成→已完结；已搁置→已归档）
    cur.execute("UPDATE tasks SET status='进行中' WHERE status='待处理'")
    cur.execute("UPDATE tasks SET status='已完结' WHERE status='已完成'")
    cur.execute("UPDATE tasks SET status='已归档' WHERE status='已搁置'")
    # 迁移：已挂起 → 已归档（状态重命名）
    cur.execute("UPDATE tasks SET status='已归档' WHERE status='已挂起'")

    # 迁移：subtasks 加 order_index 列（幂等，用于子待办排序）
    try:
        cur.execute("ALTER TABLE subtasks ADD COLUMN order_index INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # 列已存在则忽略

    # ===== 2.6.1 合并迁移：旧 businesses / ledgers → 单表 businesses =====
    # 判定依据：新 businesses 含 business_level 列；旧表没有 → 需要迁移（幂等）。
    if not _column_exists(cur, "businesses", "business_level"):
        # 旧表改名兜底（幂等：若 _bak 已存在先删，避免 ALTER RENAME 报已存在）
        for t in ("businesses", "ledgers"):
            bak = t + "_bak"
            if _table_exists(cur, bak):
                cur.execute("DROP TABLE " + bak)
            if _table_exists(cur, t):
                cur.execute("ALTER TABLE " + t + " RENAME TO " + bak)
        # 重建新结构 businesses
        cur.execute("""CREATE TABLE businesses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER, user_id INTEGER, company_name TEXT, business_type TEXT,
            business_level TEXT, number TEXT, contract_code TEXT, contract_amount REAL,
            start_date TEXT, end_date TEXT, business_address TEXT, date TEXT, user_name TEXT,
            parent_id INTEGER, business_package TEXT, notes TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_id) REFERENCES businesses(id) ON DELETE SET NULL
        )""")
        # 复制旧 businesses（合同类）
        for r in cur.execute("SELECT * FROM businesses_bak").fetchall():
            r = dict(r)
            cur.execute("""INSERT INTO businesses
                (customer_id,user_id,company_name,business_type,number,contract_code,contract_amount,
                 start_date,end_date,business_address,business_package,notes,created_at,updated_at)
                VALUES (:customer_id,:user_id,:company_name,:business_type,:business_number,:contract_code,
                        :contract_amount,:start_date,:end_date,:business_address,:business_package,:notes,:created_at,:updated_at)""", r)
        # 复制旧 ledgers（台账类）→ 业务，并建立 旧id→新id、主卡 number→id 映射
        old2new = {}
        main_nums = {}
        for r in cur.execute("SELECT * FROM ledgers_bak").fetchall():
            r = dict(r)
            cur.execute("""INSERT INTO businesses
                (customer_id,user_id,company_name,business_type,business_level,number,date,user_name,created_at,updated_at)
                VALUES (:customer_id,:user_id,:company,:package_type,:package_name,:number,:date,:user_name,:created_at,:updated_at)""", r)
            nid = cur.lastrowid
            old2new[r["id"]] = nid
            if r["package_type"] in ("数智惠企", "冰激凌") and r["number"]:
                main_nums[r["number"]] = nid
        # parent_number（串号）→ parent_id（FK）解析：子卡关联主卡
        for r in cur.execute("SELECT id, parent_number FROM ledgers_bak WHERE parent_number IS NOT NULL AND parent_number != ''").fetchall():
            nid = old2new.get(r["id"])
            pid = main_nums.get(r["parent_number"])
            if nid and pid:
                cur.execute("UPDATE businesses SET parent_id=? WHERE id=?", (pid, nid))
        # 类型重命名：融合 → 宽带（原「固话」保持不变）
        cur.execute("UPDATE businesses SET business_type='宽带' WHERE business_type='融合'")
        # 彻底移除「移网」类型（数据已确认为 0 条，此句幂等兜底层）
        cur.execute("DELETE FROM businesses WHERE business_type='移网'")
        conn.commit()
        print("[OK] 2.6.1 合并迁移完成：businesses/ledgers → 单表 businesses")

    # 迁移：customers 加 source 列（标记客户来源，如「导入业务时自动添加」）
    try:
        cur.execute("ALTER TABLE customers ADD COLUMN source TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    # 回填：历史的「导入业务时自动添加的」空壳客户（只有公司名，其余信息全空）标记为 auto_business_import
    # 幂等：source 已设值的不再命中
    cur.execute(
        "UPDATE customers SET source='auto_business_import' "
        "WHERE source IS NULL "
        "AND COALESCE(name,'')='' AND COALESCE(contact,'')='' "
        "AND COALESCE(phone,'')='' AND COALESCE(email,'')='' "
        "AND COALESCE(address,'')='' AND COALESCE(notes,'')=''"
    )

    # 迁移：settings 表多用户化（旧结构无 user_id 且 PK 仅为 key）
    if not _column_exists(cur, "settings", "user_id"):
        cur.execute("""CREATE TABLE settings_new (
            key TEXT NOT NULL, user_id INTEGER NOT NULL DEFAULT 0, value TEXT,
            PRIMARY KEY (key, user_id))""")
        cur.execute("INSERT INTO settings_new (key, user_id, value) SELECT key, 0, value FROM settings")
        cur.execute("DROP TABLE settings")
        cur.execute("ALTER TABLE settings_new RENAME TO settings")

    # 迁移：users 表清理旧登录列、改用 is_admin（幂等）
    if _column_exists(cur, "users", "dingtalk_userid") or not _column_exists(cur, "users", "is_admin"):
        cur.execute("""CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            display_name TEXT,
            is_admin INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""")
        cur.execute("""INSERT INTO users_new (id, username, password_hash, display_name, is_admin, status, created_at)
                       SELECT id, username, password_hash, display_name,
                              CASE WHEN COALESCE(is_current_user,0)=1 OR username='admin' THEN 1 ELSE 0 END,
                              'active', created_at FROM users""")
        cur.execute("DROP TABLE users")
        cur.execute("ALTER TABLE users_new RENAME TO users")

    # 迁移：为已有 users 表补充 status 列（幂等；真实库已建表但无此列）
    if not _column_exists(cur, "users", "status"):
        cur.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'active'")

    # 迁移：补充钉钉 userId 绑定列（免登用；幂等）
    if not _column_exists(cur, "users", "dingtalk_user_id"):
        cur.execute("ALTER TABLE users ADD COLUMN dingtalk_user_id TEXT")

    # 种子用户 + 默认设置（首次建库时）
    _seed_users(cur)

    # 迁移：把历史 'admin' 账号改为管理员手机号（幂等，已改则不再命中）
    cur.execute(
        "UPDATE users SET username=?, password_hash=?, display_name=?, is_admin=1 WHERE username='admin'",
        ("18607184641", make_password_hash("123456"), "18607184641"),
    )
    cur.execute("UPDATE users SET is_admin=1 WHERE username='18607184641' AND COALESCE(is_admin,0)=0")

    # 现有数据归属管理员账号：把所有 user_id 为空的行指向管理员
    cur_user = cur.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
    owner_id = cur_user[0] if cur_user else cur.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
    for tbl in ("customers", "tasks", "businesses"):
        cur.execute(f"UPDATE {tbl} SET user_id=? WHERE user_id IS NULL OR user_id=0", (owner_id,))
    # settings：旧数据(user_id=0) 归管理员；若管理员无任何设置则补默认
    cur.execute("UPDATE settings SET user_id=? WHERE user_id IS NULL OR user_id=0", (owner_id,))
    if cur.execute("SELECT COUNT(*) FROM settings WHERE user_id=?", (owner_id,)).fetchone()[0] == 0:
        _seed_user_settings(cur, owner_id)

    # 打卡表
    cur.execute("""
        CREATE TABLE IF NOT EXISTS checkins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            year_month TEXT NOT NULL,   -- "YYYY-MM"
            count INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(customer_id, year_month)
        )
    """)

    # 密码哈希兼容性迁移：FC 运行时(Py3.10)底层 OpenSSL 不支持 scrypt，
    # 存量 scrypt hash 会导致登录 500。统一重写为 pbkdf2:sha256（默认密码 123456，
    # 与系统现状一致），保证所有账号在 FC 与本地均可正常登录。
    cur.execute(
        "UPDATE users SET password_hash=? WHERE password_hash IS NULL OR password_hash='' OR password_hash LIKE 'scrypt%'",
        (make_password_hash("123456"),),
    )

    # 钉钉免登：把管理员账号绑定钉钉 userId（用户本人 03683725397487）
    cur.execute(
        "UPDATE users SET dingtalk_user_id=? WHERE username='18607184641' AND (dingtalk_user_id IS NULL OR dingtalk_user_id='')",
        ("03683725397487",),
    )

    conn.commit()
    conn.close()
    print(f"[OK] 数据库初始化完成: {DB_PATH}")


def _column_exists(cur, table, column):
    """检查表中是否存在某列（兼容 SQLite pragma）"""
    rows = cur.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _table_exists(cur, table):
    """检查表是否存在"""
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name=?", (table,)
    ).fetchone()
    return row is not None


def _seed_users(cur):
    """首次建库时只创建管理员账号（手机号注册，默认密码 123456）。

    其他成员通过 /api/register 自行用手机号注册（默认密码 123456）。
    现有数据在 init_db 的迁移段统一归属到管理员账号。
    """
    if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0:
        return
    cur.execute(
        "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?,?,?,1)",
        ("18607184641", make_password_hash("123456"), "18607184641"),
    )


def _seed_user_settings(cur, user_id):
    """为指定用户写入默认设置（幂等）。"""
    defaults = (
        ("my_location_name", "上海市浦东新区张江高科技园区"),
        ("my_latitude", "31.2036"),
        ("my_longitude", "121.6040"),
        ("default_radius_km", "10"),
    )
    for k, v in defaults:
        cur.execute("INSERT OR IGNORE INTO settings (key, user_id, value) VALUES (?,?,?)", (k, user_id, v))


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

    # 示例数据归属管理员账号
    cur_user = cur.execute("SELECT id FROM users WHERE is_admin=1 ORDER BY id LIMIT 1").fetchone()
    owner_id = cur_user[0] if cur_user else None

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
            INSERT INTO customers (name, company, phone, email, address, latitude, longitude, category, priority, notes, user_id)
            VALUES (:name, :company, :phone, :email, :address, :latitude, :longitude, :category, :priority, :notes, :user_id)
        """, {**c, "user_id": owner_id})
        customer_id = cur.lastrowid

        # 为每个客户添加示例事项
        sample_tasks = generate_sample_tasks(c["name"], c["priority"])
        for t in sample_tasks:
            t["customer_id"] = customer_id
            t["user_id"] = owner_id
            cur.execute("""
                INSERT INTO tasks (customer_id, title, description, status, priority, progress, due_date, user_id)
                VALUES (:customer_id, :title, :description, :status, :priority, :progress, :due_date, :user_id)
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
            "status": "进行中",
            "priority": "中",
            "progress": 0,
            "due_date": later
        },
        {
            "title": f"{customer_name}季度回访",
            "description": "电话回访，了解使用情况",
            "status": "已完结",
            "priority": "低",
            "progress": 100,
            "due_date": overdue
        },
    ]


if __name__ == "__main__":
    init_db()
    seed_sample_data()

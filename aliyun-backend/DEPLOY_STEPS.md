# 建云实例后 · 一步到位部署清单

> 前置：阿里云账号已实名，已开通 FC / RDS(MySQL) / OSS（同地域，如 `cn-hangzhou`）。
> 本清单把你「建好实例」之后的动作固化成可执行步骤。按顺序跑，每步有验证点。

---

## 第 1 步：建 RDS MySQL Serverless 并建库

1. RDS 控制台 → 创建实例 → **Serverless** 形态，MySQL 8.0，地域 `cn-hangzhou`（与 FC/OSS 同地域）。
2. 创建管理员账号（记下：主机地址 `rm-xxx.mysql.rds.aliyuncs.com`、端口 `3306`、账号、密码）。
3. 创建数据库 `crm`（字符集 `utf8mb4`）。
4. 开启「自动暂停」（无连接 ≈ ¥0）。
5. **联调期**：临时开启「公网地址」+ 白名单 `0.0.0.0/0`；上线后收白名单为 FC 的内网网段。

**建表**（在 RDS 执行，本地用 mysql 客户端或控制台 SQL 窗口）：
```bash
# 本地若有 mysql 客户端：
mysql -h<rm-xxx>.mysql.rds.aliyuncs.com -P3306 -u<账号> -p crm < ../migration/schema_mysql.sql
```
或用 RDS 控制台的「SQL 窗口」直接粘贴 `migration/schema_mysql.sql` 内容执行。

验证点：8 张表（`customers/businesses/tasks/subtasks/users/settings/checkins/password_resets`）已建好，无报错。

---

## 第 2 步：跑数据迁移（SQLite → RDS，403 行）

在**本地** Python 3.13 venv 跑（需 `pymysql`）：

```bash
cd customer-workspace
"venv/Scripts/python.exe" -m pip install pymysql   # 若未装

MYSQL_HOST=rm-xxx.mysql.rds.aliyuncs.com \
MYSQL_USER=<账号> MYSQL_PASSWORD='<密码>' MYSQL_DB=crm \
"venv/Scripts/python.exe" migration/migrate_sqlite_to_mysql.py
```

验证点：脚本打印 `[OK] customers: 157 行` / `[OK] businesses: 59 行` 等；RDS 中 `SELECT COUNT(*) FROM customers` = 157。

> 注意：迁移是**一次性**的。重复跑会因主键冲突报错（FOREIGN_KEY_CHECKS 已关但主键重复）。
> 若要重迁，先 `TRUNCATE` 各表再跑。

---

## 第 3 步：建 FC 函数 + 部署代码

方式 A（控制台，最直观）：
1. 函数计算控制台 → 服务 → 创建服务 `crm-svc`。
2. 创建函数 → 运行环境 **Python 3.10**，函数名 `crm-backend`。
3. 代码：把 `aliyun-backend/` 整个目录（含 `requirements.txt`）打包 zip 上传；或关联代码仓库。
4. 入口：自定义运行时填 `index.handler`（本目录 `index.py`）。
5. 触发器：HTTP 触发器，认证「**免鉴权**」（鉴权由应用 JWT 负责），方法全开。
6. **环境变量**（控制台「环境变量」页填，密钥不进代码）：
   - `MYSQL_HOST` / `MYSQL_PORT`(3306) / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB`(crm)
   - `DING_APP_KEY` = `dingnurzg7xk1gmitlar`
   - `DING_APP_SECRET` = （`.internal_app_secret` 里的值）
   - `JWT_SECRET` = 自定一个长随机串（如 `openssl rand -hex 32`）
   - `TENCENT_MAP_KEY` = 你已有的腾讯地图 key
   - `OSS_ENDPOINT` / `OSS_BUCKET` / `OSS_AK` / `OSS_SK`（导出用，可后补）
   - `ALLOW_ORIGIN` = `*`

方式 B（s 工具，可复现）：
```bash
cd aliyun-backend
# 1. 准备本地 .env（不要提交！已加 .gitignore 建议）
cat > .env <<'EOF'
MYSQL_HOST=rm-xxx.mysql.rds.aliyuncs.com
MYSQL_USER=<账号>
MYSQL_PASSWORD=<密码>
DING_APP_KEY=dingnurzg7xk1gmitlar
DING_APP_SECRET=<secret>
JWT_SECRET=<openssl rand -hex 32>
TENCENT_MAP_KEY=<key>
OSS_ENDPOINT=
OSS_BUCKET=
OSS_AK=
OSS_SK=
EOF
npm install -g @serverless-devs/s
s config add    # 绑定你的阿里云账号
s deploy
```

验证点：FC 给出 HTTP 地址（如 `https://crm-backend-xxx.cn-hangzhou.fcapp.run`）。
```bash
curl https://<你的FC地址>/api/healthz
# 期望返回 {"ok":true,"db":true}
```

---

## 第 4 步：（已弃用）小程序联调说明

> 小程序方案已于 2026-08-23 弃用，前端改为钉钉 H5 微应用（GitHub Pages 部署，`docs/m.html`）。
> 原 `dingtalk-miniapp/` 目录已从仓库删除。如需恢复小程序，概述如下：
> 1. 打开小程序 `config.js`，把 `apiBase` 改成第 3 步拿到的 FC 地址。
> 2. 钉钉开发者工具导入小程序项目（appid = `dingnurzg7xk1gmitlar`）。
> 3. 真机/模拟器登录 → 验证 `/api/auth/login` 拿到 token → 客户/业务/导入导出/去重全链路跑通。

---

## 第 5 步（后置）：P4 推送 + P5 发布

- P4：把 `dingtalk_notify.py` 接入 FC（复用现有钉钉群机器人 Webhook 加签通道）。
- P5：网页端给「客户管理平台」申请**通讯录成员信息**权限 + 把 3 人加可见范围；企业内部授权发布。

---

## 常见坑

- **RDS 自动暂停后首次请求慢**：FC 冷启动 + RDS 唤醒可能 3-5s，属正常；频繁调用不会暂停。
- **跨地域连不上**：FC / RDS / OSS 必须同地域，否则内网不通、延迟高。
- **pymysql 在 FC 未安装**：`requirements.txt` 已含 `pymysql==1.1.1`，FC 会自动装；若用「Flask 框架」模式需确认依赖已装。
- **OSS 未配时导出**：后端返回 `warning + content`（前 5000 字），前端复制到剪贴板，不影响其他功能。

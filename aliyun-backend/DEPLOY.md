# 钉钉小程序后端 · 阿里云 FC 部署说明

## 前置（P0-2 已完成）
- 阿里云账号已实名，已开通：函数计算 FC、云数据库 RDS(MySQL)、对象存储 OSS（同地域，如华东1 杭州）。
- RDS 已执行 `migration/schema_mysql.sql` 建表，并用 `migrate_sqlite_to_mysql.py` 迁完数据。

## 一、建 RDS 实例（若还没建）
1. RDS 控制台 → 创建实例 → **Serverless** 形态，MySQL 8.0，与 FC/OSS **同地域**。
2. 建库 `crm`，建管理员账号。
3. 开启「自动暂停」（无人连接≈¥0）。
4. 记下内网地址/端口/账号。首次联调可临时开「公网地址」+ 设置白名单为 `0.0.0.0/0`（上线后收紧）。

## 二、建 FC 函数
1. 函数计算控制台 → 服务 → 函数 → 创建（**Python 3.10**）。
2. 运行环境选「Flask 框架」或「自定义运行时」，HTTP 触发器，认证选「免鉴权」（鉴权由本应用 JWT 负责）。
3. 代码：把本目录（`app.py/index.py/config.py/db.py/auth.py/requirements.txt`）打包上传，或关联代码仓库。
4. **环境变量**（密钥只放这里，绝不进代码）：
   - `MYSQL_HOST` `MYSQL_PORT` `MYSQL_USER` `MYSQL_PASSWORD` `MYSQL_DB`
   - `DING_APP_KEY` `DING_APP_SECRET`（即「客户管理平台」小程序的 AppKey/Secret）
   - `JWT_SECRET`（自定一个长随机串）
   - `TENCENT_MAP_KEY`（你已有的腾讯地图 key）
   - `OSS_ENDPOINT` `OSS_BUCKET` `OSS_AK` `OSS_SK`（导出文件用，未配則导出接口返回原始内容）
5. 入口：自定义运行时填 `index.handler`；Flask 框架填 `app.app`。

## 三、联调
1. 拿到 FC 的 HTTP 访问地址（如 `https://xxx.cn-hangzhou.fcapp.run`）。
2. 把它填进小程序 `config.js` 的 `apiBase`。
3. 小程序 `dd.requestAuthCode` → 调 `/api/auth/login` → 拿 token → 后续请求带 `Authorization: Bearer <token>`。

## 四、已实现路由（完整 P2 后端）
`app.py` 已实现全部核心路由：
- `GET /api/healthz` 健康检查
- `POST /api/auth/login` 钉钉免登（authCode→userId→JWT）
- `GET /api/me` 当前用户
- `GET /api/customers` / `GET /api/customers/<id>` 客户
- `GET /api/settings` / `PUT /api/settings` 设置
- `GET /api/nearby` 附近客户（geo 真实距离）
- `GET|POST /api/tasks` / `PUT|DELETE /api/tasks/<id>` 事项
- `GET|POST /api/tasks/<id>/subtasks` / `PUT /api/tasks/<id>/subtasks/<sid>` 子待办
- `GET|POST /api/business` / `GET|PUT|DELETE /api/business/<id>` 业务台账
- `POST /api/export`（csv/json→OSS 签名 URL）、`POST /api/import`（CSV 导入）、`GET /api/report`（汇总）
- admin：`GET /api/admin/users`、`PUT /api/admin/users/<id>/status`、`POST /api/admin/bind-dingtalk`

模块：`db.py`(RDS 封装)/`auth.py`(免登+JWT)/`geo.py`(地图距离)/`export.py`(导出导入报告)/`oss.py`(OSS)。
辅助模块 `dingtalk_notify.py`（P4 推送）待接入，复用现有钉钉群机器人通道。

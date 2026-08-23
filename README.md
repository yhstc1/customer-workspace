# 客户管理平台

一个完整的客户管理平台，集客户管理、地图服务、事项跟进、每日报告于一体。

## 功能特性

- 👥 **客户管理** — 客户信息（名称、公司、电话、地址、经纬度、分类、优先级、备注）
- 🗺️ **地图视图** — 基于 OpenStreetMap（免费）展示客户位置，按距离筛选附近客户
- 📝 **事项看板** — 3 状态看板（进行中/已完结/已挂起），支持子待办、置顶、截止日期
- 📊 **每日报告** — 一键生成 HTML 报告（统计概览 + 附近客户 + 待办 + 今日建议）
- ⚙️ **位置设置** — 手动填写地址自动解析经纬度，或使用浏览器 GPS 定位
- ⏰ **定时任务** — 通过 cron 每天自动生成报告

## 技术栈

- **后端**: Python 3.11 + Flask
- **数据库**: SQLite（轻量、零配置）
- **地图**: Leaflet + OpenStreetMap（免费、无需 API Key）
- **地理编码**: Nominatim（免费 OSM 服务）
- **前端**: 原生 HTML + CSS + JavaScript（无构建工具）

## 目录结构

```
customer-workspace/
├── app.py                  # Flask 主应用
├── models.py               # 数据库模型
├── geo_service.py          # 地理编码与附近客户计算
├── report_generator.py     # 每日报告生成器
├── data/
│   └── customers.db        # SQLite 数据库（自动生成）
├── reports/                # 生成的报告（HTML）
├── static/
│   ├── css/style.css       # 样式
│   └── js/app.js           # 前端工具
├── templates/              # HTML 页面模板
│   ├── customers.html      # 客户管理
│   ├── map.html            # 地图视图
│   ├── tasks.html          # 事项看板
│   ├── reports.html        # 报告列表
│   └── settings.html       # 设置
├── start.sh                # 启动脚本
└── README.md
```

## 快速开始

### 启动应用

```bash
cd /workspace/customer-workspace
python3.11 app.py
```

访问 http://localhost:5000

### 重置数据库

```bash
rm -f data/customers.db
python3.11 models.py
```

### 手动生成报告

```bash
python3.11 report_generator.py
```

报告保存在 `reports/daily_report_YYYY-MM-DD.html`

### 配置定时任务（每天早上 8:00 自动生成报告）

```bash
crontab -e
```

添加以下行：

```
0 8 * * * cd /workspace/customer-workspace && python3.11 report_generator.py >> /tmp/report_cron.log 2>&1
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/customers | 客户列表（支持 search, category 过滤） |
| POST | /api/customers | 新增客户（自动地理编码） |
| GET | /api/customers/{id} | 客户详情（含事项） |
| PUT | /api/customers/{id} | 更新客户 |
| DELETE | /api/customers/{id} | 删除客户 |
| GET | /api/tasks | 事项列表（支持 status 过滤） |
| POST | /api/tasks | 新增事项 |
| PUT | /api/tasks/{id} | 更新事项 |
| DELETE | /api/tasks/{id} | 删除事项 |
| GET | /api/nearby?lat=&lon=&radius= | 附近客户查询 |
| GET | /api/geocode?address= | 地址转经纬度 |
| GET/PUT | /api/settings | 系统设置 |
| GET | /api/dashboard | 仪表盘统计 |
| POST | /api/report/generate | 生成今日报告 |
| GET | /api/reports | 报告列表 |

## 数据模型

### customers（客户表）
- id, name, company, phone, email, address
- latitude, longitude（经纬度）
- category（VIP客户/重要客户/普通客户）
- priority（高/中/低）
- notes, created_at, updated_at

### tasks（事项表）
- id, customer_id（外键）
- title, description, status, priority
- progress（0-100）, due_date
- created_at, updated_at

### settings（设置表）
- my_location_name（位置名称）
- my_latitude, my_longitude（我的位置）
- default_radius_km（默认搜索半径）

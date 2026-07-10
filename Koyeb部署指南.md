# 客户管理系统 · Koyeb 部署指南（Docker Hub + Koyeb）

> 本文件是当前采用的部署方案。之前的 Zeabur 方案因"免费套餐必须购买服务器"已弃用，配置保留作历史参考。
> github.com 打不开不影响本方案（Koyeb 支持 Email/Google 注册；镜像走 Docker Hub，不依赖 GitHub）。

---

## 0. 架构

```
本地/CI  ──build──▶  Docker 镜像  ──push──▶  Docker Hub
                                              │
                                      Koyeb 拉镜像 ──▶ 容器运行 (gunicorn)
                                                           │
                                              数据持久化：Volume 挂载 /data
```

- **入口**：gunicorn 监听 `$PORT`（Koyeb 注入，默认 8000），绑定 `0.0.0.0`。
- **数据**：SQLite 文件在 `DATA_DIR`（容器内 `/data`），挂 Koyeb Volume 持久化。
- **配置**：通过环境变量注入。

---

## 1. 前置准备

| 需要 | 说明 | 链接 |
|---|---|---|
| Docker Hub 账号（免费） | 存放镜像 | https://hub.docker.com |
| Docker Desktop（路线 A 必需） | 本机构建/推送镜像 | https://www.docker.com/products/docker-desktop/ |
| Koyeb 账号（有免费额度） | 跑容器 | https://app.koyeb.com |
| Node（仅路线 B 备选需要） | 你已装 22.x | — |

- 本机装 Docker Desktop：Windows 家庭版需先启用 **WSL2**（安装向导会引导）。
- Koyeb 注册可用 **Email / Google**（别选 GitHub，反正 github.com 打不开）。
- 本机现无 Docker、无 Koyeb CLI——路线 A 需先装 Docker Desktop；路线 B 需装 Koyeb CLI（更轻，免 Docker）。

---

## 2. 路线 A：本地构建 + 推 Docker Hub（推荐，符合你指定的 Docker Hub 方案）

1. 装好并**启动 Docker Desktop**（系统托盘出现鲸鱼图标、状态 Running）。
2. 双击项目里的 **`docker-build-push.bat`**。
3. 按提示输入你的 Docker Hub **用户名** → 回车。
4. 自动 `docker login`（输入密码或 Access Token）→ `build` → `push`。
5. 成功后得到镜像地址：
   ```
   docker.io/<你的用户名>/customer-workspace:latest
   ```

> 若想手动执行：
> ```bash
> docker login
> docker build -t docker.io/<用户名>/customer-workspace:latest .
> docker push docker.io/<用户名>/customer-workspace:latest
> ```

---

## 3. 在 Koyeb 控制台部署（路线 A 的后续步骤）

1. 打开 https://app.koyeb.com ，登录。
2. 点 **Create App**（或 New Service）。
3. 来源选择 **Container (Docker image)**。
4. 填写：
   - **Image**：`docker.io/<你的用户名>/customer-workspace:latest`
   - **Port**：`8000`
5. 选区域：离你最近的（**Singapore** 或 **Frankfurt**，以控制台下拉列表为准）。
6. 实例类型选 **Free / Eco**（若免费额度支持）。
7. 展开 **Environment variables**，添加：
   | Key | Value |
   |---|---|
   | `PORT` | `8000` |
   | `DATA_DIR` | `/data` |
   | `FLASK_SECRET_KEY` | 一串随机字符串（务必改掉默认） |
8. 展开 **Volumes**，添加：
   - **Mount path**：`/data`（与 `DATA_DIR` 对应，确保 SQLite 重启不丢）
   - 选或新建一个 Store / Volume
9. **Health check**（建议）：Path `/api/dashboard`，Port `8000`。
10. 点 **Deploy**，等待启动；状态变 Healthy 后点生成的 URL 访问。

---

## 4. 路线 B：Koyeb CLI 本地目录云端构建（免装 Docker，备选）

如果不想装 Docker Desktop（约 1GB，且要 WSL2），用 Koyeb CLI 让云端直接构建：

1. 安装 Koyeb CLI（Windows PowerShell）：
   ```powershell
   iwr https://cli.koyeb.com/install.ps1 -useb | iex
   # 或：winget install Koyeb.koyeb
   ```
2. `koyeb login`（浏览器确认）。
3. 在项目目录执行（**参数以 `koyeb app deploy --help` 为准**）：
   ```bash
   koyeb app deploy . --name customer-workspace --docker --ports 8000:http --env PORT=8000 --env DATA_DIR=/data --region sin
   ```
   Koyeb 会在云端用本目录的 Dockerfile 构建镜像并部署——**无需本地 Docker、无需 Docker Hub、无需 GitHub**。
4. 部署后在控制台补 **Volume（/data）** 与 **FLASK_SECRET_KEY**。

---

## 5. 环境变量说明

| 变量 | 必填 | 说明 |
|---|---|---|
| `PORT` | 是 | gunicorn 监听端口，Koyeb 注入，设 `8000` |
| `DATA_DIR` | 是 | SQLite 目录，容器里设 `/data`（挂卷） |
| `FLASK_SECRET_KEY` | 强烈建议 | Session 签名密钥，改掉默认值 |
| `DINGTALK_APP_KEY` / `DINGTALK_APP_SECRET` / `APP_BASE_URL` | 可选 | 填了启用钉钉扫码登录门禁；不填则无门禁、直接可用 |

---

## 6. 钉钉登录（可选）

- **不填** `DINGTALK_*` 变量 → 线上直接能进、无登录门禁。
- **要启用** → 填三个变量，并去钉钉开放平台把回调域名加入白名单（`APP_BASE_URL` = 你的 Koyeb 域名）。

---

## 7. 数据持久化注意事项

- Koyeb 实例磁盘是**临时**的，必须挂 Volume 到 `/data` 才能持久化 SQLite。
- 若免费额度不支持 Volume，数据会随重启/重部署丢失。可用项目自带的 `/download-project`（或 `/download`）页面定期导出备份（含数据库）应急。

---

## 8. 排错

- **镜像起不来**：看 Koyeb **Logs**。常见：PORT 没设、gunicorn 未安装（requirements 已含）、`/data` 不可写。
- **访问 502 / 超时**：确认 Port 填 `8000`，且应用监听 `0.0.0.0`（Dockerfile 已配）。
- **数据丢失**：检查 Volume 是否挂载到 `/data`。
- **健康检查失败**：确认 `/api/dashboard` 返回 200（本地已验证 200）。

---

## 9. 已完成的代码改造（均已验证）

- `app.py`：建表 `init_db()` 提到模块级（gunicorn 不走 `__main__`，否则首请求 500）。
- `models.py`：`DB_PATH` 支持 `DATA_DIR` 环境变量；默认本地 `data/`，容器设 `/data`。向后兼容。
- 新增 `Dockerfile`（python:3.13-slim + gunicorn，绑定 `$PORT`，含 HEALTHCHECK）。
- 新增 `.dockerignore`（排除 `*.db` / `.workbuddy` / 缓存等）。
- 新增 `docker-build-push.bat`（路线 A 一键 build+push）。
- `requirements.txt` 含 `gunicorn`。

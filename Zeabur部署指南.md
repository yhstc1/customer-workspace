# Zeabur 部署指南

本项目已完成 Zeabur 适配。下面两种方式任选其一，**推荐方式一（GitHub）**，最稳、支持 push 后自动重新部署。

---

## 一、已为部署做的改动（无需你操作，已完成）

| 文件 | 改动 | 原因 |
|------|------|------|
| `requirements.txt` | 新增 `gunicorn` | 生产 WSGI 服务器，Zeabur 用它拉起应用 |
| `app.py` | 建表 `init_db()` 提到模块级 | gunicorn 不执行 `if __name__=="__main__"`，否则线上第一个请求就 500 |
| `models.py` | 启动时自动 `makedirs(data)` | 云端容器首次没有 `data/` 目录，SQLite 连接会失败 |
| `zbpack.json` | 指定启动命令 | 告诉 Zeabur 用 `gunicorn app:app` 启动 |
| `.gitignore` | 忽略 `*.db`、`__pycache__` 等 | 数据库不进仓库，线上用 Volume 持久化 |

启动命令：`gunicorn app:app -b 0.0.0.0:$PORT --workers 2 --timeout 120`

---

## 二、方式一：GitHub（推荐）

### 1. 推送到 GitHub
项目已初始化 git 并完成首次提交，只差关联远程仓库：

```bash
cd "C:\Users\123\Downloads\customer-workspace"
# 先到 github.com 新建一个空仓库（不要勾选 README/.gitignore），拿到地址后执行：
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

### 2. 在 Zeabur 部署
1. 打开 https://zeabur.com ，用 GitHub 登录
2. `Create Project` → 选区域（推荐 Hong Kong / Singapore）
3. `Add Service` → `Deploy from GitHub` → 授权并选中刚推送的仓库
4. Zeabur 自动识别为 Python 项目，读取 `zbpack.json`，用 gunicorn 启动，几分钟后构建完成

### 3. 生成公网域名
服务详情 → `Networking` / `Domains` → `Generate Domain`，填一个前缀，得到 `xxx.zeabur.app` 即可访问。

---

## 三、方式二：Zeabur CLI（不想用 GitHub 时）

```bash
cd "C:\Users\123\Downloads\customer-workspace"
npx zeabur@latest deploy
```
按提示登录、选/建 Project，CLI 会把当前目录打包上传部署。

---

## 四、必须配置的两项（部署后立刻做）

### 1. 数据持久化 Volume（重要，不配数据会丢）
Zeabur 容器磁盘是临时的，**重新部署/重启会清空 SQLite 数据库**。必须挂 Volume：

- 服务详情 → `Volumes` → `Add Volume`
- Mount Path 填：`/src/data`
- 保存后 Redeploy 一次

这样 `data/customers.db` 落在持久卷上，数据不再丢失。

### 2. 环境变量
服务详情 → `Variables` → 添加：

| 变量名 | 值 | 说明 |
|--------|-----|------|
| `FLASK_SECRET_KEY` | 一段随机长字符串 | session 加密密钥，务必改掉默认值 |

钉钉扫码登录（可选，不填则线上无登录门禁、直接可用）：

| 变量名 | 值 |
|--------|-----|
| `DINGTALK_APP_KEY` | 钉钉应用 AppKey |
| `DINGTALK_APP_SECRET` | 钉钉应用 AppSecret |
| `APP_BASE_URL` | `https://你的域名.zeabur.app` |

> ⚠️ 一旦填了钉钉 AppKey/AppSecret，登录门禁会启用。此时必须：
> 1. 设置 `APP_BASE_URL` 为你的 Zeabur 域名（回调地址会自动拼成 `域名/api/dingtalk/oauth/callback`）
> 2. 到钉钉开放平台「安全设置 → 重定向 URL」把该回调地址加进白名单
> 3. 否则会一直卡在扫码登录页登不进去

---

## 五、验证
- 访问 `https://你的域名.zeabur.app/` 打开仪表盘
- 访问 `/api/dashboard` 返回 JSON 即为正常

## 六、常见问题
- **502 / 启动失败**：看 Zeabur 日志。多半是依赖装失败或端口没监听 `$PORT`，本项目已用 `-b 0.0.0.0:$PORT` 处理。
- **数据莫名清空**：没挂 Volume，回到第四节第 1 步。
- **改代码后更新**：GitHub 方式直接 `git push`，Zeabur 自动重新部署。

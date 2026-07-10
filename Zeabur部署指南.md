# Zeabur 部署指南（不依赖 GitHub）

> 适用场景：**github.com 打不开 / 不想用 GitHub**。本方案用 Zeabur 官方 CLI 从本地直接打包上传部署，全程不碰 GitHub。

---

## 一、已为部署做的改动（无需你操作，已完成）

| 文件 | 改动 | 原因 |
|------|------|------|
| `requirements.txt` | 新增 `gunicorn` | 生产 WSGI 服务器，Zeabur 用它拉起应用 |
| `app.py` | 建表 `init_db()` 提到模块级 | gunicorn 不执行 `if __name__=="__main__"`，否则线上第一个请求就 500 |
| `models.py` | 启动时自动 `makedirs(data)` | 云端容器首次没有 `data/` 目录，SQLite 连接会失败 |
| `zbpack.json` | 指定启动命令 | 告诉 Zeabur 用 `gunicorn app:app` 启动 |
| `.zeaburignore` | 忽略 `*.db`、`__pycache__`、`.workbuddy` 等 | 防止把本地数据库、密钥、缓存传上线 |
| `.gitignore` | 忽略 `*.db`、`__pycache__` 等 | 数据库不进仓库 |

启动命令（Zeabur 自动读取）：`gunicorn app:app -b 0.0.0.0:$PORT --workers 2 --timeout 120`

---

## 二、准备：注册 Zeabur（用邮箱，不碰 GitHub）

1. 打开 https://zeabur.com
2. 点注册/登录，**选择「邮箱 Email」或「Google」方式**（不要选 GitHub，因为你打不开 github.com）
3. 首次创建项目需要验证账号：手机号 / 预存余额 / 信用卡，三选一完成验证

> 只要 `zeabur.com` 能打开，这一步就和 GitHub 无关，正常走。

---

## 三、主部署方式：Zeabur CLI（本地直传）

在本机项目目录执行：

```bash
cd "C:\Users\123\Downloads\customer-workspace"

# 1. 登录（会打开浏览器，到 Zeabur 网站用邮箱登录后点 Confirm）
npx zeabur@latest auth login

# 2. 部署（在当前目录执行，CLI 自动识别 Python 项目并打包上传）
npx zeabur@latest deploy
```

`deploy` 会交互式让你：
- 选择或新建一个 Project（区域推荐 Hong Kong / Singapore）
- 选择环境（默认 production）
- 自动构建并给出服务 URL

构建完成后在终端会显示访问地址。

> 前提：本机需有 Node.js（你已装 22.x，`npx` 可用）。
> CLI 登录走的是 Zeabur 自家网站，回传 token 给终端，**全程不经过 github.com**。

---

## 四、备选：网页直接传 ZIP（不想装 CLI 时）

1. 在本地把整个项目目录压成 `customer-workspace.zip`（**排除** `data/*.db`、`__pycache__`、`.workbuddy` 文件夹）
2. 在 Zeabur 项目里 `Add Service` → 选择「Upload / Deploy code」类入口上传该 zip
3. Zeabur 自动解包构建

（CLI 方式更省事，优先用第三种。）

---

## 五、部署后必须配置的两项

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
> 1. 设置 `APP_BASE_URL` 为你的 Zeabur 域名（回调地址自动拼成 `域名/api/dingtalk/oauth/callback`）
> 2. 到钉钉开放平台「安全设置 → 重定向 URL」把该回调地址加进白名单
> 3. 否则会一直卡在扫码登录页登不进去

---

## 六、生成公网域名
服务详情 → `Domains` / `Networking` → `Generate Domain`，填前缀得到 `xxx.zeabur.app` 即可访问。

## 七、验证
- 访问 `https://你的域名.zeabur.app/` 打开仪表盘
- 访问 `/api/dashboard` 返回 JSON 即为正常

## 八、常见问题
- **502 / 启动失败**：看 Zeabur 日志。多半是依赖装失败或没监听 `$PORT`，本项目已用 `-b 0.0.0.0:$PORT` 处理。
- **数据莫名清空**：没挂 Volume，回到第五节第 1 步。
- **改代码后更新**：重新在本地目录跑 `npx zeabur@latest deploy` 即可重新部署（会新建一次部署）。
- **CLI 登录没反应**：确认浏览器能打开 `zeabur.com` 并完成邮箱登录，点 Confirm 后回到终端应显示 success。
- **`Failed to create project: invalid region code`**：CLI 交互创建项目时传入了服务端不认的区域代码，是 CLI 的已知坑，与你的操作无关。绕过办法：去 zeabur.com 网页 `New Project` 选好区域（Hong Kong）创建空项目，再重新跑 `npx zeabur@latest deploy`，这次选已有项目即可，不再触发创建项目的 region 错误。

---

## 九、如果你将来能访问 github.com（可选）
也可用 GitHub 方式：把项目 `git push` 到 GitHub 仓库，Zeabur `Add Service → Deploy from GitHub` 选中仓库，支持 push 后自动重新部署。当前已 `git init` 并提交，只差 `git remote add origin` + `git push`。

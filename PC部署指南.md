# 客户管理平台 · PC 端部署指南

本指南帮助你在自己的电脑（Windows / macOS / Linux）上运行客户管理平台。

> 项目已从云端沙盒导出。所有数据保存在 `data/customers.db`（SQLite 文件），完全本地，无需联网注册。
> 地图和地址解析需要联网（使用 OpenStreetMap 免费服务）。

---

## 一、环境准备

### Windows
1. 下载安装 Python 3.11+：https://www.python.org/downloads/
   - ⚠️ 安装时务必勾选 **"Add Python to PATH"**
2. 解压本项目到任意目录，例如 `D:\customer-workspace\`

### macOS
1. 一般已自带 Python 3；若没有，用 Homebrew：`brew install python`
2. 解压项目到 `~/customer-workspace/`

### Linux
1. 一般已自带 Python 3；若没有：`sudo apt install python3 python3-pip`
2. 解压项目到 `~/customer-workspace/`

---

## 二、安装依赖

打开终端（Windows 用 PowerShell 或 CMD，进入项目目录）：

```bash
cd 你的项目路径/customer-workspace

# 安装依赖
pip install -r requirements.txt
# 如果提示 pip 不存在，用： python -m pip install -r requirements.txt
```

依赖只有两个：`flask`、`requests`（体积很小，几秒钟装完）。

---

## 三、启动应用

### 方式 A：一键脚本（最简单）

- **Windows**：双击 `启动.bat`
- **macOS / Linux**：终端执行 `./start.sh`（首次需 `chmod +x start.sh`）

### 方式 B：命令行

```bash
python app.py
# 或 macOS/Linux 上： python3 app.py
```

看到以下输出即启动成功：

```
============================================================
  客户管理平台已启动
  本地访问:    http://localhost:5000
  移动端入口:  http://localhost:5000/m
============================================================
```

---

## 四、打开使用

浏览器访问：

| 地址 | 说明 |
|------|------|
| http://localhost:5000 | 电脑端完整界面（仪表盘/客户/地图/事项/报告/设置） |
| http://localhost:5000/m | 手机端界面（鸿蒙/Android/iOS 浏览器打开，底部 Tab 导航） |

> 💡 **首次打开** 会有 7 个示例客户和示例事项，方便你熟悉功能。
> 想用真实数据：在「客户管理」里逐个删除示例，再新增自己的客户即可。
> 想彻底清空重来：删除 `data/customers.db` 文件，重新运行 `python models.py`。

---

## 五、手机如何访问（鸿蒙 6 华为手机）

手机和电脑在同一个 WiFi 下时，手机浏览器打开：
```
http://你的电脑局域网IP:5000/m
```
查电脑局域网 IP：
- Windows：`ipconfig` 看「IPv4 地址」
- Mac/Linux：`ifconfig` 或 `ip a` 看 `192.168.x.x`

> 不在同一 WiFi、或想随时随地访问，需要把应用部署到公网：
> 见 `deploy.sh`（内网穿透 / 云服务器）。

---

## 六、账号与登录

- 系统采用「手机号自助注册」登录，无需第三方凭证。
- 管理员初始账号：手机号 `18607184641` / 密码 `123456`。
- 其他成员在登录页用手机号注册，默认密码 `123456`，注册后自动登录。
- 在「设置」页可修改自己的密码。

---

## 七、每日报告定时生成（可选）

Windows（任务计划程序）或 Mac/Linux（crontab）配置定时执行：
```bash
python report_generator.py
```
报告生成在 `reports/` 目录，可在「每日报告」页查看下载。

---

## 八、常见问题

**Q：启动报错 "address already in use" / 端口被占用？**
A：改端口启动：`PORT=8080 python app.py`（Windows 用 `set PORT=8080`）

**Q：地图不显示？**
A：检查电脑是否联网。地图瓦片来自 OpenStreetMap CDN。

**Q：新增客户时地址解析失败？**
A：Nominatim 免费服务偶尔限流，可手动填写经纬度，或稍后重试。

**Q：数据存在哪？会丢吗？**
A：全部在 `data/customers.db`。备份只需复制这个文件。

**Q：换电脑怎么办？**
A：把整个项目文件夹复制过去，装好依赖，双击启动即可。数据库一起带走。

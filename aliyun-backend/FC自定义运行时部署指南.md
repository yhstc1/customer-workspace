# FC 自定义运行时部署指南（解决 H5 下载问题）

## 根因结论（已实测）
- **FC Web 函数**网关对所有动态路由响应强制注入 `Content-Disposition: attachment`，应用层 inline 无法覆盖 → 浏览器下载 HTML。
- **OSS 直链**对匿名访问对象也强制加 `attachment`（防钓鱼策略，metadata 无法覆盖）→ 同样下载。
- 两条"静态托管"路都走不通。

## 唯一彻底解法：FC 自定义运行时
自定义运行时模式下，FC 只做 L7 转发、不注入响应头，响应头完全由自己的 HTTP server 决定。
本方案用标准库 `wsgiref` 跑 Flask app（监听 9000），`/m.html` 返回 `text/html; inline` → 浏览器渲染。

## 已准备好的包
`aliyun-backend/crm-api-custom-runtime.zip`（1.14MB），包含：
- `bootstrap`（启动脚本，设 755，自动 pip install 依赖后起 server）
- `server.py`（wsgiref 监听 9000）
- `app.py` 等后端 + `m.html` + `templates/` + `static/` + `requirements.txt`

## 控制台操作步骤（约 5 分钟）

### 1. 新建函数
- FC 控制台 → 函数管理 → 创建函数
- 选择**「使用自定义运行时创建」**（不是 Web 函数 / 不是内置运行时）
- 运行环境：Python 3.10（或"自定义运行时"基础镜像，FC 会自动给 Python 环境）
- 函数名称：`crm-api-custom`（或覆盖现有 crm-api-fc：先删 crm-api-fc，再建同名的自定义运行时函数，避免钉钉域名变动）
- 上传代码：`crm-api-custom-runtime.zip`
- 启动命令：留空（FC 自动找 `bootstrap` 执行）；若要求填，填 `./bootstrap`
- 监听端口：9000

### 2. 配置 HTTP 触发器
- 触发器类型：HTTP 触发器
- 认证方式：**匿名访问**（否则钉钉/浏览器访问报 MissingRequiredHeader）
- 方法：GET/POST/PUT/DELETE/OPTIONS 全开

### 3. 配置环境变量
与之前一致（从 .env 提取，JSON 格式）。**以下均为占位示例，真实值请填本地 .env，禁止明文写入本仓库**：
```
MYSQL_HOST=<MYSQL_HOST>
MYSQL_PORT=3306
MYSQL_USER=<MYSQL_USER>
MYSQL_PASSWORD=<MYSQL_PASSWORD>
MYSQL_DB=crm
JWT_SECRET=<JWT_SECRET>
JWT_EXPIRE_HOURS=720
DING_APP_KEY=<DING_APP_KEY>
DING_APP_SECRET=<DING_APP_SECRET>
TENCENT_MAP_KEY=<TENCENT_MAP_KEY>
ALLOW_ORIGIN=*
```

### 4. 验证
部署完成后，浏览器/手机直接访问：
```
https://<新函数域名>/m.html
```
预期：直接渲染登录页（标题"客户管理平台"，底部 4 个 Tab），**不再是下载**。

### 5. 钉钉配置
- H5 微应用主页地址改：`<新函数域名>/m.html`
- 若保留同名 `crm-api-fc`，域名不变，主页仍填 `https://crm-api-fc-jhzrzpdlrd.cn-hangzhou.fcapp.run/m.html`
- 手机钉钉清缓存（杀进程重进）后测试

## 冷启动说明
自定义运行时每次实例冷启动会 `pip install` 依赖（约 10-20s），之后常驻。首次访问稍慢属正常。

## 旧函数清理
- `crm-api`（502 那个）、`crm-api-custom`（之前 bootstrap 失败的）建议删除，避免混淆。
- OSS bucket `crm-h5-static` 已无用（attachment 坑），可删可不删。

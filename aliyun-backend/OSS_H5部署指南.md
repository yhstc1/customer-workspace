# FC H5 页面下载问题 · OSS 静态托管解决方案

## 根因（已确认）
阿里云 FC **Web 函数网关**对**所有动态路由响应**强制注入 `Content-Disposition: attachment`，
应用层设 `inline` 无法覆盖。curl 实测：
```
curl -sI https://crm-api-fc-jhzrzpdlrd.cn-hangzhou.fcapp.run/m.html
→ Content-Disposition: attachment   ← 浏览器必下载，无法渲染
```
因此「HTML 走 FC 函数返回」这条路在 FC Web 函数下**无解**。

## 解决思路
前后端分离：
- **FC 函数 `crm-api-fc`**：只跑 API（`/api/*`、`/healthz`），CORS 已为 `*`，跨域可用。
- **H5 静态页面**：托管到 OSS，OSS 对 `.html` 文件正常返回 `inline`，浏览器渲染。
- 钉钉主页指向 OSS 域名下的 `/m.html`。

## 已准备好的文件
目录：`D:\Users\User185984\Desktop\customer-workspace\aliyun-backend\h5-dist\`
```
m.html              ← H5 入口（已注入 API_BASE 指向 FC 域名，已改 /assets 引用为 /static）
static/css/mobile.css
static/css/style.css
static/js/app.js
static/js/biz-fields.js
static/js/mobile.js
static/images/about-logo.png
static/img/splash-icon.png
static/img/splash_b64.txt
```
（已移除 apk，包体 884K）

## 操作步骤（你在阿里云控制台做，约 5 分钟）

### 1. 创建 OSS Bucket
- 对象存储 OSS → Bucket 列表 → 创建 Bucket
- 名称：如 `crm-h5-static`（全局唯一，换你喜欢的）
- 地域：**华东1（杭州）**（与 FC 同地域，免流量费）
- 读写权限：**公共读**（H5 需匿名访问）
- 其余默认 → 确定

### 2. 上传文件
- 进入 bucket → 文件管理 → 上传
- 把 `h5-dist\` 下**所有内容**（含 m.html 和 static/ 目录）上传到 bucket **根目录**
- 保持目录结构：`m.html` 在根，`static/` 在根

### 3. 开启静态页面托管
- bucket → 数据湖管理 / 基础设置 → 静态页面（或「静态网站托管」）
- 默认首页：`m.html`
- 默认 404 页：可不填
- 保存

### 4. 配置钉钉
- 钉钉开发者后台 → 你的 H5 微应用：
  - **主页地址**：`https://<你的bucket>.oss-cn-hangzhou.aliyuncs.com/m.html`
  - **安全域名 / 可信域名**（H5 微应用 → 开发管理 → 服务器出口IP/应用首页地址 下方"可信域名"）：
    添加 `https://<你的bucket>.oss-cn-hangzhou.aliyuncs.com`
    （钉钉免登 requestAuthCode 要求主页域名在可信列表，否则 dd.ready 报错）

### 5. FC 函数无需改动
- `crm-api-fc` 的 CORS 已 `Access-Control-Allow-Origin: *`，OSS 跨域调用 `/api/*` 自动允许。
- 旧 `crm-api`（502 那个）建议删除，避免误访问。

## 验证
手机钉钉打开应用 → 应直接渲染登录页（标题"客户管理平台"，底部 4 个 Tab）。
用 `18607184641 / 123456` 登录 → 加载客户列表。

## 备选：若不想用 OSS
可用 FC **自定义运行时**（Python 3.10 基础镜像，自带 pip），启动标准库 `wsgiref` 监听 9000，
自己控制响应头（自定义运行时模式下网关不强制 attachment）。但需要重建函数 + 重新装依赖，
复杂度高于 OSS 方案，当前不优先。

# H5 前端静态托管部署指南（CloudBase 静态托管）

## 部署目标
把 `h5-static.zip` 解压后的内容部署到腾讯云 CloudBase 静态托管，获得一个**不强制下载**的 HTTPS 域名，钉钉 H5 微应用主页填这个地址即可。

---

## 前置条件
- 你有腾讯云账号（腾讯地图 Key 就是你的，同一个账号体系）
- `h5-static.zip` 已打好（路径：`D:\Users\User185984\Desktop\customer-workspace\h5-static.zip`）

---

## 步骤一：开通 CloudBase 静态托管

1. 打开 https://console.cloud.tencent.com/tcb
2. 如果没建过环境，点「新建环境」：
   - 环境名称：`crm-h5`（随便）
   - 计费方式：**按量计费（免费额度够用）** 或 **基础版1（约 19.9 元/月，含静态托管）**
   - 地域：选**上海**或**广州**（离武汉近，手机访问快）
3. 进入环境 → 左侧「**静态网站托管**」→ 开通（首次需要点「开通」按钮）

---

## 步骤二：上传文件

**方式 A：控制台拖拽（推荐，最简单）**
1. 静态网站托管页面 → 「文件管理」→「上传文件」
2. 把 `h5-static.zip` **解压**后的内容（注意是内容，不是整个文件夹）拖进去：
   ```
   m.html
   static/css/mobile.css
   static/css/style.css
   static/images/about-logo.png
   static/js/app.js
   static/js/biz-fields.js
   static/js/mobile.js
   ```
   ⚠️ 重要：上传后，浏览器访问地址应该是 `https://你的域名/m.html`，
   即 `m.html` 直接在根目录，`static/` 也在根目录。
   不要传成 `h5-static/m.html`（多一层目录会导致 /static/ 路径 404）。

**方式 B：CLI 上传（需装 Node）**
```bash
npm install -g @cloudbase/cli
tcb login          # 浏览器扫码登录
tcb hosting deploy h5-static -e 你的环境ID
```

---

## 步骤三：拿到域名

静态网站托管开通后，控制台会显示一个**默认域名**，形如：
```
https://crm-h5-xxxxxxx.tcloudbaseapp.com
```
这个域名：
- ✅ **不强制 `Content-Disposition`**（CloudBase 不是阿里云默认域名体系，不会注入 attachment）
- ✅ 自带 HTTPS
- ✅ 免备案（`.tcloudbaseapp.com` 是腾讯云提供的二级域名）

---

## 步骤四：验证（不用问我）

在电脑浏览器打开：
```
https://你的域名.tcloudbaseapp.com/m.html
```

**判定成功**：
- 页面**直接渲染**出 H5 登录界面（不下载）
- 浏览器开发者工具 → Network → 看 `m.html` 响应头：
  - `Content-Type: text/html` ✅
  - **没有** `Content-Disposition: attachment` ✅

如果还是下载 → 那是 CloudBase 也强制（概率极低），回头告诉我。

---

## 步骤五：钉钉 H5 微应用配置

1. 钉钉开发者后台 → 你的应用 → 「应用功能」→「H5 微应用」
2. **应用主页**填：`https://你的域名.tcloudbaseapp.com/m.html`
3. 保存

手机钉钉打开应用 → 应该正常渲染 H5，登录/客户列表等 API 调用走 FC（`crm-api-fc-nrfocbaaxv.cn-hangzhou.fcapp.run`），跨域已验证通。

---

## 后端 API 地址（已内置在 m.html）

```
https://crm-api-fc-nrfocbaaxv.cn-hangzhou.fcapp.run
```

FC 那条链路保持不动（API 返回 JSON 给 JS 读，attachment 头对 fetch 无影响，已实测通）。

---

## 验证 checklist

- [ ] CloudBase 环境已建（上海/广州）
- [ ] 静态托管已开通
- [ ] `m.html` + `static/` 在根目录（不是 h5-static/ 子目录）
- [ ] 浏览器开 `/m.html` 渲染（不下载）
- [ ] 钉钉 H5 微应用主页填了 CloudBase 域名
- [ ] 手机钉钉实测登录 + 客户列表能加载

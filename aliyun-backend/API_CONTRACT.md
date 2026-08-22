# 钉钉小程序 ↔ 云后端 接口契约

> 统一返回信封：后端所有接口返回 `{ code: 0, data: {...}, ...extra }`（成功）或 `{ code: 非0, message: "..." }`（失败）。
> 前端 `request.js` 约定：`res.data.code === 0` 时 `resolve(res.data.data)`，否则 `reject(res.data)`。
> 鉴权：除 `/api/auth/login` 与 `/api/healthz` 外，所有请求需带 `Authorization: Bearer <token>`（免登登录后由小程序存 `sessionToken`）。

## 1. 登录 / 用户

### POST /api/auth/login
- 入参：`{ authCode: "<dd.requestAuthCode 返回的 code>" }`
- 返回：`{ token: "<JWT>", user: { id, is_admin } }`
- 前端：存 `sessionToken = token`，`userId = user.id`

### GET /api/me
- 返回：`{ user: { id, username, phone, display_name, is_admin } }`

## 2. 客户

### GET /api/customers?keyword=
- 返回：`{ customers: [...], count }`

### GET /api/customers/<id>
- 返回：`{ customer: {...} }`

## 3. 事项（tasks）

### GET /api/tasks?status=&customer_id=
- 返回：`{ tasks: [...], count }`
- status 取值（重构后）：`进行中` / `已挂起` / `已完结`

### POST /api/tasks
- 入参：`{ customer_id, title, description, status, due_date }`
- 返回：`{ task: {...} }`

### PUT /api/tasks/<id>
- 入参（部分）：`{ title, description, status, due_date, pinned }`
- 返回：`{ task: {...} }`

### DELETE /api/tasks/<id>
- 返回：`{ message: "已删除" }`

### GET /api/tasks/<id>/subtasks
- 返回：`{ subtasks: [...] }`

### POST /api/tasks/<id>/subtasks
- 入参：`{ title }`
- 返回：`{ subtask: {...} }`

### PUT /api/tasks/<id>/subtasks/<sid>
- 入参：`{ title, done }`
- 返回：`{ subtask: {...} }`

## 4. 业务台账（business）

### GET /api/business?search=
- 返回：`{ businesses: [...], count }`

### POST /api/business
- 入参：`{ customer_id, company_name, business_address, number, contract_code, business_type, contract_amount, start_date, end_date, notes, business_package, business_level, date, user_name, parent_id }`
- 返回：`{ business: {...} }`

### GET /api/business/<id> / PUT /api/business/<id> / DELETE /api/business/<id>
- 同上结构

## 5. 地图 / 附近

### GET /api/nearby?lat=&lng=&radius=
- 返回：`{ nearby: [{ id, company, name, latitude, longitude, address, phone, distance }, ...], count }`
- `distance` 单位：米（优先腾讯地图驾车距离，失败兜底球面距离）

## 6. 导出 / 导入 / 报告

### POST /api/export
- 入参：`{ kind: "customers"|"business"|"all", format: "csv"|"json" }`
  - `kind=all` 强制 JSON（含客户+业务+事项全量备份）；`customers`/`business` 导出 CSV。
- 返回：`{ url: "<OSS 签名下载地址(1小时有效)>", object_key }`
  - OSS 未配置时返回 `{ warning: "OSS 未配置", content: "<原始文本前5000字>" }`，前端复制到剪贴板。
- 前端下载流程：`dd.downloadFile({url})` → `dd.saveFileToDisk({filePath})`；保存失败退化为复制链接。

### POST /api/import
- 入参：`{ kind: "customers"|"business", csv: "<CSV 文本（含表头）>" }`
- 返回：`{ imported: <新增条数>, skipped: <剔除条数>, skipped_details: [{line, key, reason}], kind }`
- **去重规则**：
  - 客户：按 `company`（公司名）去重，同一 user 下已存在同名客户 / 同文件重复行 → 跳过并计入 `skipped_details`。
  - 业务：按 `number + company_name`（业务号码 + 公司名）组合去重，库内已存在 / 同文件重复 → 跳过并计入明细。
  - 空公司名 / 写入失败也计入 `skipped_details`（reason 说明）。
- `skipped_details` 每条含 `line`（CSV 行号，含表头从 2 起）、`key`（去重键，如公司名或 "公司名 / 号码"）、`reason`（剔除原因）。前端默认展示前 20 条，超出提示折叠，可一键复制全部明细。

### CSV 表头模板
- 客户（customers）：`company,name,phone,address,business_type,importance,tier,notes`
- 业务（business）：`customer_id,company_name,business_type,business_level,number,contract_code,contract_amount,start_date,end_date,business_address,date,user_name,parent_id,notes`

### GET /api/report
- 返回：`{ report: { customer_count, business_count, task_open, task_done, generated_at } }`

## 7. 管理（仅 admin）

### GET /api/admin/users → `{ users: [...] }`
### PUT /api/admin/users/<id>/status → `{ message }`（status: active|pending|disabled）
### POST /api/admin/bind-dingtalk → `{ message }`（入参 `{ user_id, dingtalk_user_id }`，首次建账号绑定钉钉 userId 到 users 表）

## 字段类型说明（RDS MySQL）
- 时间戳列（created_at/updated_at/due_date/start_date/end_date 等）统一为 **TEXT**，由应用层写本地时间字符串（避免 MySQL 时区错位）。
- 所有隔离基于 `user_id`（本地整数 id，来自 JWT payload.uid）。钉钉 userId（字符串）仅用于免登时映射，存于 `users.dingtalk_user_id`。

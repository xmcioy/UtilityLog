# UtilityLog API 文档（API.md）

> 版本：0.5.2（2026-10-25）
> 基准实现：`auth_server.py`（认证网关，`ThreadingHTTPServer`，默认监听 `127.0.0.1:8099`）。
> 本地访问经 nginx `:8089` 反代到 `:8099`；公网经 Cloudflare Tunnel 暴露。
> 本文档与代码同步维护；路由或参数变更时必须同步更新。

---

## 1. 服务地址与数据格式

| 项 | 说明 |
|---|---|
| 服务地址 | `http://127.0.0.1:8099`（本地直连） / `http://127.0.0.1:8089`（nginx 反代） |
| 请求编码 | `application/x-www-form-urlencoded`（登录 / 注册 / 退出为表单 POST） |
| 响应 | 登录注册类为 302 跳转 + Set-Cookie；`/data.js` 为 JS 赋值语句（`application/javascript`）；静态资源按 mimetype |
| 会话 | 180 天 HttpOnly Cookie（`ul_token`），持久化于 `api_tokens` 表 |

## 2. 鉴权方式

请求按以下顺序依次尝试，命中即通过：

1. **Cookie**：请求头 `Cookie: ul_token=<token>`（登录 / 注册成功后浏览器自动携带）
2. **Bearer Token**：请求头 `Authorization: Bearer <token>`（`api_tokens` 表 token，供 Skill / 外部程序）
3. **Basic**：请求头 `Authorization: Basic base64(user:password)`（兼容旧脚本）

> token 有效期：签发时写入 `expires_at = 当前时间 + 180 天`；`api_tokens.expires_at IS NULL` 表示永不过期。
> 每次命中自动更新 `last_used`。
> 所有 `/data.js` 与静态资源请求都要求鉴权；未登录的脚本 / 图片 / JSON 类请求返回 401。

## 3. 路由总表

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/login` | 无需 | 用户名密码登录，成功种 Cookie 并 302 到 `/` |
| POST | `/register` | 无需 | 注册新用户（PBKDF2 哈希入库），成功即自动登录 |
| POST | `/logout` | 无需（读取 Cookie） | 吊销 token、清除 Cookie，302 到 `/login.html` |
| POST | `/mcp` | 必须 | MCP Streamable HTTP 端点（JSON-RPC 2.0）。鉴权同上；推荐 `Authorization: Bearer <API Key>`。与前端共用 nginx `:8089` 端口 |
| POST | `/api/bills/upload` | 必须 | 上传账单文件（multipart/form-data），自动解析出草稿（**不落库**），见 4.7 |
| POST | `/api/families` | 必须 | 新建家庭（JSON `{name}`），重复名称返回 400，见 4.9 |
| POST | `/api/bills` | 必须 | 账单确认入库（JSON，add_bill 兼容字段，upsert），见 4.8；同时服务手工录入 |
| GET | `/data.js` | 必须 | 按当前登录用户动态导出数据（`window.UTILITY_DATA = {...};`） |
| GET | `/api/me` | 必须 | 当前登录用户信息 |
| GET | `/api/tokens` | 必须 | API Key 列表（仅前缀）；**列表为空时自动签发一把并一次性返回明文** |
| POST | `/api/tokens/reset` | 必须 | 重置 API Key，返回一次明文（旧 Key 立即失效） |
| POST | `/api/password` | 必须 | 修改密码，成功后当前会话全部失效 |
| GET | `/api/families` | 必须 | 可见家庭列表（含被共享的），标注 `can_manage_members` |
| GET | `/api/families/{id}/members` | 必须 | 家庭成员列表（仅成员可见） |
| POST | `/api/families/{id}/members` | 必须（仅拥有者） | 共享家庭给某用户（权限与拥有者等同） |
| POST | `/api/families/{id}/members/remove` | 必须（仅拥有者） | 取消某用户对该家庭的共享 |
| GET | `/api/users` | 必须 | 可共享的目标用户（仅用户名，不含凭据） |
| GET | `/`、`/index.html`、`/login.html`、`/settings.html`、其它静态 | 必须 | 已登录 → 返回 `site/` 下静态文件；未登录 → 页面类回登录页、资源类 401 |

> `/api/*` 一律要求登录，未登录返回 **401 JSON**（不是登录页），便于脚本区分。

> 注意：`POST /login|/register|/logout|/mcp` 之外的 POST 一律 404；`GET /login|/register|/logout` 同样 404（避免方法混淆）。
> `GET /mcp` 返回 405（暂只支持 POST，不提供 SSE 流式响应）。

## 4. 接口详情

### 4.1 POST /login

校验 `users` 表用户名密码，成功签发 180 天会话 token。

| 参数 | 必填 | 说明 |
|---|---|---|
| `user` | 是 | 用户名 |
| `pass` | 是 | 密码（与 `users.password_hash` 做 PBKDF2-SHA256 校验） |

返回：

- 成功：`302 Location: /`，响应头 `Set-Cookie: ul_token=<token>; Path=/; HttpOnly; SameSite=Lax; Max-Age=15552000`
- 失败（用户名不存在 / 密码错误 / 账号停用）：`302 Location: /login.html?err=1`（页面回显「用户名或密码错误，请重试」）

curl 示例：

```bash
curl -i -X POST -d "user=demo&pass=secret123" http://127.0.0.1:8089/login
```

### 4.2 POST /register

注册新用户并自动登录。规则：用户名唯一；密码至少 4 位；密码经 PBKDF2-SHA256（120000 迭代）哈希后存 `users.password_hash`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `user` | 是 | 用户名（唯一，重复返回失败） |
| `pass` | 是 | 密码（至少 4 位） |
| `display_name` | 否 | 显示名称，缺省用用户名 |

返回：

- 成功：`302 Location: /` + `Set-Cookie: ul_token=<token>`
- 失败：`302 Location: /login.html?err=2&msg=<urlencode 后的原因>`（页面回显「注册失败：...」，常见原因为「用户名已存在」「密码至少 4 位」）

curl 示例：

```bash
curl -i -X POST \
  -d "user=newuser&pass=abcd1234&display_name=新用户" \
  http://127.0.0.1:8089/register
```

### 4.3 POST /logout

读取 `ul_token` Cookie 吊销对应 token（`DELETE api_tokens`），清除 Cookie，302 到登录页。

curl 示例（携带 Cookie）：

```bash
curl -i -X POST -H "Cookie: ul_token=<token>" http://127.0.0.1:8089/logout
```

### 4.4 GET /data.js

按当前登录用户动态导出完整数据（`site/data.js` 的运行时来源，不再依赖手工 `sync_site.py`）。必须通过鉴权。

响应：

```
Content-Type: application/javascript; charset=utf-8
Cache-Control: no-store

window.UTILITY_DATA = {"user":{...},"families":[...],"bills":[...]};
```

返回结构：

```json
{
  "user": { "id": 1, "username": "demo", "display_name": "Demo" },
  "families": [ { "id": 1, "name": "我的家", "user_id": 1, "created_at": "..." } ],
  "bills": [
    {
      "id": 12, "family_id": 1, "user_id": 1,
      "bill_month": "2026-09", "type": "water",
      "usage": 12.0, "usage_unit": "m³",
      "prev_reading": 100, "cur_reading": 112,
      "water_unit_price": 4.05, "sewage_unit_price": 2.0,
      "water_fee": 48.6, "sewage_fee": 21.6, "amount": 70.2,
      "bill_date": "2026-09-15", "image": null, "note": null,
      "current_tier": null, "tier_remaining": null,
      "year_usage": null, "tier_detail": null
    }
  ]
}
```

> `type` 取值为 `water | electric | gas`；三张账单表经 `utility.dump_json()` 统一投影为同一列集（非本表字段为 `null`）。
> 未登录访问返回 `401`（含 `WWW-Authenticate: Basic realm="UtilityLog Private"`）。

curl 示例（三种鉴权任选其一）：

```bash
# Cookie（登录后）
curl -b "ul_token=<token>" http://127.0.0.1:8089/data.js

# Bearer Token（Skill / 脚本推荐）
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8089/data.js

# Basic
curl -u demo:secret123 http://127.0.0.1:8089/data.js
```

### 4.5 GET 静态资源

| 路径 | 说明 |
|---|---|
| `/` | 重定向到 `/index.html` |
| `/index.html` | 主展示页（已登录才能看） |
| `/login.html` | 登录 / 注册页；`?err=1` 登录失败、`?err=2&msg=...` 注册失败回显 |
| `/vendor/*`、`/images/*` 等 | `site/` 下静态文件，路径规范化防 `../` 穿越，不存在返回 404 |

缓存策略：图片类（png/jpg/jpeg/gif/svg/webp/ico）`Cache-Control: public, max-age=604800`（7 天）；`.js` 为 `no-cache, must-revalidate`。

未登录访问规则：

- `.js` / `.json` / `.css` / 图片类 → `401` + `WWW-Authenticate: Basic realm="UtilityLog Private"`
- 其它页面类 → `200` 返回 `login.html`（登录页本身无需登录）

### 4.6 POST /mcp（MCP Streamable HTTP）

MCP（Model Context Protocol）端点，复用 `scripts/mcp_server.py` 的全部 10 个工具
（add_bill / list_bills / list_families / add_family / update_bill / delete_bill /
share_family / unshare_family / list_members / get_summary），与前端共用 nginx `:8089`
同一端口 —— 域名只需转发 8089 即可同时访问网页与 MCP。

| 项 | 说明 |
|---|---|
| 传输 | Streamable HTTP（JSON-RPC 2.0 over POST），不支持 SSE |
| 鉴权 | 与普通 API 一致（Cookie / Bearer / Basic）；推荐 Bearer **API Key**（网页「设置」中重置获取，`scope='api'` 不过期） |
| 请求体 | 单条 JSON-RPC 消息或 batch 数组，上限 1MB |
| 成功响应 | `200` + JSON-RPC 响应（batch 返回数组）；纯通知（无 `id`）返回 `202` 无响应体 |
| 错误响应 | 未鉴权 `401`；body 超限 `413`；JSON 解析失败 `400` + `-32700`；未知方法/工具 `-32601` |
| 安全约束 | 工具参数中的 `user` 字段会被**已认证用户强制覆盖**，HTTP 通道无法冒充他人操作 |

MCP 客户端配置示例（远程，走域名）：

```json
{
  "mcpServers": {
    "utilitylog": {
      "url": "https://<your-domain>/mcp",
      "headers": { "Authorization": "Bearer <API Key>" }
    }
  }
}
```

本地 stdio 配置（不经 HTTP，直接跑 `scripts/mcp_server.py`）仍然可用，见该文件头部说明。

curl 示例：

```bash
curl -s -X POST http://127.0.0.1:8089/mcp \
  -H "Authorization: Bearer <API Key>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 4.7 用户管理与家庭共享（`/api/*`）

全部要求已登录（Cookie / Bearer / Basic 三通道任一），响应一律 JSON。

**GET `/api/me`** → `{"ok":true,"user":{"id":..,"username":..,"display_name":..,"created_at":..}}`

**GET `/api/tokens`** → Key 列表（只含前缀与创建时间）。

```json
{"ok": true, "tokens": [{"id": 1, "prefix": "a1b2c3d4", "created_at": "..."}],
 "one_time_plaintext": null}
```

> 列表为空时（例如刚注册的用户）会自动签发一把，并把明文放在 `one_time_plaintext`
> 随这次响应一并返回 —— 明文只出现这一次，后续访问该字段恒为 `null`。

**POST `/api/tokens/reset`** → `{"ok":true,"token":"<明文>"}`，旧 Key 立即失效。

**POST `/api/password`**（表单 `old` / `new`）→ 成功后当前会话与 API Key 全部失效，并清除 Cookie。

**GET `/api/families`** → 可见家庭（自己拥有的 + 别人共享给他的），每项带 `role` 与
`can_manage_members`（仅 owner 为 `true`）。

**GET `/api/families/{id}/members`** → `[{"user_id":..,"username":..,"role":"owner|member"}]`，
非成员返回 404。

**POST `/api/families/{id}/members`**（表单 `username`）→ 共享家庭。**仅拥有者**可操作，
被共享者获得与拥有者等同的权限（可读、可写、可删）。

**POST `/api/families/{id}/members/remove`**（表单 `username`）→ 取消共享，仅拥有者可操作。

**GET `/api/users`** → 供共享时选择目标用户，只暴露用户名，不含任何凭据。

### 4.7 POST /api/bills/upload（0.5.0 账单上传识别）

`multipart/form-data` 上传账单文件（`file` 字段，PDF / png / jpg / webp，≤20MB），
自动解析出**草稿**（不落库），前端核对后调 4.8 入库。

| 项 | 说明 |
|---|---|
| PDF | 本地解析文本层（pypdf，deploy 自动安装；缺失时返回安装提示并优雅降级） |
| 图片 | 本地不做 OCR：若「设置 → 模型 API」配置了视觉模型则自动识别，否则返回提示人工填写 |
| 附件 | 原样保存到运行目录 `images/uploads/<时间戳>_<文件名>`，`file` 字段返回相对路径，可经 `/images/uploads/…` 访问 |

成功响应：

```json
{ "ok": true, "file": "uploads/20261024-101000_202504 账单.pdf",
  "draft": { "parse_ok": true, "bill_type": "electric", "confidence": "high",
             "bill": { "month": "2025-04", "usage": 14, "amount": 7.71,
                       "peak_usage": 11, "peak_price": 0.617, "...": "…" },
             "message": "识别成功，请核对后保存" } }
```

`draft.bill` 字段与 4.8 的入库字段一致；解析失败时 `parse_ok=false` 且只包含能匹配到的字段，绝不编造。

### 4.8 POST /api/bills（0.5.0 确认入库 / 手工录入）

JSON body，字段与 MCP `add_bill` 工具完全兼容（`family`、`month`、`type`、`usage`、
`amount` 必填，峰谷/分项/档位可选；同家庭同月同类型 upsert 覆盖）。
入库统一以**当前登录用户**执行（body 里的 `user` 会被忽略，防冒充），
校验逻辑复用 MCP 工具层（金额不变式由调用方保证）。

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8089/api/bills \
  -H "Content-Type: application/json" \
  -d '{"family":"我的家","month":"2025-04","type":"electric","usage":14,
       "amount":7.71,"peak_usage":11,"peak_price":0.617,
       "valley_usage":3,"valley_price":0.307,"image":"uploads/xxx.pdf"}'
```

成功：`{"ok": true, "message": "已保存", "bill": {"saved": true, "id": 1, …}}`；
失败：400 + `{"ok": false, "error": "原因"}`（家庭不存在/无权限/参数缺失等）。

### 4.9 POST /api/families（0.5.2 网页新建家庭）

JSON body `{"name": "家庭名"}`，为当前登录用户创建家庭（创建者自动成为 owner）。
重复名称返回 400。上传弹窗里「＋ 新建家庭…」即调用此接口。

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8089/api/families \
  -H "Content-Type: application/json" -d '{"name":"我的家"}'
```

## 5. 错误响应汇总

| 状态码 | 场景 |
|---|---|
| 302 | 登录 / 注册 / 退出成功或失败的跳转（携带 `Location` 与 `Set-Cookie`） |
| 401 | 未登录访问需鉴权资源（/data.js、/mcp、/api/*、脚本、图片、CSS、JSON） |
| 404 | 未知路由（POST 非四接口、GET /login 等）、静态文件不存在、路径穿越被拦截、非成员访问成员表 |
| 405 | `GET /mcp`（只支持 POST） |
| 413 | 请求体超限（/mcp 上限 1MB；/api/bills/upload 上限 20MB） |

## 6. 部署与服务

- 启动：`python3 auth_server.py`（默认 `127.0.0.1:8099`，启动时 `ensure_auth_tables()` 幂等建 auth 三表）
- 后端切换：环境变量 `UL_BACKEND=mysql`（读取运行目录 `db_config.json`）或 `sqlite`（默认）
- 路径：静态模板取源码 `site/`；运行数据（`data/`、`db_config.json`、日志）取运行目录（`UL_APP_DIR` > `UL_ROOT` > 仓库根）
- 部署 / 升级：`bash scripts/deploy.sh install | upgrade`（0.4.1 起升级末尾自动跑 `scripts/e2e_verify.py`
  端到端回归，未通过即判定该版本不可发布）
- 部署见 README「一键部署 / nginx 反代」；服务托管见 `scripts/deploy.sh` / `deploy.py`
  （无 GUI 会话上下文时自动回退独立进程）

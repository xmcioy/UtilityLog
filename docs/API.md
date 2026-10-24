# UtilityLog API 文档（API.md）

> 版本：0.3.1（2026-10-24）
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
| GET | `/data.js` | 必须 | 按当前登录用户动态导出数据（`window.UTILITY_DATA = {...};`） |
| GET | `/`、`/index.html`、`/login.html`、其它静态 | 必须 | 已登录 → 返回 `site/` 下静态文件；未登录 → 页面类回登录页、资源类 401 |

> 注意：`POST /login|/register|/logout` 之外的 POST 一律 404；`GET /login|/register|/logout` 同样 404（避免方法混淆）。

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

## 5. 错误响应汇总

| 状态码 | 场景 |
|---|---|
| 302 | 登录 / 注册 / 退出成功或失败的跳转（携带 `Location` 与 `Set-Cookie`） |
| 401 | 未登录访问需鉴权资源（/data.js、脚本、图片、CSS、JSON） |
| 404 | 未知路由（POST 非三接口、GET /login 等）、静态文件不存在、路径穿越被拦截 |

## 6. 部署与服务

- 启动：`python3 auth_server.py`（默认 `127.0.0.1:8099`，启动时 `ensure_auth_tables()` 幂等建 auth 三表）
- 后端切换：环境变量 `UL_BACKEND=mysql`（读取运行目录 `db_config.json`）或 `sqlite`（默认）
- 路径：静态模板取源码 `site/`；运行数据（`data/`、`db_config.json`、日志）取运行目录（`UL_APP_DIR` > `UL_ROOT` > 仓库根）
- launchd 托管示例见 `scripts/deploy.sh`（0.3.1 起），nginx 反代见 INSTALL.md

# UtilityLog 知识架构与代码走读

> 建立日期：2026-10-24 · 对应版本：v0.3.0（commit `3586948`）
> 目的：为后续维护这个开源项目打底——搞清楚「代码怎么跑、数据怎么流、哪里有坑」。
> 本文档为**只读走读产出**，未修改任何项目源码。

---

## 1. 一句话定位

家庭水/电/燃气账单的**自托管记录与展示系统**：账单截图 → AI 解析 → 本地数据库 → 静态网页看板。
技术栈刻意极简：**Python 3 标准库（零 pip 依赖）· SQLite/MySQL 双后端 · 原生 HTML/JS + ECharts · nginx 反代**。

---

## 2. 分层架构

```
┌─ 录入层 ────────────────────────────────────────────┐
│  AI 技能 skill/SKILL.md（视觉解析账单）              │
│  CLI scripts/utility.py（唯一数据写入口）            │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─ 存储层 ────────────────────────────────────────────┐
│  scripts/db_backend.py  ← 方言抽象层（关键设计）     │
│  ├─ SQLite（默认，data/utility.db，零依赖）          │
│  └─ MySQL 8+（可选，db_config.json + 低权限用户）    │
│  表：users / families / bills_water / bills_electric │
│      / bills_gas / api_tokens / user_settings       │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─ 服务层 ────────────────────────────────────────────┐
│  auth_server.py（127.0.0.1:8099）                   │
│  Cookie会话 / Bearer Token / Basic 三重鉴权          │
│  /data.js 按当前登录用户动态导出                     │
└───────────────────────┬─────────────────────────────┘
                        ▼
┌─ 展示层 ────────────────────────────────────────────┐
│  site/index.html（804 行，含 ECharts 图表）          │
│  site/login.html（登录 + 注册）                      │
│  nginx :8089 反代 → auth_server :8099               │
└─────────────────────────────────────────────────────┘
```

---

## 3. 关键设计决策（维护时必须守住）

| # | 决策 | 原因 | 违反后果 |
|---|---|---|---|
| 1 | **按费种拆三表**（`bills_water`/`bills_electric`/`bills_gas`） | 三类账单字段差异大（电费有峰谷八列、水费有分项费、燃气简单），拆表消除无关 NULL | 回退单宽表 → 大量 NULL 列，文档明确禁止 |
| 2 | **总价 = 分项之和** | 水：`amount = water_fee + sewage_fee`；电：`amount = peak_usage×peak_price + valley_usage×valley_price`；气：`amount = usage×unit_price` | 金额对不上，年度趋势图失真 |
| 3 | **峰谷四示数独立列** | `peak_prev/peak_cur/valley_prev/valley_cur` 必须分列，禁止合并 | 原始数据丢失，无法复算峰谷电量 |
| 4 | **阶梯档位必录** | `current_tier` / `tier_remaining` / `year_usage` / `tier_detail`(JSON) | 网页阶梯进度条与表格缺列 |
| 5 | **同家庭同月同类型唯一** | `UNIQUE(family_id, bill_month)` + upsert 覆盖 | 重复录入产生重复行 |
| 6 | **业务 SQL 只写 SQLite 方言** | `db_backend._mysql_sql()` 负责翻译 | 双后端语义漂移 |
| 7 | **源码 / 运行目录分离** | `UL_APP_DIR` > `UL_ROOT` > 源码根；真实配置与数据不入库 | 开源仓库泄露凭据 |
| 8 | **缺项不编造** | CLI 只写实有字段，缺失留 NULL | 凭空生成数据 |

---

## 4. 代码地图

### 4.1 `scripts/db_backend.py`（156 行）— 最该先读的文件

整个项目的枢纽。上层业务只写 SQLite 风格 SQL，这里翻译给 MySQL。

| 函数 | 职责 |
|---|---|
| `resolve_app_dir()` | `UL_APP_DIR` > `UL_ROOT` > 脚本上级目录 |
| `get_backend()` | 读 `UL_BACKEND`，默认 `sqlite` |
| `get_conn()` | 返回统一连接对象（SQLite `Row` / MySQL `DictCursor`，都支持 `row['col']`） |
| `_mysql_sql()` | 方言翻译：`?`→`%s`、`AUTOINCREMENT`→`AUTO_INCREMENT`、`datetime('now','localtime')`→`NOW()`、`usage` 加反引号（MySQL 保留字） |
| `upsert_sql()` | 双方言 upsert：SQLite `ON CONFLICT ... DO UPDATE` / MySQL `ON DUPLICATE KEY UPDATE` |
| `_split_statements()` | MySQL 无 `executescript`，按分号拆句逐条执行 |

> ⚠️ `_mysql_sql()` 是**字符级正则替换**，不是真正的 SQL 解析器。改写 SQL 语法时要格外小心。

### 4.2 `scripts/utility.py`（501 行）— CLI 唯一数据入口

命令：`init` / `register` / `list-users` / `add-family` / `add` / `update` / `delete` / `list` / `dump`

关键机制：
- **按类型路由**：`TABLE_BY_TYPE` 把 `water|electric|gas` 映射到三张表
- **三表 UNION 统一投影**：`UNION_COLS`（第 310–347 行）把三表投影成同一列集，前端和 `sync_site` 无需感知拆表细节；非本表字段为 NULL；含 `sewage_price` 旧别名兼容列
- **用户隔离**：所有读写强制带 `user_id`（由 `--user` 解析）
- **`find_bill_table()`**：`update`/`delete` 依次在三表按 id 定位，自动路由
- **`tier_detail`**：写入时 `json.dumps`，读取原样输出

### 4.3 `auth_server.py`（425 行）— 认证网关

监听 `127.0.0.1:8099`，nginx 反代全部请求到此。

| 端点 | 行为 |
|---|---|
| `POST /register` | 创建用户（PBKDF2 哈希），成功即登录 |
| `POST /login` | 校验 users 表 → 种 180 天 HttpOnly Cookie → 302 到 `/` |
| `POST /logout` | 吊销 token + 清 Cookie |
| `GET /data.js` | **按当前会话用户动态导出**（不依赖手工 sync） |
| `GET /*` | Cookie/Bearer/Basic 三选一鉴权 → 返 `site/` 静态文件 |

密码方案：`pbkdf2_hmac('sha256', 120000 次迭代)`，盐 16 字节，格式 `pbkdf2_sha256$120000$salt$hash`。

### 4.4 `scripts/sync_site.py`（52 行）— 站点导出

`dump_json(user)` → `<运行目录>/site/data.js`（`window.UTILITY_DATA = {...}`）+ 给 `index.html` 的 `data.js?v=` 打版本戳规避 Cloudflare 缓存。

### 4.5 `site/index.html`（804 行）— 展示

原生 JS + ECharts（`vendor/echarts.min.js` 已内置，无 CDN 依赖）：
- 年度趋势（**总价单柱**，水/电/气三柱 + 折线用量的双 Y 轴）
- 用能明细（费种 Tabs + 年份切换 + 分项堆叠柱 + **三段阶梯进度条**：绿/黄/粉，阈值 水 220/300、电 3120/4800、气 310/520）
- 当年汇总 / 月度明细（三张独立表，分页 + 多维筛选）

### 4.6 `skill/SKILL.md`（116 行）— AI 录入契约

脱敏模板（`{{PLACEHOLDER}}` 占位）。规定了账单解析规则、峰谷四值分读、阶梯推算价目表、在线文档 27 列表头、录完三端校验流程。**这是 AI 行为的唯一权威来源**。

---

## 5. 数据模型要点

```
users(id, username, password_hash, display_name, is_active)
  │
  ├─→ families(id, name, user_id)                ← 家庭归属用户
  │     │
  │     └─→ bills_water    (family_id, user_id, bill_month, usage, water_unit_price,
  │     │                   sewage_unit_price, water_fee, sewage_fee, amount,
  │     │                   prev_reading, cur_reading, current_tier, tier_remaining,
  │     │                   year_usage, tier_detail, bill_date, image, note)
  │     ├─→ bills_electric (…, peak_prev/peak_cur/valley_prev/valley_cur_reading,
  │     │                   peak_usage, peak_price, valley_usage, valley_price, unit_price)
  │     └─→ bills_gas      (…, unit_price)
  │
  ├─→ api_tokens(id, user_id, token, scope, expires_at, last_used)
  └─→ user_settings(user_id, model_api_base, model_api_key, model_name, theme)
```

三表唯一约束均为 `UNIQUE(family_id, bill_month)`。

---

## 6. 部署形态（通用说明）

> 本节描述**通用部署形态**，不含任何特定机器的路径、进程号或账号信息。
> 各开发者的实际部署状态见本地协作区 `.agent-sync/PROJECT.md`（不入库）。

| 项 | 说明 |
|---|---|
| 源码仓库 | 存放代码 / 模板 / 文档 / 脱敏示例，由 git 管理 |
| 运行目录 | 存放数据库 / 图片 / 配置 / 日志 / 程序副本，由 `UL_APP_DIR` 指定，gitignore |
| 认证网关 | 监听 `127.0.0.1:8099`，通常由 launchd（macOS）或 systemd（Linux）托管 |
| nginx | 监听 `:8089` → 反代 `127.0.0.1:8099` |
| 数据库 | SQLite（默认，零依赖）或 MySQL 8+（`UL_BACKEND=mysql`） |
| 鉴权行为 | 未登录 `/` → 200 登录页；未登录 `/data.js` → 401 |

**目录分离要点**：静态模板来自**源码** `site/`，运行时数据（`data.js` / 数据库 / 图片 / 日志 / 凭据）全部在**运行目录**。
`site/images` 指向运行目录 `images/` 的软链由部署脚本创建，不随源码入库。

---

## 7. 已验证存在的问题（按严重度）

> 全部经过实测复现，非静态推断。

### 🔴 P1-1　`update --sewage-price` 静默失效（兼容别名 broken）

`update_bill()` 只认 `sewage_unit_price`；`sewage_price` 被当作**未授权字段**过滤掉 → 输出 `no fields to update`，值不变。

```
$ utility.py --user alice update 1 --sewage-price 3.0
no fields to update          ← 库中值仍为 2.0
```
**根因**：`update_bill()` 里的兼容代码检查 `"sewage_unit_price" not in fields`，但 CLI 侧 `a.sewage_unit_price` **总是存在**（默认 `None`），条件永不成立 → 别名永远不会被转换。
**影响**：旧脚本用 `--sewage-price` 更新污水单价会静默无效果（`add` 路径正常）。
**修法**：在 `update_bill` 入口改为「若 `sewage_unit_price` 为 None 且 `sewage_price` 非 None，则取后者」。

### 🔴 P1-2　SQLite 与 MySQL 的家庭名唯一性语义不一致

| 后端 | 约束 | 语义 |
|---|---|---|
| SQLite `db/schema.sql:17` | `name TEXT NOT NULL UNIQUE` | **全局唯一** |
| MySQL `db/schema.mysql.sql:20` | `UNIQUE KEY uq_families_user_name (user_id, name)` | **用户内唯一** |

实测：用户 alice 建「我家」后，用户 bob 建「我家」→ `family already exists: 我家` ❌

**影响**：违背 DESIGN.md 第 213 行「家庭名只在同一用户内唯一」的声明；在 SQLite 后端上多用户不能各自建同名家庭；两个后端行为分叉。
**修法**：SQLite 改 `UNIQUE(user_id, name)`（需迁移脚本处理存量重复）。

### 🟠 P2-1　CLI 无档位参数，无法写入阶梯信息

`TABLE_FIELDS` 里定义了 `current_tier`/`tier_remaining`/`year_usage`/`tier_detail`，`add_bill()` 也有对应形参，**但 argparse 没有暴露任何 `--current-tier` / `--tier-remaining` / `--year-usage` / `--tier-detail` 选项**。

```
$ utility.py add ... --current-tier 第一档 --tier-remaining 100 --year-usage 50
error: unrecognized arguments: --current-tier 第一档 --tier-remaining 100 --year-usage 50
```

**影响**：`skill/SKILL.md` 反复强调「分档计费必须记录」、DESIGN.md 第 117 行列为「必须遵守」原则——但 CLI 走不通。库里现存 `current_tier='第一档'` 的数据是更早期直写或手工补录的。
**修法**：为 `add`/`update` 补齐 4 个 argparse 选项并透传。

### 🟠 P2-2　`update --month` 静默失效

`update_bill()` 里 `month` → `bill_month` 的转换同样因「键总是存在且值为 None」而失效；且 `bill_month` 不在 `TABLE_FIELDS` 白名单内，双重拦截 → 改账期报 `no fields to update`。
**影响**：无法修正录错的月份（只能删了重录）。

### ✅ P3-1　`get_backend()` 不读 `db_config.json` 的 `backend` 字段（0.5.2 已修）

文档（README / DESIGN）声称优先级为 `UL_BACKEND` > `db_config.json.backend` > `sqlite`，早期实现只读环境变量：

```python
def get_backend():
    return (os.environ.get("UL_BACKEND") or "sqlite").strip().lower()
```

**影响**：`db_config.json` 里明明写了 `"backend": "mysql"`，但不加 `UL_BACKEND=mysql` 就静默跑 SQLite。文档与实现不一致，易误判部署状态。

**修法（0.5.2）**：`get_backend()` 现在按文档优先级读取 —— 环境变量未指定时读配置文件的 `backend` 字段，都没有才默认 `sqlite`；launchd 部署仍在 plist 里显式写 `UL_BACKEND`，行为不变。回归见 `scripts/test_db_backend.py`。

### ✅ P3-2　`send_login_page` 的 `__ERR__` 占位符不存在（0.5.2 已删）

`auth_server.py:265` 做 `body.replace(b"__ERR__", err)`，但 `site/login.html` 里**没有 `__ERR__` 占位符**（登录页用 JS 读 `?err=` 参数渲染错误）。
**影响**：无害但冗余——服务端注入的错误消息永远不会显示；实际错误提示靠前端 JS，行为正确。多余的分支代码易误导维护者。

### 🟡 P3-3　`send_login_page` 返回 200 而非 401

未登录访问页面返回 200（登录页内容）。设计如此（登录页要能渲染），但语义上未认证请求返回 200 会干扰监控与缓存策略。

### 🟡 P3-4　`family_id_by_name` 每条命令重复查库

`add_bill` 里连续调用 `require_user` → `user_id_by_name`（开一次连接）+ `family_id_by_name`（再开一次连接），`add` 路径最多开 4~5 次连接。数据量小时无感，但 SQLite 下连接开销显著。

### ✅ P3-5　`register_user` 吞掉所有异常（0.5.2 已修）

```python
except Exception:
    print(f"user already exists: {username}")
```
任何异常（磁盘满、表不存在、字段超长）都被误报为「用户已存在」，排查困难。

### ✅ P3-6　`_mysql_sql` 的 `usage` 反引号替换作用于整个 SQL 字符串（0.5.2 已修）

```python
sql = re.sub(r"(?<!`)\busage\b(?!`)", "`usage`", sql)
```
不区分列名与字符串字面量。若将来 SQL 里出现 `'usage'` 字面量会被破坏。

**修法（0.5.2）**：`_mysql_sql()` 先把字符串字面量摘出来占位，替换完再放回 ——
`?`→`%s` 与 usage 反引号都只作用于代码部分。同类隐患（`LIKE '%?%'` 被改成 `'%%s%'`）
一并堵住。回归见 `scripts/test_db_backend.py`（17 项断言）。

---

## 8. 开源安全提醒

> 0.5.2 更新：URL 内嵌凭据的问题**已修复** —— 4 个 remote 的 token 全部移入
> macOS 钥匙串（`credential.helper=osxkeychain`），URL 已清理为无凭据形式。
> 遗留事项：钥匙串里的 token 仍是原值，**建议尽快轮换**（曾出现在 URL/history 里的凭据
> 都应视为已泄露）。

历史问题记录（修复前）：`git remote` 中 3 个 remote 的 URL 内嵌了明文凭据：

```
gitea   https://xmcioy:<token>@<gitea-host>/...
github  https://xmcioy:<token>@github.com/...
```

这些 token 保存在 `.git/config`（本地文件，未入库，已被 `.gitignore` 覆盖），但：
- 一旦 `.git/config` 被误提交、或被日志/备份/截屏带出，**凭据即泄露**
- 建议改用 credential helper 或 SSH key，并**轮换这两个 token**

`.gitignore` 覆盖良好：`data/`、`images/`、`site/data.js`、`auth_config.json`、`db_config.json`、`*.log`、`SKILL.md`（根目录私有副本）均已排除，`git ls-files` 确认无运行数据入库 ✅。

---

## 9. 部署链路速查（通用形态）

```
进程管理（launchd / systemd）
  ├─ 执行: python3 <运行目录>/auth_server.py
  ├─ 环境变量: UL_APP_DIR=<运行目录>、UL_BACKEND=sqlite|mysql
  └─ RunAtLoad + KeepAlive（崩溃自动重启）
       ↓
  auth_server.py → 127.0.0.1:8099
       ↓
nginx  →  proxy_pass http://127.0.0.1:8099;
       ↓
浏览器 → http://localhost:8089
```

> 进程标签与配置路径由 `scripts/deploy.sh` / `scripts/deploy.py` 自动生成（基于 `$HOME`
> 推导，不硬编码用户名），详见 README「一键部署」。

**源码与运行目录的边界**：
- 静态模板来自**源码** `site/`（`index.html`/`login.html`/`vendor/`），其中 `site/images` 是软链 → 运行目录 `images/`
- 运行时数据（`data.js`/DB/图片/日志/配置）在**运行目录**
- `sync_site.py` 会**改写源码仓库的 `site/index.html`**（加版本戳）——这是运行期写源码树，会污染 git 工作区（当前 `git status` 干净，说明尚未触发或已还原）

---

## 10. 维护建议优先级

> 0.5.2 更新：下面 P0~P2 的条目**已全部完成**（P0 凭据移入钥匙串并清理 URL，
> P1/P2 见 0.3.2 与 0.5.2 修订记录）。剩余动作只有「轮换已泄露过的 token」与
> 「继续补迁移脚本」两项。

| 优先级 | 动作 | 状态 |
|---|---|---|
| P0 | git remote 明文 token → 钥匙串 + 清理 URL；**轮换已泄露 token** | 已迁移，轮换待人工 |
| P1 | `update --sewage-price` / `--month` 静默失效 | ✅ 0.3.2 |
| P1 | SQLite / MySQL `families` 唯一约束统一 + 迁移脚本 | ✅ 0.3.2 |
| P2 | CLI 补齐档位参数 | ✅ 0.3.2 |
| P2 | `get_backend()` 读 `db_config.json.backend` | ✅ 0.5.2 |
| P3 | `__ERR__` 死分支、`register_user` 异常分类 | ✅ 0.5.2 |
| P3 | `_mysql_sql` 字面量保护（`LIKE '%?%'` 隐患） | ✅ 0.5.2 |
| P3 | 继续补 `db/migrations/` 迁移脚本（当前 2 个） | 进行中（随 schema 变更追加） |

---

## 11. 版本演进脉络

| 版本 | 日期 | 内容 |
|---|---|---|
| 0.1.0 | 2026-10-24 | 首次开源化：设计文档、建表语句、脱敏源码、技能模板、双语 README |
| 0.2.0 | 2026-10-24 | 多用户改造：users 表启用、user_id 隔离、注册/登录/退出、Bearer Token、迁移脚本 |
| 0.3.0 | 2026-10-24 | 双后端（db_backend 方言抽象）、MySQL schema、源码/运行目录分离、launchd/nginx 部署 |
| 0.3.1 | 2026-10-24 | MySQL 全量迁移、幂等自动建表、deploy.sh 一键部署、API 文档 |
| 0.3.2 | 2026-10-24 | 15 项缺陷修复（id 跨表冲突、路径穿越、Content-Length、XSS、外键、backlog…） |
| 0.4.0 | 2026-10-24 | MCP Streamable HTTP `/mcp`（与前端同端口）+ 家庭共享 |
| 0.4.1 | 2026-10-24 | e2e 回归脚本 + 部署链路修复 + MCP 健壮性 + API Key 自动签发 |
| 0.5.0 | 2026-10-24 | 网页上传账单自动识别（bill_parser + /api/bills/upload） |
| 0.5.1 | 2026-10-24 | 跨平台部署 deploy.py（macOS/Linux/Windows）+ UL_AUTH_PORT |
| 0.5.2 | 2026-10-25 | 已知问题清零 + 文档收敛进 README + 凭据入钥匙串 |

**后续规划**见 README「路线图」：网页内编辑/删除账单、解析自学习、提醒与预算、
同比/环比图表、导出、移动端打磨、多实例聚合、本地 OCR、PWA、国际化。

---

*走读范围：全部源码文件（1900+ 行）、双 schema、git 历史、launchd 与 nginx 部署配置、运行态 DB 数据、HTTP 端到端链路。*
*所有问题均经实测复现；测试产物已清理，工作区保持干净。*

---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 5c462fda08d022c3bf06f0c7c13f492d_f7f50b97cfad11f19f8752540064ee0f
    ReservedCode1: TSARLnT1WnB5R9vWTXA3d453By9vg/nL2eR4Up82DOG/8jJX/nJ79kRygk6fVeNXU+Rp64HE8wZRwCx674pZEtskHTABJtN745D/CBr3fewIYdcq8SRzgLzS8OTc7o/6l3gT5lYyMxKFB/jpuuypXvfxU5SdeWdI9AYdDSGLGulLMnaSA9GVNpsY4ZY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 5c462fda08d022c3bf06f0c7c13f492d_f7f50b97cfad11f19f8752540064ee0f
    ReservedCode2: TSARLnT1WnB5R9vWTXA3d453By9vg/nL2eR4Up82DOG/8jJX/nJ79kRygk6fVeNXU+Rp64HE8wZRwCx674pZEtskHTABJtN745D/CBr3fewIYdcq8SRzgLzS8OTc7o/6l3gT5lYyMxKFB/jpuuypXvfxU5SdeWdI9AYdDSGLGulLMnaSA9GVNpsY4ZY=
---

# UtilityLog 设计文档（DESIGN.md）

> 版本：0.4.1（2026-10-24）
> 目标读者：开发者 / AI 客户端（Codex、WorkBuddy 等）——任何需要理解本项目结构、意图或做后续修复改造的角色。
> 本文档与 `db/schema.sql`、`db/schema.mysql.sql`、`CHANGELOG.md` 同步维护；代码实现偏离本文档时必须更新文档。

---

## 1. 项目概述

UtilityLog 是一个**家庭水电气账单记录与展示系统**：用户把每月水费、电费、燃气费账单（截图 / PDF / 文字）交给 AI 助手，AI 解析字段后写入本地数据库（SQLite 默认，可切换 MySQL），再同步到静态网页（nginx 托管）供随时查看，并可选同步腾讯文档在线表格。

### 1.1 当前架构（0.3 双后端 + 目录分离）

```
用户注册/登录（users 表，password_hash 存库）
        │  Cookie / Bearer Token / Basic 鉴权
        ▼
  AI 助手 / Skill（utility-bill-recorder）
        │  utility.py add --user <user> --type <water|electric|gas>
        ▼
  存储后端（db_backend.py 抽象，UL_BACKEND 切换）
  ├─ SQLite（默认，data/utility.db）
  └─ MySQL（可选，utilitylog 库 + 专属低权限用户）
  ├─ users（账号，PBKDF2 哈希）
  ├─ families（家庭，user_id 归属）
  ├─ bills_water（水费，user_id 归属）
  ├─ bills_electric（电费，user_id 归属）
  └─ bills_gas（燃气费，user_id 归属）
        │  sync_site.py（导出配置用户数据）
        ▼
  site/data.js ──► nginx 静态站点（site/）
        │               │
        ▼               ▼
  本地 127.0.0.1:8089  公网域名（Cloudflare Tunnel）
        │
  认证网关 auth_server.py（/register、/login、/logout；动态 /data.js）
        ▼
  浏览器访问：每用户只看到本人数据
```

目录分离（0.3 起）：

- **源码仓库** `~/project/UtilityLog`：代码、模板、文档、脱敏示例配置（.git 保留全部历史，仅含公开安全内容）。
- **运行目录** `~/myapp/utilitylog`：数据库、图片、日志、真实配置（auth_config.json / db_config.json / .auth_tokens.json 等），全部 gitignore，不入库。
- 路径由环境变量 `UL_APP_DIR`（或回退 `UL_ROOT` / 仓库根）解析，保持默认值可回退。

### 1.2 演进目标（0.2+，多用户）

- [x] 注册 / 登录，每用户独立账单
- [x] 每用户 API Token（api_tokens 表），供 Skill / 外部程序远程录入
- [x] SQLite 默认 + MySQL 双后端（db_backend.py 抽象，方言兼容）
- [x] 源码 / 运行目录分离（UL_APP_DIR 可配，运行产物与真实配置不入库）
- [ ] 网页手工编辑
- [ ] 设置页配置通用模型 API 与用户模型 Token
- [ ] 配好模型 API 后，网页可直接上传图文记录（图片走 OCR / 多模态解析，文字走 LLM 抽取）
- [ ] Skill 与网页双录入并存

---

## 2. 目录结构（0.3 起：源码 / 运行分离）

```
源码仓库 ~/project/UtilityLog/
├── auth_server.py         认证网关（Cookie 登录校验、/login；0.3 双后端）
├── scripts/
│   ├── utility.py         数据管理 CLI（init/register/add/update/delete/list/dump）
│   ├── sync_site.py       数据库 → site/data.js 导出 + 腾讯文档同步
│   └── db_backend.py      0.3 双后端抽象（SQLite / MySQL，方言转换）
├── site/
│   ├── index.html         主展示页（趋势图/汇总/明细/用能明细）
│   ├── login.html         登录页
│   └── vendor/            echarts.min.js 等前端依赖
├── db/
│   ├── schema.sql         建表语句（SQLite 0.3，users + user_id 隔离）
│   ├── schema.mysql.sql   建表语句（MySQL 0.3，与 SQLite 语义等价）
│   └── migrations/
│       └── migrate_multiuser.py   0.1 → 0.2 迁移（备份 + 建表 + 数据归属 hh）
├── docs/
│   ├── DESIGN.md          本文档
│   ├── INSTALL.md         安装部署指南（传统命令 + AI 客户端 + MySQL）
│   └── AI_AGENTS.md       AI 客户端（Codex/WorkBuddy）指令安装说明
├── auth_config.example.json  凭据配置模板（真实 auth_config.json 放运行目录）
├── db_config.example.json    MySQL 连接配置模板（真实 db_config.json 放运行目录）
├── README.md              中英文双语说明
├── CHANGELOG.md           修订记录
├── LICENSE                MIT
└── .gitignore             排除本地私有数据

运行目录 ~/myapp/utilitylog/（不入库）
├── data/utility.db        SQLite 数据库（UL_BACKEND=sqlite 时）
├── db_config.json         MySQL 连接配置（UL_BACKEND=mysql 时，gitignore）
├── auth_config.json       初始账号配置（gitignore）
├── .auth_tokens.json      令牌令牌兜底存储（gitignore）
├── images/                账单截图按 YYYY-MM 归档（gitignore）
├── site/data.js           站点数据导出（gitignore）
├── .htpasswd / auth_server.log / temp*  运行产物（gitignore）
```

> `site/` 静态模板始终来自源码仓库；`site/images` 软链到运行目录 `images/`。
> 路径解析优先级：`UL_APP_DIR` > `UL_ROOT` > 仓库根（`Path(__file__).resolve().parent.parent`）。

---

## 3. 数据模型（表结构）

### 3.1 核心设计原则（用户强调，必须遵守）

1. **按费种拆表**：水/电/气各自独立表（`bills_water` / `bills_electric` / `bills_gas`），禁止回退单宽表。原因：三类账单字段差异大（电费有峰谷八列、水费有分项费、燃气简单），拆表消除无关 NULL。
2. **同家庭同月份同类型唯一**：`UNIQUE(family_id, bill_month)`，重复录入走 upsert 覆盖，不产生重复行。
3. **总价 = 分项之和**：
   - 水费：`amount = water_fee（水费金额）+ sewage_fee（污水处理费金额）`
   - 电费：`amount = peak_usage×peak_price + valley_usage×valley_price`
   - 燃气：`amount = usage×unit_price`
   - 年度趋势图只画总价单柱；分项在月度明细表与用能明细堆叠柱中展示。
4. **电费峰谷四示数独立**：`peak_prev_reading / peak_cur_reading / valley_prev_reading / valley_cur_reading` 必须分列保存，禁止合并。
5. **阶梯档位必须记录**：`current_tier / tier_remaining / year_usage / tier_detail(JSON)`，网页与表格都要展示。

### 3.2 表定义

完整 DDL 见 `db/schema.sql`，此处为设计语义说明。

#### families（家庭）

| 列 | 说明 |
|---|---|
| id | 主键 |
| name | 家庭名（用户内唯一），如「我的家」 |
| user_id | 归属用户（0.2 起） |
| created_at | 创建时间 |

#### bills_water（水费）

| 列 | 说明 |
|---|---|
| family_id | 归属家庭 |
| user_id | 归属用户（0.2 起） |
| bill_month | 账期 YYYY-MM，与 family_id 联合唯一 |
| usage / usage_unit | 用量（m³） |
| prev_reading / cur_reading | 上期 / 本期读数 |
| water_unit_price | 水费单价（元/m³） |
| sewage_unit_price | 污水单价（元/m³） |
| water_fee | 水费金额 = usage × water_unit_price |
| sewage_fee | 污水费金额 = usage × 0.9 × sewage_unit_price |
| amount | 合计 = water_fee + sewage_fee |
| bill_date / image / note | 账单日期 / 截图 / 备注 |
| current_tier / tier_remaining / year_usage / tier_detail | 档位信息 |

#### bills_electric（电费）

| 列 | 说明 |
|---|---|
| family_id / bill_month | 归属 + 账期（唯一） |
| user_id | 归属用户（0.2 起） |
| usage / usage_unit | 总用量（kWh） |
| prev_reading / cur_reading | 综合上期 / 本期读数 |
| peak_prev_reading / peak_cur_reading | 峰上期 / 峰本期示数 |
| valley_prev_reading / valley_cur_reading | 谷上期 / 谷本期示数 |
| peak_usage / peak_price | 峰电量 / 峰单价 |
| valley_usage / valley_price | 谷电量 / 谷单价 |
| unit_price | 综合 / 平均单价 |
| amount | 费用合计 = 峰电费 + 谷电费 |
| 其余 | 同 bills_water |

#### bills_gas（燃气费）

| 列 | 说明 |
|---|---|
| family_id / bill_month | 归属 + 账期（唯一） |
| user_id | 归属用户（0.2 起） |
| usage / usage_unit | 用量（m³） |
| prev_reading / cur_reading | 上期 / 本期读数 |
| unit_price | 单价（元/m³） |
| amount | 费用 = usage × unit_price |
| 其余 | 同 bills_water |

#### 多用户表（0.2 起启用）

- `users`：多用户账号（username / password_hash(PBKDF2) / display_name / is_active）
- `api_tokens`：会话 Cookie 与 API Token（token / user_id / scope / expires_at / last_used）
- `user_settings`：模型 API 配置（model_api_base / model_api_key / model_name）
- 隔离：`families` 与 `bills_*` 均带 `user_id`，所有查询强制按用户过滤

#### 3.2.1 字段 / 类型 / 外键 / 索引明细

> 以 `db/schema.sql`（SQLite）为基准；`db/schema.mysql.sql`（MySQL）语义等价：
> `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGINT NOT NULL AUTO_INCREMENT`，`TEXT` → `VARCHAR(n)` / `TEXT`，
> `REAL` → `DOUBLE`，`datetime('now','localtime')` → `NOW()`，唯一约束转 `UNIQUE KEY`。
> MySQL 版为保持部署灵活**未声明 FOREIGN KEY 约束**（逻辑外键由应用层保证），SQLite 版在 DDL 中声明 `REFERENCES`。

**users（用户账号）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，AUTOINCREMENT / AUTO_INCREMENT |
| username | TEXT | VARCHAR(64) | NOT NULL，UNIQUE（uq_users_username） |
| password_hash | TEXT | VARCHAR(512) | NOT NULL，PBKDF2-SHA256（120000 迭代） |
| display_name | TEXT | VARCHAR(128) | 可空，默认同 username |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |
| is_active | INTEGER | TINYINT | NOT NULL DEFAULT 1 |

**families（家庭）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，自增 |
| name | TEXT | VARCHAR(255) | NOT NULL；两后端统一 `UNIQUE(user_id, name)`（uq_families_user_name）——0.3.2 修正 SQLite 原全局 UNIQUE |
| user_id | INTEGER | BIGINT | 逻辑外键 → users(id)（SQLite DDL 声明 REFERENCES） |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |

**bills_water（水费）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，自增 |
| family_id | INTEGER | BIGINT | NOT NULL，外键 → families(id)；UNIQUE(family_id, bill_month)（uq_bills_water_family_month） |
| user_id | INTEGER | BIGINT | 逻辑外键 → users(id) |
| bill_month | TEXT | VARCHAR(7) | NOT NULL，YYYY-MM，与 family_id 联合唯一 |
| usage | REAL | DOUBLE | MySQL 保留字，建表时反引号 `` `usage` `` |
| usage_unit | TEXT | VARCHAR(16) | DEFAULT 'm³' |
| prev_reading / cur_reading | REAL | DOUBLE | 上期 / 本期读数 |
| water_unit_price | REAL | DOUBLE | 水费单价（元/m³） |
| sewage_unit_price | REAL | DOUBLE | 污水单价（元/m³） |
| water_fee / sewage_fee | REAL | DOUBLE | 水费金额 / 污水处理费金额 |
| amount | REAL | DOUBLE | 合计 = water_fee + sewage_fee |
| bill_date | TEXT | VARCHAR(16) | YYYY-MM-DD |
| image | TEXT | VARCHAR(512) | 截图相对路径 |
| note | TEXT | TEXT | 备注 |
| current_tier | TEXT | VARCHAR(32) | 当前阶梯档位 |
| tier_remaining / year_usage | REAL | DOUBLE | 本档剩余量 / 年累计用量 |
| tier_detail | TEXT | TEXT | JSON 档位明细 |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |

**bills_electric（电费，峰谷四示数独立）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，自增 |
| family_id | INTEGER | BIGINT | NOT NULL，外键 → families(id)；UNIQUE(family_id, bill_month)（uq_bills_electric_family_month） |
| user_id | INTEGER | BIGINT | 逻辑外键 → users(id) |
| bill_month | TEXT | VARCHAR(7) | NOT NULL，YYYY-MM，与 family_id 联合唯一 |
| usage / usage_unit | REAL | DOUBLE | 总用量（kWh），DEFAULT 'kWh' |
| prev_reading / cur_reading | REAL | DOUBLE | 综合上期 / 本期示数 |
| unit_price | REAL | DOUBLE | 综合 / 平均单价（元/kWh） |
| peak_prev_reading / peak_cur_reading | REAL | DOUBLE | 峰上期 / 峰本期示数 |
| valley_prev_reading / valley_cur_reading | REAL | DOUBLE | 谷上期 / 谷本期示数 |
| peak_usage / peak_price | REAL | DOUBLE | 峰电量 / 峰单价 |
| valley_usage / valley_price | REAL | DOUBLE | 谷电量 / 谷单价 |
| amount | REAL | DOUBLE | 合计 = peak_usage×peak_price + valley_usage×valley_price |
| bill_date / image / note | TEXT | VARCHAR/TEXT | 同 bills_water |
| current_tier / tier_remaining / year_usage / tier_detail | TEXT/REAL | VARCHAR/DOUBLE/TEXT | 同 bills_water |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |

**bills_gas（燃气费）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，自增 |
| family_id | INTEGER | BIGINT | NOT NULL，外键 → families(id)；UNIQUE(family_id, bill_month)（uq_bills_gas_family_month） |
| user_id | INTEGER | BIGINT | 逻辑外键 → users(id) |
| bill_month | TEXT | VARCHAR(7) | NOT NULL，YYYY-MM，与 family_id 联合唯一 |
| usage / usage_unit | REAL | DOUBLE | 用量（m³），DEFAULT 'm³' |
| prev_reading / cur_reading | REAL | DOUBLE | 上期 / 本期读数 |
| unit_price | REAL | DOUBLE | 单价（元/m³） |
| amount | REAL | DOUBLE | 费用 = usage × unit_price |
| bill_date / image / note | TEXT | VARCHAR/TEXT | 同 bills_water |
| current_tier / tier_remaining / year_usage / tier_detail | TEXT/REAL | VARCHAR/DOUBLE/TEXT | 同 bills_water |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |

**api_tokens（会话 / API Token）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| id | INTEGER | BIGINT | PRIMARY KEY，自增 |
| user_id | INTEGER | BIGINT | NOT NULL，外键 → users(id) |
| token | TEXT | VARCHAR(255) | NOT NULL，UNIQUE（uq_api_tokens_token），secrets.token_urlsafe(32) |
| scope | TEXT | VARCHAR(32) | NOT NULL DEFAULT 'bill:write' |
| expires_at | TEXT | VARCHAR(32) | 过期时间，NULL 永不过期 |
| created_at | TEXT | DATETIME | NOT NULL DEFAULT 当前时间 |
| last_used | TEXT | VARCHAR(32) | 最近使用时间 |

**user_settings（用户设置）**

| 列 | SQLite | MySQL | 约束 / 外键 / 索引 |
|---|---|---|---|
| user_id | INTEGER | BIGINT | PRIMARY KEY，外键 → users(id) |
| model_api_base | TEXT | VARCHAR(512) | 通用模型 API 地址 |
| model_api_key | TEXT | TEXT | 模型 Token（规划加密存储） |
| model_name | TEXT | VARCHAR(128) | 模型名称 |
| theme | TEXT | VARCHAR(16) | DEFAULT 'light' |
| updated_at | TEXT | VARCHAR(32) | 更新时间 |

索引 / 唯一键汇总：

| 表 | 索引 / 唯一键 |
|---|---|
| users | UNIQUE(username) |
| families | UNIQUE(user_id, name)（SQLite 为 name 全局 UNIQUE） |
| bills_water | UNIQUE(family_id, bill_month) |
| bills_electric | UNIQUE(family_id, bill_month) |
| bills_gas | UNIQUE(family_id, bill_month) |
| api_tokens | UNIQUE(token) |
| user_settings | PRIMARY KEY(user_id) |

---

## 4. 程序逻辑设计

### 4.1 scripts/utility.py（数据管理 CLI）

职责：**唯一的数据写入/读取入口**。网页与 Skill 都不直接碰数据库。

```
命令一览：
  init                     建库建表（含 users 等）
  register <username> <pass> [display_name]   注册用户（PBKDF2 哈希）
  list-users                列出用户
  add-family <name>        新增家庭（归属 --user）
  add --user <user> --family --month --type --usage --amount [--prev-reading --cur-reading
      --unit-price --water-unit-price --sewage-unit-price --peak-usage --peak-price
      --valley-usage --valley-price --water-fee --sewage-fee --bill-date --image --note ...]
  update --user <user> <id> [--字段...]  修改（type 不可改，按表路由）
  delete --user <user> <id>              删除（自动定位所在表）
  list [--user --family --month --type]   查询（JSON 输出）
  dump [--user]                按用户全量导出（三表 UNION 统一投影 + user 信息）
```

关键实现：

1. **按 type 路由**：`TABLE_BY_TYPE = {water: bills_water, electric: bills_electric, gas: bills_gas}`；`add` 用 `INSERT ... ON CONFLICT(family_id, bill_month) DO UPDATE` 实现 upsert。
2. **update/delete 自动定位表**：`find_bill_table(bid)` 依次在三张表按 id 查找，确定所属表后操作；`type` 字段不可修改（账单按表路由）。
3. **三表 UNION 统一投影**：`UNION_COLS` 把三张表投影为同一列集（非本表字段为 NULL），前端 / sync_site 无需感知拆表细节；兼容旧字段别名 `sewage_price`。
4. **档位 JSON**：`tier_detail` 存 JSON 字符串，写入时 `json.dumps`，读取时原样输出。
5. **用户隔离（0.2）**：所有查询/写入强制带 `user_id`（由 `--user` 解析）；家庭名只在同一用户内唯一；`list/update/delete` 找不到他人数据时如实报错；`DEFAULT_USER` 读取 `UL_USER` 或 `auth_config.json`，未配置则必须显式传 `--user`。
6. **路径解析（0.3 目录分离）**：运行目录由 `UL_APP_DIR` > `UL_ROOT` > 仓库根（`Path(__file__).resolve().parent.parent`）推导；数据库默认 `{运行目录}/data/utility.db`（SQLite）或读 `{运行目录}/db_config.json`（MySQL），详见 INSTALL.md。
7. **双后端（0.3）**：`db_backend.py` 提供 `get_conn()` / `get_backend()`，后端由环境变量 `UL_BACKEND`（sqlite|mysql）选择，缺省读运行目录 `db_config.json` 的 `backend` 字段，再缺省为 `sqlite`；SQL 方言差异（upsert / 自增 / 时间函数 / 占位符 / 类型）在 `db_backend._mysql_sql()` 中统一改写，业务 SQL 保持 SQLite 方言书写。
8. **缺项不编造**：CLI 只写用户/解析出的字段，缺失留 NULL；上游解析层（Skill）负责提示缺失。

### 4.2 scripts/sync_site.py（站点同步 + 腾讯文档）

职责：把数据库当前状态导出为 `site/data.js`（`window.UTILITY_DATA = {...}`），并为 `index.html` 中的 data.js 引用追加版本号（`?v=v<timestamp>`）规避浏览器缓存；随后可选覆盖式同步腾讯文档表格。

```
流程（0.2：导出指定用户数据）：
  dump_json(user) 读取该用户 families + bills（三表 UNION）
  → 写 site/data.js（window.UTILITY_DATA = {user, families, bills}）
  → 更新 index.html 中 <script src="data.js?v=..."> 的版本戳
  → 若配置了腾讯文档凭据（0.2 起可禁用），按键（家庭+月份+类型）覆盖式写入
```

用户来源（优先级从高到低）：环境变量 `UL_SYNC_USER` > `DEFAULT_USER`（`UL_USER` 或 `auth_config.json`）。

腾讯文档同步要点：
- 覆盖式更新：`get_cell_data` 读全表定位键行，`set_range_value` 覆盖该行全部 27 列；未找到则写首个空行。
- 大表分批：每批 ≤9 行或 ≤180 cells。
- 表头 27 列：家庭/月份/类型/上次读数/本次读数/用量/单位/综合单价/峰上期/峰本期/谷上期/谷本期/峰电量/峰单价/谷电量/谷单价/污水单价/当前档位/本档剩余/年累计/档位明细/费用/账单日期/截图/备注/水费金额/污水费金额。

### 4.3 auth_server.py（认证网关）

职责：对 `site/` 静态资源做多用户鉴权，并为前端动态导出当前登录用户数据。

```
监听 127.0.0.1:8099（nginx 反代，公网经 Cloudflare Tunnel）
/register：POST user/pass[/display_name] → 创建用户（PBKDF2 哈希入库）并自动登录
/login：POST user/pass → 校验 users 表，通过签发 180 天 HttpOnly Cookie（ul_token）
/logout：清除 Cookie 并吊销对应 token
API 鉴权（三选一，按序）：
  1. Cookie（ul_token → api_tokens 表关联 user_id）
  2. Authorization: Bearer <token>（api_tokens 表）
  3. Authorization: Basic base64(user:pass)（兼容旧脚本）
/data.js：动态按当前用户导出（不再依赖手工 sync）
静态文件：未登录 → 返回 login.html 或 401；已登录 → 正常服务
/mcp：POST MCP Streamable HTTP 端点（0.4.1 起，JSON-RPC 2.0）。
  复用 scripts/mcp_server.py 的 10 个工具与鉴权三通道，与前端共用 nginx :8089
  端口；已认证用户强制覆盖工具参数 user，HTTP 通道无法冒充他人。
```

0.1 开源化要点：
- **凭据不再硬编码**：改为环境变量 `UL_USER` / `UL_PASS` 或配置文件 `auth_config.json`（模板见 `auth_config.example.json`，真实配置放运行目录，不入库）。
- 0.2 起凭据仅用于**创建/校验初始账号 hh**；用户注册/登录走 `users` 表。
- 0.3 起连接层走 `db_backend`：默认 SQLite；`UL_BACKEND=mysql` 时读取运行目录 `db_config.json`（host/port/user/password/db），建库/建表/令牌校验均兼容。

### 4.4 0.3 双后端抽象（scripts/db_backend.py，已实现）

```
get_backend()          → 'sqlite' | 'mysql'（UL_BACKEND > db_config.json.backend > sqlite）
get_conn()             → SQLite 连接（row_factory=Row）或 pymysql 连接（DictCursor）
_mysql_sql(sql, params)→ MySQL 方言改写：
                          INSERT ... ON CONFLICT DO UPDATE → ON DUPLICATE KEY UPDATE
                          datetime('now','localtime')      → NOW()
                          ? 占位符                        → %s
                          AUTOINCREMENT 自增              → AUTO_INCREMENT
                          INTEGER PRIMARY KEY              → BIGINT AUTO_INCREMENT（部分建表）
保留字保护：MySQL 保留字（usage 等）自动加反引号，已反引号的不重复处理
```

业务模块统一 `import db_backend` 后只写 SQLite 方言 SQL，由 `_mysql_sql()` 在执行前转换；验证过：MySQL 下 init/注册/登录/数据隔离/增删改查/权限隔离（专属用户跨库访问被拒）全部通过。

### 4.5 0.2 多用户逻辑（已实现）

```
注册/登录（users 表 + password_hash）
  → 登录签发会话 Cookie（api_tokens 持久化，绑定 user_id）
  → 同时支持 Bearer Token / Basic 认证
每用户隔离：bills_*/families 带 user_id，所有查询强制带 user_id
数据导出：auth_server 动态 /data.js + sync_site.py 按用户导出
设置页：用户配置通用模型 API base + key + model（存 user_settings，key 加密）【规划】
网页上传录入：配好模型 API 后，POST 图片 → 服务端调模型 OCR/多模态解析
  → 结构化字段 → utility.py add；纯文字走 LLM 抽取【规划】
Skill 录入：用户 token 调同一 API 入口，等价于网页录入【规划】
```

---

## 5. 展示设计

### 5.1 页面结构（site/index.html）

```
┌────────────────────────────────────────────┐
│ 标题：家庭水电气账单    [欢迎，用户名] [退出]│
├────────────────────────────────────────────┤
│ 年度趋势（总价单柱折线图，水/电/气三柱）     │
├────────────────────────────────────────────┤
│ 用能明细（Tabs：水/电/气 + 年份）           │
│   ├ 月度费用堆叠柱（分项分色 + 用量折线）   │
│   └ 阶梯收费进度条（绿/黄/粉三段 + 档位卡） │
├────────────────────────────────────────────┤
│ 当年汇总（分费种合计）                      │
├────────────────────────────────────────────┤
│ 月度明细（三张独立表，按费种分列）          │
│   ├ 水费表：用量/水费金额/污水费金额/合计   │
│   ├ 电费表：峰谷四示数/峰谷电量/峰谷单价    │
│   └ 燃气表：读数/用量/单价/费用             │
└────────────────────────────────────────────┘
```

### 5.2 关键展示规则（用户强调）

1. **月度明细分项独立展示**：水/电/气三张独立表，禁止跨类型混排。水费表含「水费金额 + 污水费金额」两列；电费表峰谷四列独立展示。
2. **年度趋势单柱总价**：水费柱 = amount（水费金额+污水费金额），电费柱 = amount（峰+谷），燃气柱 = amount；tooltip 只显示总价。
3. **用能明细区块**：
   - 顶部 Tabs（水/电/气）+ 年份选择；
   - 月度费用按分项堆叠（水=水费段+污水费段；电=峰段+谷段；气=单段），柱顶标总价，叠加用量折线（第二 Y 轴）；
   - 底部阶梯进度条：绿/黄/粉三档（第三档取 25% 宽度示意），分界刻度显示阈值（水 220/300、电 3120/4800、气 310/520），指针定位当年累计用量，信息卡显示当前档位、年累计、本档上限、本档剩余、各档单价。
4. **档位展示**：每类账单的当前档位与本档剩余都要在网页展示。
5. **数据来源**：`window.UTILITY_DATA`（data.js）；`images/${b.image}` 相对路径加载截图。

### 5.3 登录页（site/login.html）

极简卡片式；POST /login；错误提示通过 `?err` 参数；凭据仅存本机 Cookie，180 天免登录。
0.2 起：同页提供**注册表单**（用户名 / 密码 / 显示名称），POST /register 成功后自动登录；注册失败通过 `?err=2&msg=...` 回显。

### 5.4 0.2 展示（已实现）

- 头部用户栏：显示当前登录用户名（`DATA.user.display_name || username`）与退出按钮（POST /logout）
- 数据完全按登录用户隔离：`data.js` 由 auth_server 按当前用户动态导出

---

## 6. 认证与安全

| 项 | 现状（0.3） | 规划（0.4+） |
|---|---|---|
| 存储 | SQLite 默认 / MySQL 可选（专属低权限用户，仅本库权限） | 同左 + 连接池 |
| 登录 | users 表 + PBKDF2 哈希，注册/登录 | 同左 + 可选过期策略 |
| 会话 | 180 天 HttpOnly Cookie（api_tokens 持久化） | 同左 + 刷新/吊销 |
| API | Bearer Token（api_tokens 表，每用户独立） | scope 细化 |
| 密钥 | 环境变量/配置文件（初始 hh）；MySQL root 仅建库授权用，不入库不落盘 | 同左 |
| 静态站 | nginx 反代 + Tunnel | 同左 |
| 私有数据 | .gitignore 全排除（真实配置/库/日志均放运行目录） | 同左 |

---

## 7. 修订记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 0.4.1 | 2026-10-24 | **MCP Streamable HTTP 端点**：`POST /mcp` 挂入 auth_server，复用 `scripts/mcp_server.py` 工具层与三通道鉴权，与前端共用 nginx `:8089` 端口（域名只需转发一个端口）；HTTP 通道强制以已认证用户执行（`threading.local` 请求上下文覆盖工具参数 `user`），杜绝冒充；支持 JSON-RPC batch 与纯通知 202；stdio 本地传输保持不变（stdout 重定向从模块级移入 stdio main，消除被 import 时的副作用）；`deploy.sh verify` 增加 `/mcp` 未鉴权 401 检查（直连 + nginx 反代） |
| 0.3.2 | 2026-10-24 | 缺陷修复批次（详见 `docs/KNOWN_ISSUES.md`）：**id 跨表冲突**（三表 AUTOINCREMENT 空间独立，`delete/update <id>` 会误伤其他费种 → 改为多表命中时报错并要求 `--type` 消歧）；**update 静默失效**（`--sewage-price` / `--month` 别名转换条件恒不成立 → 改为值判空回退，`bill_month` 纳入可写白名单）；**CLI 补齐档位参数**（`--current-tier` / `--tier-remaining` / `--year-usage` / `--tier-detail`，打通 SKILL.md「分档必录」强制要求）；**tier_detail 序列化对称**（add/update 统一 `_norm_tier_detail`，前端 JSON.parse 补 try/catch）；**families 唯一约束对齐**（SQLite 改 `UNIQUE(user_id, name)` + 迁移脚本 `db/migrations/migrate_families_unique.py`）；**路径穿越修复**（`serve_static` 改用 `os.path.commonpath` 边界判断，替代可被 `site_backup/` 绕过的 `startswith`）；**Content-Length 校验**（负数/超长/非法一律 400/413 并关闭连接，消除线程阻塞与请求走私）；**is_active 全通道生效**（Basic 与 Token 通道补校验，停用账号立即失效）；**前端 XSS 防护**（新增 `esc()`，家庭名/档位/月份/截图路径/档位明细/tooltip 全面转义）；**SQLite 外键生效**（`PRAGMA foreign_keys=ON` 逐连接开启 + WAL）；**并发 backlog**（`request_queue_size=128`，80 并发实测全通）；**schema 检测缓存**（免去每连接一次 SHOW TABLES）；**备注列上网页**（note 此前只落库不展示） |
| 0.3.1 | 2026-10-24 | 数据迁移 MySQL（7 表全量）、连接后幂等自动建表、`scripts/deploy.sh` 一键 install/upgrade、`docs/API.md` 接口文档 |
| 0.3.0 | 2026-10-24 | 双后端：db_backend.py 抽象 SQLite/MySQL 方言（upsert/自增/时间函数/占位符/保留字）；schema.mysql.sql；db_config.example.json；目录分离：源码迁 project/UtilityLog、运行产物迁 myapp/utilitylog、UL_APP_DIR 可配；launchd/nginx 本地部署；MySQL 端到端验证与权限隔离 |
| 0.2.0 | 2026-10-24 | 多用户改造：users 表启用、families/bills_* 增加 user_id、历史数据迁移至 hh、auth_server 注册/登录/退出 + Bearer Token、utility.py 按用户隔离（--user）、sync_site 按用户导出、前端用户名显示与退出、文档同步 |
| 0.1.0 | 2026-10-24 | 首次开源化：设计文档、建表语句、脱敏源码、技能模板、双语 README、安装指南、CHANGELOG |

> 修订规则：每次代码变更后同步更新本文档对应章节与 `db/schema.sql` / `db/schema.mysql.sql`；版本号按 Keep a Changelog + 语义化版本推进。
*（内容由AI生成，仅供参考）*

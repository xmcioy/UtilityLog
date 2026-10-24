# UtilityLog

家庭水电气账单一站式记录与管理工具（多家庭 · 多费种 · 网页展示 · AI 技能双录入）

UtilityLog is a self-hosted utility bill (water / electricity / gas) tracker for multiple households, with a password-protected web dashboard, a CLI data manager, and a Marvis-style AI skill for image/PDF bill entry.

> 中文 README 见 [README.zh-CN.md](README.zh-CN.md) · English README: this file

## Features

- **多家庭独立账单**：`families` + 三张费种表（bills_water / bills_electric / bills_gas），互不干扰
- **按费种拆表**：水费含"水费金额 + 污水费金额"分项，电费含峰谷四读数，燃气独立；每类账单独立明细展示
- **阶梯计费记录**：当前档位、本档剩余、年累计用量、档位明细 JSON
- **密码保护的网页**：Cookie 180 天免登录 + Basic Auth 兼容，nginx 反代，静态站点（ECharts 图表 + 表格）
- **AI 技能录入**：截图 / PDF 账单 → 视觉解析 → 本地 SQLite → 网页同步 → 腾讯文档表格覆盖式同步
- **双后端存储（0.3）**：SQLite 默认零依赖，可切换 MySQL 8+（专属低权限用户，权限隔离）
- **源码 / 运行分离（0.3）**：仓库仅代码 / 模板 / 文档 / 脱敏示例，真实配置与数据落运行目录（UL_APP_DIR），gitignore 不入库
- **一键部署 / 升级（0.3.1）**：`scripts/deploy.sh install|upgrade` 自动完成 MySQL 建库建表、源码同步、launchd 服务配置与验证，数据 / 程序分离，升级保留运行数据与凭据
- **数据三端同步**：本地数据库（source of truth）→ 静态站点 data.js → 腾讯文档在线表格
- **隐私友好**：本地私有数据（数据库、截图、token、配置）全部 gitignore，开源仓库零敏感信息

## Repository layout (0.3: source / runtime separated)

```
UtilityLog/                        # source repo (public-safe only)
├── auth_server.py                 # auth gateway (login/register/logout, dual backend)
├── auth_config.example.json       # credential template (real config lives in runtime dir)
├── db_config.example.json         # MySQL connection template (real config lives in runtime dir)
├── db/
│   ├── schema.sql                 # SQLite DDL (0.3 multi-user)
│   └── schema.mysql.sql           # MySQL DDL (0.3, semantically equivalent)
├── scripts/
│   ├── utility.py                 # CLI: init / register / add-family / add / list / update / delete / dump
│   ├── sync_site.py               # DB → site/data.js + Tencent Docs sync
│   └── db_backend.py              # SQLite / MySQL dialect abstraction (0.3)
├── site/                          # frontend static templates (index.html + vendor/echarts.min.js)
├── skill/
│   └── SKILL.md                   # AI skill (Marvis style), sanitized template
├── docs/
│   ├── DESIGN.md                  # design doc (schema / program logic / display / changelog)
│   ├── INSTALL.md                 # install guide (中文) incl. MySQL deployment
│   └── AI_AGENTS.md               # one-shot prompt for AI coding agents
├── README.md / README.zh-CN.md / CHANGELOG.md / LICENSE

runtime dir (e.g. ~/myapp/utilitylog, gitignored)
├── data/utility.db                # SQLite DB (default backend)
├── db_config.json                 # MySQL connection config (backend=mysql)
├── auth_config.json               # real initial credentials
├── images/  site/data.js  auth_server.log  temp* ...
```

Runtime dir resolution: `UL_APP_DIR` > `UL_ROOT` > source root. Backend: `UL_BACKEND=sqlite|mysql` > `db_config.json` > default `sqlite`.

## Quick start (traditional)

```bash
git clone <repo-url> UtilityLog && cd UtilityLog

# 0. (optional) separate runtime dir for local data/config
export UL_APP_DIR=~/myapp/utilitylog && mkdir -p "$UL_APP_DIR"

# 1. 初始化数据库
python3 scripts/utility.py init
python3 scripts/utility.py --user <user> register <user> <pass>   # 注册用户（0.2+ 多用户）
python3 scripts/utility.py --user <user> add-family 我的家

# 2. 配置认证凭据（环境变量或配置文件）
cp auth_config.example.json "$UL_APP_DIR/auth_config.json"
# 编辑 auth_config.json 填写 user / pass

# 3. 启动认证网关（监听 127.0.0.1:8099）
python3 auth_server.py

# 4. 录入账单
python3 scripts/utility.py --user <user> add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5

# 5. 同步网页数据（可选，0.3 起网关 /data.js 动态导出）
python3 scripts/sync_site.py

# 6. nginx 反代：将你的域名/端口反代到 127.0.0.1:8099（详见 docs/INSTALL.md）
```

MySQL backend: create DB + dedicated low-priv user, write `db_config.json` into runtime dir, then `UL_BACKEND=mysql python3 scripts/utility.py init`. See [docs/INSTALL.md](docs/INSTALL.md) §2.5.

Full commands and nginx config: [docs/INSTALL.md](docs/INSTALL.md) (中文) / [docs/INSTALL.en.md](docs/INSTALL.en.md) (English, optional).

## One-shot deploy / upgrade (recommended)

```bash
bash scripts/deploy.sh install    # first run: create DB → sync source to runtime dir → configure launchd → start & verify
bash scripts/deploy.sh upgrade    # upgrade: git pull → sync → idempotent schema → restart → verify
```

All paths are derived from `$HOME` (no hardcoded usernames). Runtime data and credentials
(`data/` `images/` `temp/` `db_config.json` `auth_config.json` `.auth_tokens.json` `.htpasswd`)
are excluded from the sync — **upgrades replace the program only, your data is untouched**.
The script also creates the `site/images → images/` symlink so bill screenshots are reachable.

## Pre-commit sensitive-data scan

```bash
bash scripts/install_hooks.sh    # install the git pre-commit hook
```

The hook scans staged content before every `git commit` and **blocks the commit** when it
finds local absolute paths, private-domain names, access tokens, API keys or plaintext
passwords — pointing at the exact file and line. `.gitignore` already covers every
runtime-data and credential file.

## Install with an AI coding agent

Copy the one-shot prompt in [docs/AI_AGENTS.md](docs/AI_AGENTS.md) into Codex / Workbuddy / any agentic CLI. The agent will clone, init, configure credentials, start the gateway and sync the site automatically.

## Roadmap

### 0.3 (implemented)
- SQLite 默认 + MySQL 双后端（`db_backend.py` 方言抽象）
- 源码 / 运行目录分离（`UL_APP_DIR` 可配，真实配置与数据不入库）
- MySQL 专属低权限用户 + 权限隔离，schema.mysql.sql / db_config.example.json
- launchd / nginx 本地部署

### 0.4 (planned)
- 网页手工编辑账单
- 设置页配置通用模型 API 与用户模型 token
- 配 API 后网页直接上传图文记录
- skill 与网页双录入均支持

Schema for these tables is already planned in [db/schema.sql](db/schema.sql) (see migration comments), [db/schema.mysql.sql](db/schema.mysql.sql) and [docs/DESIGN.md](docs/DESIGN.md).

## Tech stack

Python 3 (stdlib only, no pip dependencies; optional pymysql for MySQL) · SQLite / MySQL 8+ · HTML/JS + ECharts · nginx (optional) · Cloudflare Tunnel (optional, for public access)

## License

MIT — see [LICENSE](LICENSE).

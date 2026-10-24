# UtilityLog

家庭水电气账单一站式记录与管理工具（多家庭 · 多费种 · 网页展示 · AI 技能双录入）

English README: [README.md](README.md)

## 功能特性

- **多家庭独立账单**：`families` + 三张费种表（bills_water / bills_electric / bills_gas），互不干扰
- **按费种拆表**：水费含"水费金额 + 污水费金额"分项，电费含峰谷四读数，燃气独立；每类账单独立明细展示
- **阶梯计费记录**：当前档位、本档剩余、年累计用量、档位明细 JSON
- **密码保护的网页**：Cookie 180 天免登录 + Basic Auth 兼容，nginx 反代，静态站点（ECharts 图表 + 表格）
- **AI 技能录入**：截图 / PDF 账单 → 视觉解析 → 本地数据库 → 网页同步 → 腾讯文档表格覆盖式同步
- **双后端存储（0.3）**：SQLite 默认零依赖，可切换 MySQL 8+（专属低权限用户，权限隔离）
- **源码 / 运行分离（0.3）**：仓库仅代码 / 模板 / 文档 / 脱敏示例，真实配置与数据落运行目录（UL_APP_DIR），gitignore 不入库
- **一键部署 / 升级（0.4.1）**：`scripts/deploy.sh install|upgrade` 自动完成 MySQL 建库建表、源码同步、launchd 服务配置与验证，数据 / 程序分离，升级保留运行数据与凭据
- **数据三端同步**：本地数据库（数据源）→ 静态站点 data.js → 腾讯文档在线表格
- **隐私友好**：本地私有数据（数据库、截图、token、配置）全部 gitignore，开源仓库零敏感信息

## 目录结构（0.3：源码 / 运行分离）

```
UtilityLog/                       # 源码仓库（仅公开安全内容）
├── auth_server.py                # 认证网关（登录/注册/登出，双后端）
├── auth_config.example.json      # 凭据模板（真实配置放运行目录）
├── db_config.example.json        # MySQL 连接模板（真实配置放运行目录）
├── db/
│   ├── schema.sql                # SQLite 建表 DDL（0.3 多用户）
│   └── schema.mysql.sql          # MySQL 建表 DDL（0.3，语义等价）
├── scripts/
│   ├── utility.py                # CLI：init / register / add-family / add / list / update / delete / dump
│   ├── sync_site.py              # 数据库 → site/data.js + 腾讯文档同步
│   └── db_backend.py             # SQLite / MySQL 方言抽象（0.3）
├── site/                         # 前端静态模板（index.html + vendor/echarts.min.js）
├── skill/
│   └── SKILL.md                  # AI 技能（Marvis 风格），开源脱敏模板
├── docs/
│   ├── DESIGN.md                 # 设计文档（表结构/程序逻辑/展示设计/修订记录）
│   ├── INSTALL.md                # 安装指南（含 MySQL 部署）
│   └── AI_AGENTS.md              # AI 客户端（Codex / Workbuddy）安装指令
├── README.md / README.zh-CN.md / CHANGELOG.md / LICENSE

运行目录（如 ~/myapp/utilitylog，gitignore 不入库）
├── data/utility.db               # SQLite 库（默认后端）
├── db_config.json                # MySQL 连接配置（backend=mysql 时）
├── auth_config.json              # 真实初始凭据
├── images/  site/data.js  auth_server.log  temp* ...
```

运行目录解析：`UL_APP_DIR` > `UL_ROOT` > 源码根；后端选择：`UL_BACKEND=sqlite|mysql` > `db_config.json` > 默认 `sqlite`。

## 快速开始（传统命令）

```bash
git clone <仓库地址> UtilityLog && cd UtilityLog

# 0.（可选）运行目录与源码分离
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

MySQL 后端：建库 + 专属低权限用户后，把 `db_config.json` 写入运行目录，再 `UL_BACKEND=mysql python3 scripts/utility.py init`，详见 [docs/INSTALL.md](docs/INSTALL.md) §2.5。

完整命令与 nginx 配置见 [docs/INSTALL.md](docs/INSTALL.md)。

## 一键部署 / 升级（推荐）

```bash
bash scripts/deploy.sh install    # 首次：建库建表 → 同步源码到运行目录 → 配置 launchd → 启动验证
bash scripts/deploy.sh upgrade    # 升级：git pull → 同步 → 幂等 schema → 重启 → 验证
```

脚本用 `$HOME` 推导所有路径，不硬编码用户名；运行数据与凭据（`data/` `images/` `temp/`
`db_config.json` `auth_config.json` `.auth_tokens.json` `.htpasswd`）在同步时自动排除，
**升级只替换程序，不触碰你的数据**。同时会创建 `site/images → images/` 软链，
让网页能访问账单截图。

## 提交前敏感信息扫描

```bash
bash scripts/install_hooks.sh    # 安装 git pre-commit hook
```

hook 会在每次 `git commit` 前扫描暂存区，命中本机绝对路径、私域域名、访问令牌、
API 密钥、明文密码等私密内容时**阻止提交**并指出具体位置。
仓库的 `.gitignore` 已覆盖所有运行数据与凭据文件。

## 用 AI 编程客户端安装

把 [docs/AI_AGENTS.md](docs/AI_AGENTS.md) 里的一段话粘贴给 Codex / Workbuddy 等任意 agentic CLI，它会自动完成克隆、初始化、配置凭据、启动网关、同步站点。

## 路线图

### 0.3（已实现）
- SQLite 默认 + MySQL 双后端（`db_backend.py` 方言抽象）
- 源码 / 运行目录分离（`UL_APP_DIR` 可配，真实配置与数据不入库）
- MySQL 专属低权限用户 + 权限隔离，schema.mysql.sql / db_config.example.json
- launchd / nginx 本地部署

### 0.4（规划中）
- 网页手工编辑账单
- 设置页配置通用模型 API 与用户模型 token
- 配 API 后网页直接上传图文记录
- skill 与网页双录入均支持

相关表结构已在 [db/schema.sql](db/schema.sql)（迁移注释）、[db/schema.mysql.sql](db/schema.mysql.sql) 与 [docs/DESIGN.md](docs/DESIGN.md) 中规划。

## 技术栈

Python 3（标准库 + 可选 pymysql）· SQLite / MySQL 8+ · HTML/JS + ECharts · nginx（可选）· Cloudflare Tunnel（可选，公网访问）

## 开源协议

MIT — 见 [LICENSE](LICENSE)。

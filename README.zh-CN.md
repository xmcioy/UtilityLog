# UtilityLog

家庭水电气账单一站式记录与管理工具（多家庭 · 多费种 · 网页展示 · AI 技能双录入）

English README: [README.md](README.md)

## 功能特性

- **多家庭独立账单**：`families` + 三张费种表（bills_water / bills_electric / bills_gas），互不干扰
- **按费种拆表**：水费含"水费金额 + 污水费金额"分项，电费含峰谷四读数，燃气独立；每类账单独立明细展示
- **阶梯计费记录**：当前档位、本档剩余、年累计用量、档位明细 JSON
- **密码保护的网页**：Cookie 180 天免登录 + Basic Auth 兼容，nginx 反代，静态站点（ECharts 图表 + 表格）
- **AI 技能录入**：截图 / PDF 账单 → 视觉解析 → 本地 SQLite → 网页同步 → 腾讯文档表格覆盖式同步
- **数据三端同步**：本地 SQLite（数据源）→ 静态站点 data.js → 腾讯文档在线表格
- **隐私友好**：本地私有数据（数据库、截图、token、配置）全部 gitignore，开源仓库零敏感信息

## 目录结构

```
UtilityLog/
├── auth_server.py            # 认证网关（登录/登出/静态文件）
├── auth_config.example.json  # 凭据配置文件模板（复制为 auth_config.json 并填写）
├── db/
│   └── schema.sql            # 建表 DDL（含 0.2 多用户规划）
├── scripts/
│   ├── utility.py            # CLI：init / add-family / add / list / update / delete / dump
│   └── sync_site.py          # SQLite → site/data.js 并刷新版本号
├── site/                     # 前端静态站点（index.html + vendor/echarts.min.js）
├── skill/
│   └── SKILL.md              # AI 技能（Marvis 风格），开源脱敏模板
├── docs/
│   ├── DESIGN.md             # 设计文档（表结构/程序逻辑/展示设计/修订记录）
│   ├── INSTALL.md            # 传统命令安装指南（中文）
│   └── AI_AGENTS.md          # AI 客户端（Codex / Workbuddy）安装指令
├── README.md / README.zh-CN.md / CHANGELOG.md / LICENSE
```

## 快速开始（传统命令）

```bash
git clone <仓库地址> UtilityLog && cd UtilityLog

# 1. 初始化数据库
python3 scripts/utility.py init
python3 scripts/utility.py add-family 我的家

# 2. 配置认证凭据（环境变量或配置文件）
cp auth_config.example.json auth_config.json
# 编辑 auth_config.json 填写 user / pass

# 3. 启动认证网关（监听 127.0.0.1:8099）
python3 auth_server.py

# 4. 录入账单
python3 scripts/utility.py add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5

# 5. 同步网页数据
python3 scripts/sync_site.py

# 6. nginx 反代：将你的域名/端口反代到 127.0.0.1:8099（详见 docs/INSTALL.md）
```

完整命令与 nginx 配置见 [docs/INSTALL.md](docs/INSTALL.md)。

## 用 AI 编程客户端安装

把 [docs/AI_AGENTS.md](docs/AI_AGENTS.md) 里的一段话粘贴给 Codex / Workbuddy 等任意 agentic CLI，它会自动完成克隆、初始化、配置凭据、启动网关、同步站点。

## 多用户路线图（0.2）

- 注册 / 登录，每用户独立账单
- 用户 token 供 AI skill 调用
- 网页手工编辑账单
- 设置页配置通用模型 API 与用户模型 token
- 配 API 后网页直接上传图文记录
- skill 与网页双录入均支持

相关表结构已在 [db/schema.sql](db/schema.sql)（迁移注释）与 [docs/DESIGN.md](docs/DESIGN.md) 中规划。

## 技术栈

Python 3（仅标准库，零 pip 依赖）· SQLite · HTML/JS + ECharts · nginx（可选）· Cloudflare Tunnel（可选，公网访问）

## 开源协议

MIT — 见 [LICENSE](LICENSE)。

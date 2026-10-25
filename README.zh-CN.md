# UtilityLog

![Version](https://img.shields.io/badge/version-0.5.3-2563eb) ![License](https://img.shields.io/badge/license-MIT-green) ![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab)

家庭水/电/燃气账单自托管记录系统（多家庭 · 多费种）。支持**网页上传账单自动识别**、手工录入、AI 技能（MCP）三种录入方式，统一存入私有数据库并可视化展示。

English README: [README.md](README.md)

## 功能

- 📄 **账单上传自动识别**：首页「＋ 上传账单」，账期、用量、峰谷示数、阶梯档位等字段自动解析，核对后入库；家庭可下拉选择或直接新建；图片账单可配置视觉模型 API 自动识别
- 🏠 **多家庭**：家庭独立账本，家庭共享后成员拥有同等管理权限
- ⚡ **阶梯与分项计费**：水费+污水费分项、峰谷四示数与单价、档位/剩余/年累计全部独立成列，绝不合并
- 🤖 **AI 技能（MCP）**：本地 stdio 与远程 HTTP（`/mcp`，与网页同端口）双传输，Bearer API Key 鉴权
- 🔐 **隐私优先**：密码保护、token 入库、敏感文件永不入库
- 🗄 **双后端**：SQLite 默认零依赖，可切换 MySQL 8+

![架构](docs/images/architecture.svg)

| 账单样例 | 上传识别 → 核对 → 入库 |
|---|---|
| ![账单样例](docs/images/bill-sample-water.png) | 首页「＋ 上传账单」：选择/新建家庭 → 上传 PDF/截图 → 自动解析草稿 → 核对保存 |

## 快速开始

环境要求：Python 3.9+（Windows 用 `python`），默认零 pip 依赖；可选 `pymysql`
（MySQL 后端）与 `pypdf`（账单 PDF 识别）。nginx / Cloudflare Tunnel 仅在需要公网时用到。

### 一键部署（推荐）

```bash
git clone <仓库地址> UtilityLog && cd UtilityLog
# 跨平台（macOS / Linux / Windows）
python3 scripts/deploy.py install     # 同步代码 + 依赖 + 建库 + 启动服务 + 验证
python3 scripts/deploy.py upgrade     # 升级：只换程序，数据与凭据保留
# macOS 也可：bash scripts/deploy.sh install|upgrade（launchd 托管）
```

`deploy.py` 自动选择服务托管方式：launchd（macOS）→ systemd 用户服务（Linux）→
后台进程（Windows / 兜底）。每次升级末尾都会跑端到端回归
（`scripts/e2e_verify.py`，48 项，用临时数据跑完自动清理）——
必须同时看到 **`验证通过 ✅`** 与 **`全部通过 ✅`** 才算可发布。

其它命令：`doctor`（环境体检）、`start` / `stop` / `status` / `verify`、
`--port`（或 `UL_AUTH_PORT`）、`--service auto|launchd|systemd|process|none`、
`--sim windows|linux`（预览其它平台行为）。离线环境设 `UL_SKIP_DEPS=1` 跳过 pip 安装。

### 手动运行

```bash
python3 scripts/utility.py init
python3 auth_server.py          # 监听 127.0.0.1:8099，前面配 nginx 反代
```

凭据配置：复制 `auth_config.example.json` 为 `auth_config.json` 填入 `user` / `pass`，
或导出 `UL_USER` / `UL_PASS`；两者都没有则拒绝所有登录。

### 源码 / 运行分离

程序在 git 仓库里；**数据、凭据、日志在独立的运行目录**（已 gitignore），升级不碰账单：

| 路径 | 内容 |
|---|---|
| `~/project/UtilityLog`（源码仓库） | 代码、模板、文档 |
| `~/myapp/utilitylog`（运行目录） | `data/utility.db`、`db_config.json`、`auth_config.json`、`.auth_tokens.json`、`images/`、`*.log` |

运行目录解析优先级：`UL_APP_DIR` > `UL_ROOT` > 源码根。
后端选择优先级：`UL_BACKEND` > `db_config.json` 的 `backend` 字段 > 默认 `sqlite`。

### MySQL 后端（可选）

```bash
pip install pymysql
```

```sql
CREATE DATABASE utilitylog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ul_app'@'localhost' IDENTIFIED BY '<强随机密码>';
CREATE USER 'ul_app'@'127.0.0.1' IDENTIFIED BY '<强随机密码>';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'localhost';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'127.0.0.1';
FLUSH PRIVILEGES;
```

把 `{ "backend": "mysql", "host": "127.0.0.1", "port": 3306, "user": "ul_app",
"password": "<强随机密码>", "database": "utilitylog" }` 存为
`<运行目录>/db_config.json`（模板见 `db_config.example.json`），然后
`UL_BACKEND=mysql python3 scripts/utility.py init`。

应用账号只拥有本库权限；配置文件只放运行目录，不进 git。

### nginx 反代（公网访问）

```nginx
server {
    listen 80;
    server_name your.domain.com;
    location / {
        proxy_pass http://127.0.0.1:8099;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 60s;
    }
}
```

静态资源、登录、`/mcp` 共用 8099 一个端口，无需额外 location。
注意 `client_max_body_size` 要放得下账单 PDF。

### 录入账单

网页上传：首页「＋ 上传账单」→ 选择/新建家庭 → 上传 → 核对保存。
手工录入（CLI，保留阶梯与分项字段）：

```bash
python3 scripts/utility.py --user <user> add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --prev-reading 100 --cur-reading 112.5 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5 --bill-date 2026-10-08
```

电费另加峰谷四示数（`--peak-prev-reading` / `--peak-cur-reading` /
`--valley-prev-reading` / `--valley-cur-reading`）与峰谷电量电价；燃气加 `--unit-price`。
同家庭同月同类型重复录入按 upsert 覆盖：默认只覆盖本次传入的字段，加 `--replace`
则整单全量覆盖（未传字段清空）。

AI 技能：把 MCP 客户端指向 `utilitylog` 服务（stdio 直接跑
`scripts/mcp_server.py`；HTTP 用 `https://<域名>/mcp` + Bearer API Key）。
API Key 在网页「设置」页重置获得。录入契约见 [skill/SKILL.md](skill/SKILL.md)。

其它 CLI：`register`（`--user <名字> register --password <密码>`）、`list-users`、
`add-family`、`list`、`update`、`delete`、`dump`、`share-family`、`unshare-family`、
`list-members`。`update` / `delete` 在 id 跨表存在时必须带 `--type` 消歧。
网页同步：`python3 scripts/sync_site.py`（网关的 `/data.js` 已按登录用户动态导出）。

## 常见问题

- **登录页打不开 / 401 循环**：确认 `auth_config.json` 或 `UL_USER`/`UL_PASS` 已配置。
- **`curl 127.0.0.1:8099` 返回 502**：环境里的 `HTTP_PROXY` 把本机请求劫走了，
  加 `--noproxy '*'` 再试。
- **服务返回 502** — nginx 在听，但 127.0.0.1:8099 上没有服务进程。
  在 SSH / CI / agent 会话里 `launchctl bootstrap gui/$UID` 会失败（没有 GUI 上下文），
  所以 `deploy.sh` 会改用**守护化后台进程**启动（双 fork + setsid，不会随启动它的
  会话一起被回收）。想让它重启机器后也自动起，在**本机终端**执行一次：
  ```bash
  # 方案 A：launchd（推荐，开机自启 + 崩溃重启）
  launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.<用户名>.utility-auth.plist
  # 方案 B：cron 守护（服务挂了 2 分钟内自动拉起）
  (crontab -l 2>/dev/null | grep -v ensure_service.sh
   echo '*/2 * * * * $HOME/myapp/utilitylog/scripts/ensure_service.sh >> /tmp/ul_watchdog.log 2>&1') | crontab -
  ```
  手动急救：`bash scripts/ensure_service.sh`（服务健康时静默，挂了才拉起）。
  日志：`<运行目录>/auth_server.log`。
- **数据没更新**：网关 `/data.js` 是动态导出，浏览器强刷即可；端口冲突设
  `UL_AUTH_PORT=9099` 重启。
- **远端凭据**：存放在 macOS 钥匙串（`credential.helper=osxkeychain`），
  不内嵌在 remote URL 里。若 token 曾出现在 URL、shell history 或备份中，请轮换。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/API.md](docs/API.md) | HTTP API 与 MCP 端点说明 |
| [docs/DESIGN.md](docs/DESIGN.md) | 架构与表结构设计 |
| [docs/TESTING.md](docs/TESTING.md) | 测试套件与部署验证 |
| [docs/CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md) | 代码走读（维护者向） |
| [skill/SKILL.md](skill/SKILL.md) | AI 技能录入契约（脱敏模板） |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新记录 |

## 协议

MIT — 见 [LICENSE](LICENSE)。

# UtilityLog 安装指南（跨平台 · 传统命令 + MySQL 部署）

## 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| 系统 | macOS / Linux / Windows | 核心代码纯 Python 标准库，三平台一致 |
| Python | 3.9+ | Windows 用 `python`，macOS/Linux 用 `python3` |
| 依赖 | 无（可选 `pymysql`、`pypdf`） | 默认 SQLite 零依赖；MySQL 后端需 pymysql；账单 PDF 识别需 pypdf |
| 可选 | nginx / Cloudflare Tunnel | 公网反代 |

> **跨平台部署脚本**：`python3 scripts/deploy.py`（Windows 用 `python scripts\deploy.py`），
> 见本文第 9 节。`scripts/deploy.sh` 是 macOS（launchd + brew 风格）专用脚本，二者功能等价。

## 0. 目录结构（0.3 起：源码 / 运行分离）

```
源码仓库（git 管理，仅公开安全内容）
├── auth_server.py / scripts/ / site/ / db/ / docs/ ...
├── auth_config.example.json / db_config.example.json   ← 脱敏模板
└── .gitignore

运行目录（本地私有数据，gitignore 不入库）
├── data/utility.db        SQLite 库（默认后端）
├── db_config.json         MySQL 连接配置（后端为 mysql 时）
├── auth_config.json       初始账号配置
├── .auth_tokens.json      令牌兜底存储
├── images/                账单截图
├── site/data.js           站点导出
└── auth_server.log        launchd 服务日志
```

- 路径解析：`UL_APP_DIR`（推荐，指向运行目录）> `UL_ROOT` > 源码根。
- 后端选择：`UL_BACKEND=sqlite|mysql` > `db_config.json` 的 `backend` 字段 > 默认 `sqlite`。

## 1. 获取代码

```bash
git clone <仓库地址> UtilityLog
mv UtilityLog ~/project/UtilityLog        # 源码放 project/（保留 .git）
mkdir -p ~/myapp/utilitylog/{data,images,site,temp}
export UL_APP_DIR=~/myapp/utilitylog       # 运行目录
```

## 2. 初始化数据库

```bash
python3 scripts/utility.py init
python3 scripts/utility.py --user <user> add-family 我的家     # 可添加多个家庭
```

- `init` 自动在运行目录创建 `data/utility.db`（families + bills_water / bills_electric / bills_gas / users / api_tokens / user_settings）
- 也可直接用 `db/schema.sql`（SQLite）或 `db/schema.mysql.sql`（MySQL）的 DDL 手动建库
- MySQL 部署见下文「2.5 使用 MySQL 后端」

## 2.5 使用 MySQL 后端（可选）

```bash
pip install pymysql
```

**a) 建库建专属用户（用 root 一次完成，凭据仅本次使用，勿入库）**

```sql
CREATE DATABASE utilitylog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ul_app'@'localhost' IDENTIFIED BY '<强随机密码>';
CREATE USER 'ul_app'@'127.0.0.1' IDENTIFIED BY '<强随机密码>';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'localhost';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'127.0.0.1';
FLUSH PRIVILEGES;
```

**b) 写入运行目录配置（gitignore，不入库）**

```json
{
  "backend": "mysql",
  "host": "127.0.0.1",
  "port": 9306,
  "user": "ul_app",
  "password": "<强随机密码>",
  "database": "utilitylog"
}
```

保存为 `$UL_APP_DIR/db_config.json`（模板见 `db_config.example.json`）。

**c) 初始化与运行**

```bash
export UL_BACKEND=mysql UL_APP_DIR=~/myapp/utilitylog
python3 scripts/utility.py init          # 按 schema.mysql.sql 语义建表
python3 auth_server.py                   # 网关以 mysql 后端启动
```

> 安全说明：应用用户 `ul_app` 仅有 `utilitylog.*` 权限，跨库访问会被 MySQL 拒绝（1142）；连接配置只放运行目录，不进 git。

## 3. 配置认证凭据（二选一）

**方式 A：配置文件**

```bash
cp auth_config.example.json auth_config.json
# 编辑 auth_config.json：
# {
#   "user": "你的用户名",
#   "pass": "你的密码"
# }
```

**方式 B：环境变量**

```bash
export UL_USER=你的用户名
export UL_PASS=你的密码
```

未配置时服务启动会拒绝所有登录（仅警告）。

## 4. 启动认证网关

```bash
export UL_APP_DIR=~/myapp/utilitylog    # 运行目录（可选，默认源码根）
python3 auth_server.py
# UtilityLog auth gateway (0.3.1, backend=sqlite) listening on 127.0.0.1:8099
```

网关功能：
- `POST /register`（user/pass/display_name）→ 注册并自动登录
- `POST /login`（user/pass 表单）→ 种 180 天 HttpOnly Cookie → 302 到 /
- `POST /logout` → 注销
- 其它请求校验 Cookie / Bearer / Basic Auth，通过则返回 `site/` 静态文件
- 支持环境变量 `UL_APP_DIR`（运行目录）与 `UL_BACKEND`（sqlite|mysql），默认 SQLite + 源码根
- 静态模板固定来自源码 `site/`；数据库 / 配置 / 日志落运行目录

## 5. 录入账单

> 0.2 起所有数据命令必须显式 `--user <用户名>`（每用户数据隔离）。

水费：

```bash
python3 scripts/utility.py --user <user> add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --prev-reading 100 --cur-reading 112.5 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5 \
  --bill-date 2026-10-08
```

电费（峰谷分项）：

```bash
python3 scripts/utility.py --user <user> add --type electric --family 我的家 --month 2026-10 \
  --usage 200 --amount 118.24 \
  --peak-prev-reading 800 --peak-cur-reading 900 \
  --valley-prev-reading 600 --valley-cur-reading 700 \
  --peak-usage 100 --peak-price 0.6170 \
  --valley-usage 100 --valley-price 0.3070 \
  --unit-price 0.5912 \
  --current-tier 第一档 --tier-remaining 2920 --year-usage 200 \
  --bill-date 2026-10-12
```

燃气费：

```bash
python3 scripts/utility.py --user <user> add --type gas --family 我的家 --month 2026-10 \
  --usage 20 --amount 60.00 --unit-price 3.00 \
  --prev-reading 300 --cur-reading 320 \
  --current-tier 第一档 --tier-remaining 290 --year-usage 20 \
  --bill-date 2026-10-15
```

其它命令：

```bash
python3 scripts/utility.py --user <user> register <user> <pass> [display_name]
python3 scripts/utility.py --user <user> list-users
python3 scripts/utility.py --user <user> list --family 我的家 --month 2026-10 --type water
python3 scripts/utility.py --user <user> update <bill_id> --amount 120.00
python3 scripts/utility.py --user <user> delete <bill_id>
python3 scripts/utility.py --user <user> dump     # 该用户三表 UNION 全量导出
```

## 6. 同步网页（可选，0.3 起网页默认由网关动态导出）

```bash
python3 scripts/sync_site.py
# site synced: site/data.js (N bills, M families, v<version>)
```

- 从当前后端（SQLite / MySQL）导出 `site/data.js`（`window.UTILITY_DATA`）到运行目录
- 自动为 `site/index.html` 中 `data.js?v=` 打版本号，规避缓存
- 导出用户：`UL_SYNC_USER` > 默认用户（`UL_USER` 或 `auth_config.json`）
- 注意：网关 `/data.js` 为动态导出（按登录用户），`sync_site.py` 仅用于离线导出 / 腾讯文档同步场景

## 7. 配置 nginx 反代（公网访问）

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

提示：静态资源与登录共用同一 8099 端口，无需额外 location；`/` 与 `/index.html` 返回站点首页，未登录时自动跳转登录页，脚本/数据类请求未登录返回 401。

## 8. AI 技能（可选）

- 技能文件：`skill/SKILL.md`（开源脱敏模板，部署时替换 `{{PLACEHOLDER}}`）
- 用途：将截图 / PDF 账单交给 AI 客户端解析 → 调用 `scripts/utility.py` 入库 → `scripts/sync_site.py` 同步 → 腾讯文档表格覆盖式更新
- 腾讯文档能力依赖部署者自行接入（文件 ID、文件夹 ID 等配置项替换占位符）

## 9. 跨平台部署脚本（deploy.py）

`scripts/deploy.py` 是纯标准库实现，macOS / Linux / Windows 行为一致（`deploy.sh` 仅 macOS 可用）：

```bash
python3 scripts/deploy.py doctor      # 环境体检：平台、依赖、端口、服务方案
python3 scripts/deploy.py install     # 首次部署：同步 + 依赖 + 建库 + 启动 + 验证
python3 scripts/deploy.py upgrade     # 升级：只换程序，数据与凭据保留
python3 scripts/deploy.py start|stop|status|verify
```

Windows 下把 `python3` 换成 `python`，路径用反斜杠（`python scripts\deploy.py install`）。

| 平台 | 服务托管方式 | 回退 |
|---|---|---|
| macOS | launchd（`~/Library/LaunchAgents/*.plist`，KeepAlive） | 后台进程 |
| Linux | systemd 用户服务（`~/.config/systemd/user/utility-auth.service`） | 后台进程 |
| Windows | 后台进程（DETACHED_PROCESS，日志落运行目录） | — |

常用参数：`--app-dir`（运行目录）、`--port`（auth 端口，也可用 `UL_AUTH_PORT`）、
`--service auto|launchd|systemd|process|none`、`--sim windows|linux`（预览其它平台行为）。
离线环境可设 `UL_SKIP_DEPS=1` 跳过 pip 安装。

### Linux 手动托管（不想用脚本时）

`/etc/systemd/system/utility-auth.service`（系统级）或 `~/.config/systemd/user/`（用户级）：

```ini
[Unit]
Description=UtilityLog auth gateway
After=network.target

[Service]
Type=simple
Environment=UL_APP_DIR=/opt/utilitylog
WorkingDirectory=/opt/utilitylog
ExecStart=/usr/bin/python3 /opt/utilitylog/auth_server.py
Restart=always

[Install]
WantedBy=multi-user.target      # 用户级改为 default.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now utility-auth
```

### Windows 常驻（可选）

```bat
schtasks /create /tn UtilityLog /tr "python C:\utilitylog\auth_server.py" /sc onstart /ru SYSTEM
schtasks /run /tn UtilityLog
```

Windows 上 `site/images` 软链会自动退回目录联接（junction，无需管理员）；
若仍失败，手动把运行目录 `images/` 复制到 `site/images/` 即可显示账单附件。

### 各平台差异一览（已验证/规避）

- **端口**：`auth_server.py` 端口可用 `UL_AUTH_PORT` 覆盖（默认 8099），避免 Windows/服务器上端口冲突
- **换行与路径**：全部用 `os.path` / `pathlib`，无硬编码 `/`；同步用 `shutil` 而非 `rsync`
- **依赖安装**：统一 `sys.executable -m pip install --user`，不依赖 brew/apt/msi
- **代理污染**：验证请求显式禁用代理（`ProxyHandler({})`），避免 `HTTP_PROXY` 导致本机探测被劫到外网
- **Python 命令名**：文档 Windows 用 `python`，其余用 `python3`

## 常见问题

- **登录页打不开 / 401 循环**：确认 `auth_config.json` 或环境变量已配置，且源码 `site/` 目录存在 `login.html`、`index.html`。
- **数据没更新**：0.3 起网关 `/data.js` 动态导出，正常无需手工同步；离线导出用 `sync_site.py`；浏览器强刷（Cmd+Shift+R）。
- **端口占用**：设 `UL_AUTH_PORT=9099` 重启即可（不必改代码）；nginx 反代端口同步调整。
- **数据库路径**：默认 `<运行目录>/data/utility.db`；运行目录由 `UL_APP_DIR` > `UL_ROOT` > 源码根推导，可用 `UL_DB` 直接覆盖 SQLite 路径。
- **MySQL 连不上**：确认 `db_config.json` 在运行目录且 `UL_BACKEND=mysql`（或配置 `backend: "mysql"`）；用 `ul_app` 登录验证权限，跨库访问被拒属正常。

# Changelog

All notable changes to this project will be documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.0] - 2026-10-24

### 新增
- 双后端存储抽象：`scripts/db_backend.py` 统一 SQLite / MySQL 方言（upsert、自增、时间函数、占位符、类型），默认 SQLite 零依赖
- MySQL 部署支持：`db/schema.mysql.sql`（与 SQLite 语义等价）、`db_config.example.json` 模板、专属低权限用户权限隔离（`ul_app` 仅可访问 `utilitylog.*`）
- 源码 / 运行目录分离：`UL_APP_DIR` 环境变量指向运行目录（数据 / 配置 / 日志 / images / site/data.js），静态模板仍由源码 `site/` 提供；解析顺序 `UL_APP_DIR` > `UL_ROOT` > 源码根
- MySQL 后端端到端验证：init / 注册 / 登录 / 数据隔离 / 增删改查全部通过；专属用户跨库访问被拒（1142）
- launchd plist 与 nginx 本地部署更新至新路径，站点登录 / 注册 / 数据页验证通过

### 变更
- `auth_server.py` / `scripts/utility.py` / `scripts/sync_site.py` 路径逻辑与后端选择统一走 `db_backend.py` 与 `UL_APP_DIR`
- 仓库迁移至 `~/project/UtilityLog`（保留 git 历史与 remote），运行产物迁至 `~/myapp/utilitylog`
- `docs/DESIGN.md` / `docs/INSTALL.md` / README 中英文更新至 0.3.0：双后端架构、源码 / 运行目录结构、MySQL 部署手册
- `db/schema.sql` 标注 0.3.0，新增 `db/schema.mysql.sql`

### 说明
- 真实 MySQL 连接配置仅存于运行目录 `db_config.json`（gitignore），仓库仅保留脱敏模板
- root 管理凭据仅用于建库建用户，不入库不入配置
- 推送前已用 `git ls-files` + `git grep` 扫描确认仓库不含个人信息 / 真实配置

## [0.2.0] - 2026-10-24

### 新增
- 多用户体系：`users` / `api_tokens` / `user_settings` 表启用（0.1 已预置 DDL）
- `auth_server.py` 多用户认证：注册（POST /register）、登录、退出；会话 Cookie 绑定用户，兼容 Bearer Token / Basic 认证
- `utility.py` 用户隔离：`--user` 参数贯穿 add/update/delete/list/dump/add-family；新增 `register` / `list-users` 命令
- `site/login.html` 注册表单（用户名 / 密码 / 显示名称，注册成功自动登录）
- `site/index.html` 头部用户栏：显示当前登录用户名 + 退出按钮
- `sync_site.py` 按配置用户导出数据；`auth_server.py` 动态输出当前用户 `/data.js`
- `db/migrations/migrate_multiuser.py`：0.1 → 0.2 升级迁移（自动备份 + 建表 + 数据归属）

### 变更
- `families` / `bills_water` / `bills_electric` / `bills_gas` 增加 `user_id` 列，所有查询强制按用户过滤
- 现有历史数据（1 家庭、水 8 / 电 18 / 气 9 条）迁移归属至 `hh` 用户（凭据沿用 `auth_config.json` / 环境变量，仓库不含真实密码）
- `db/schema.sql` 版本升级 0.2.0；`docs/DESIGN.md` 同步更新架构与逻辑说明

### 说明
- 会话 Token 由内存文件 `.auth_tokens.json` 迁移至数据库 `api_tokens` 表持久化（不入库）
- 首页数据不再依赖手工 `sync_site.py`：登录后由认证网关按当前用户实时导出 `data.js`

## [0.1.0] - 2026-10-24

### 新增
- 项目开源化：源码（CLI 脚本 + 认证网关 + 网页）、文档、技能统一收纳
- `docs/DESIGN.md` 设计文档：表结构、程序逻辑、展示设计、多用户规划
- `db/schema.sql` 建表语句（含 0.2 多用户规划表）
- `skill/SKILL.md` 记录技能（脱敏模板版，敏感信息以占位符代替）
- README 中英文双语说明；传统命令安装 + AI 客户端（Codex / WorkBuddy）指令安装两种方式
- CHANGELOG 修订记录体系从本版本开始

### 变更
- 认证网关凭据由硬编码改为环境变量 / 配置文件读取（仓库内不含真实凭据）
- CLI 脚本路径由绝对路径改为基于项目根的自动推导，支持 `UL_ROOT` 环境变量覆盖

### 说明
- 本仓库为开源发布版，不包含任何本地私有记录（账单数据、账单截图、腾讯文档 ID、邮箱、地址、域名等均不入库）

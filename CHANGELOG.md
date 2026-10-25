# Changelog

All notable changes to this project will be documented in this file.

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.5.3] - 2026-10-25

### 新增
- **2026-10-25 10:26 · workbuddy** — 0.5.3 重复账单保存前确认：POST /api/bills/check 探测 + /api/bills 未确认 409 拦截（不再静默 upsert），前端三选「覆盖/合并/取消」；e2e 新增 7 项共 55/55 全绿（文件：scripts/utility.py scripts/mcp_server.py scripts/e2e_verify.py auth_server.py site/index.html scripts/deploy.sh scripts/deploy.py README.md README.zh-CN.md docs/API.md docs/DESIGN.md CHANGELOG.md）
- **重复账单保存前确认（不再静默覆盖）**：网页上传/录入保存时，若该家庭当月
  已存在同类型账单，后端返回 409 + 既有记录摘要（金额/用量/入库时间），
  前端弹出「覆盖保存 / 合并保存 / 取消」三选确认，用户确认后才真正入库
  —— 覆盖 = `replace` 整单替换（未填字段清空）；合并 = 增量保留（未填字段保留旧值）
- `POST /api/bills/check`（JSON `{family, month, type}`）：保存前探测该家庭当月
  该费种是否已有账单，供前端与脚本预检
- `utility.get_existing_bill(family, month, btype, user)`：重复探测共用查询

### 变更
- `POST /api/bills` 保存流程前置重复拦截：未带 `confirm_overwrite` 且命中既有
  记录时一律 409，不再直接 upsert；MCP 通道行为不变（继续用 `replace` 参数）

## [0.5.2] - 2026-10-25

### 变更
- **2026-10-25 08:59 · workbuddy** — 0.5.2 收尾：README 路线图小节彻底删除（规划移入协作区）+ 服务守护脚本 ensure_service.sh + 502 排查文档；deploy 全绿（文件：README.md README.zh-CN.md AGENTS.md scripts/ensure_service.sh docs/CODE_WALKTHROUGH.md docs/DESIGN.md CHANGELOG.md）
- **2026-10-25 07:52 · workbuddy** — 0.5.2 已知问题清零（SEC-1/P2-5/P3-5~P3-11/P4-2/P4-3）+ 三份文档收敛进 README 后删除 + 凭据移入钥匙串；新增 test_db_backend 17 项并接入部署验证；e2e 48/48（文件：README.md README.zh-CN.md docs/API.md docs/DESIGN.md docs/TESTING.md docs/CODE_WALKTHROUGH.md docs/INSTALL.md docs/KNOWN_ISSUES.md docs/ROADMAP.md skill/SKILL.md scripts/utility.py scripts/db_backend.py auth_server.py scripts/mcp_server.py scripts/e2e_verify.py scripts/test_db_backend.py scripts/deploy.sh scripts/deploy.py AGENTS.md CHANGELOG.md）
- **2026-10-25 07:35 · workbuddy** — 0.5.2：上传入口移到首页弹窗（含新建家庭），POST /api/families；修复 nginx client_max_body_size 挡大 PDF 与迁移遇孤儿家庭失败；部署验证增大body探测（文件：auth_server.py site/index.html site/settings.html db/migrations/migrate_family_share.py scripts/deploy.sh scripts/deploy.py docs/API.md docs/INSTALL.md docs/TESTING.md docs/DESIGN.md README.md README.zh-CN.md CHANGELOG.md）
- **2026-10-25 07:52 · workbuddy** — 0.5.2：已知问题清零（SEC-1 / P2-5 / P3-5~P3-11 / P4-2 / P4-3 全部处理）+ 安装、已知问题、路线图三份文档删除（安装并入 README，规划移入本地协作区）（文件：scripts/utility.py scripts/db_backend.py auth_server.py scripts/mcp_server.py scripts/e2e_verify.py scripts/test_db_backend.py README.md README.zh-CN.md docs/API.md docs/DESIGN.md docs/TESTING.md docs/CODE_WALKTHROUGH.md skill/SKILL.md scripts/deploy.py CHANGELOG.md）
- **上传入口移到看板首页**：头部新增「＋ 上传账单」按钮 + 弹窗（上传/识别/核对/入库全流程），
  设置页的上传卡片移除（设置页只保留 API Key / 密码 / 家庭共享）
- **上传时可直接新建家庭**：家庭下拉选「＋ 新建家庭…」即可输入名称创建，
  无需先去设置页/CLI 建家庭
- **版本号单一来源**：`scripts/utility.py` 新增 `__version__`，auth_server 启动横幅从它取，
  不再多处各写各的

### 新增
- `POST /api/families`（JSON `{name}`）：网页端新建家庭，重复名称返回 400；
  首页上传流程与将来其他页面共用
- **`add --replace` 开关**（CLI 与 MCP `add_bill.replace`）：upsert 语义显式化 ——
  默认增量保留（只覆盖本次传入字段，未传的保留旧值，符合「缺项不编造」）；
  `--replace` 全量覆盖（未传字段清 NULL，适合整单重新录入）
- **`scripts/test_db_backend.py`**：17 项后端层单元测试（方言翻译、字面量保护、
  upsert 双方言、后端选择优先级）

### 修复
- **nginx 默认 `client_max_body_size` 1MB 挡住大账单 PDF**：2MB+ 的 PDF 上传在 nginx 层
  直接 413（应用层的 20MB 限制根本轮不到）。反代配置需加 `client_max_body_size 25m`；
  部署验证新增「2MB 大 body 未鉴权 POST /mcp 应返回 401」探测，自动发现此类限流
- **`migrate_family_share` 被孤儿家庭拖垮**：e2e 临时用户清理后，其家庭的
  `user_id` 悬空，回填 owner 触发外键失败 → 整个升级中断。改为跳过并告警孤儿家庭，
  校验也不再要求它们有 owner
- **`get_backend()` 不读 `db_config.json.backend`**（P3-5）：与文档声称的优先级不一致，
  现在按 `UL_BACKEND` > 配置文件的 `backend` 字段 > `sqlite` 读取
- **`_mysql_sql()` 污染字符串字面量**（P3-7 / P3-8）：`?`→`%s` 与 `usage` 反引号都是全局替换，
  `LIKE '%?%'` 会被改成 `'%%s%'`。改为先把字面量摘出来占位、替换完再放回
- **`api_tokens.scope` 只写不读**（P3-9）：长期 API Key 与网页会话完全等价。现在
  Cookie 只认 `scope='session'`，Bearer 接受 `api` 与 `session`，API Key 不再能
  冒充网页会话
- **`register_user` 吞掉所有异常**（P3-6）：磁盘满、表不存在都被误报「用户已存在」
  且退出码 0（假成功）。改为只把唯一约束冲突解释为已存在，其余原样报错并非零退出
- **`send_login_page` 的 `__ERR__` 死分支**（P3-10）：占位符在登录页里根本不存在，
  已删除（错误提示由页面 JS 读 query string 渲染）
- **upsert 破坏「总价=分项之和」**（P2-5）：重复录入时旧分项 + 新总额会不自洽。
  现在保存后用落库值复算，不自洽明确告警，并提供 `--replace` 全量覆盖
- **金额告警在 MCP 通道不可见**：utility 的 warning 只 print，而 MCP 把 stdout
  重定向到 stderr → 工具调用方看不到。改为经 `warn_sink` 收集并放进工具返回的
  `warnings` 字段
- **`register` 文档语法与实现不符**（P4-2）：文档写位置参数，实际是
  `--user <name> register --password <pass>`，README 已按实现修正

### 安全
- **git remote 内嵌明文 token**（SEC-1）：4 个 remote 的凭据全部移入 macOS 钥匙串
  （`credential.helper=osxkeychain`），URL 清理为无凭据形式，推送仍正常。
  **遗留**：钥匙串里的 token 仍是原值，曾出现在 URL/history 的凭据应视为已泄露，
  请尽快轮换

### 文档
- **三份文档收敛进 README 后删除**：`docs/INSTALL.md`（安装部署）、
  `docs/ROADMAP.md`（路线图）、`docs/KNOWN_ISSUES.md`（已知问题）。
  原因：问题清单已全部修完，留着只会让人以为还有未修的坑；规划属内部信息，
  不对外公开。安装与部署并入 README（中英双语），路线图内容移入本地协作区
  `.agent-sync/PROJECT.md`，`DESIGN.md` / `API.md` /
  `CODE_WALKTHROUGH.md` / `skill/SKILL.md` / `deploy.py` 的引用同步更新
- README 版本号升至 0.5.2，并补「常见问题」：代理 502、launchd 注册、凭据轮换

### 测试
- 上传识别专项 e2e 扩充到 16 项：新增家庭创建、重复名 400、空名 400、未登录 401 断言
- `e2e_verify.py` 扩充到 48 项：新增 upsert 两种语义、金额不自洽告警、重复注册退出码、
  API Key 冒充 Cookie 被拒
- 真机抽测发现并修复两个问题（见上）

---

## [0.5.1] - 2026-10-24

### 新增
- **2026-10-24 23:36 · workbuddy** — 0.5.1 跨平台部署脚本 deploy.py + UL_AUTH_PORT + INSTALL/README 跨平台章节（文件：scripts/deploy.py auth_server.py docs/INSTALL.md README.md README.zh-CN.md docs/API.md docs/DESIGN.md scripts/deploy.sh scripts/mcp_server.py CHANGELOG.md）
- **跨平台部署工具 `scripts/deploy.py`**（纯标准库，macOS / Linux / Windows 通用）：
  - 源码同步用 `shutil`（不再依赖 rsync）；依赖安装用 `sys.executable -m pip install --user`（不依赖 brew/apt）；HTTP 验证显式禁用代理
  - 服务托管按平台自动选择：`launchd`（macOS）→ `systemd --user`（Linux）→ 后台进程（Windows / 无 systemd 环境），注册失败一律回退后台进程
  - Windows 上 `site/images` 软链自动退回目录联接（junction，无需管理员）
  - 命令：`doctor` / `install` / `upgrade` / `start` / `stop` / `status` / `verify`；`--app-dir --port --service --sim` 参数
- **`UL_AUTH_PORT` 环境变量**：auth_server 端口不再写死 8099，跨平台部署遇到端口冲突可直接换端口

### 文档
- `docs/INSTALL.md` 新增「跨平台部署」章节：三平台服务托管对照、Linux systemd 单元示例、Windows schtasks 常驻示例、已规避的平台差异清单
- README 快速开始改为跨平台命令（Windows 用 `python`），保留 macOS 的 `deploy.sh` 路径

### 测试
- 本机 doctor（含 `--sim linux/windows` 分支预览）；临时目录 + 8100 端口实跑 install：同步 → 建库 → 启动 → 验证 ✅ → 上传燃气 PDF 识别入库 → stop 清理

---

## [0.5.0] - 2026-10-24

### 新增
- **2026-10-24 23:28 · workbuddy** — 0.5.0 网页上传账单自动识别（bill_parser 三类模板 + /api/bills/upload|/api/bills + settings 卡片）+ README 精简配图 + TESTING/ROADMAP 文档（文件：scripts/bill_parser.py scripts/test_bill_parser.py auth_server.py site/settings.html scripts/deploy.sh README.md README.zh-CN.md docs/TESTING.md docs/ROADMAP.md docs/API.md docs/DESIGN.md CHANGELOG.md docs/images）
- **网页上传账单自动识别**（不再依赖 AI 技能，技能录入继续可用）：
  - `POST /api/bills/upload`（multipart，≤20MB）：保存附件到 `images/uploads/`，
    解析出「草稿」返回，**不落库**；前端设置页「账单上传识别」卡片核对后保存
  - `POST /api/bills`（JSON）：确认入库 / 手工录入，复用 MCP 工具层校验与 upsert，
    以已登录用户执行（body 中 `user` 被忽略，防冒充）
  - 解析器 `scripts/bill_parser.py`：PDF 文本层解析（国网上海分时电费含峰谷四示数/档位/
    年累计、上海燃气阶梯、供水分项三类模板 + 非分时兜底），PDF 换行拆词容错；
    金额不变式优先取「应付电费」保证 分项之和=总价，实付零头差异写入 note
  - 图片账单：本地不做 OCR，配置「模型 API」（OpenAI 兼容视觉接口）后自动识别，
    未配置则提示人工填写（附件已保存可对照）
  - pypdf 为可选依赖（BSD），deploy.sh 自动 best-effort 安装，缺失时功能降级不阻塞
- **文档重构**：README 精简为「版本 / 功能 / 安装」并配架构图与账单样例图；
  新增 `docs/TESTING.md`（测试说明）与 `docs/ROADMAP.md`（路线图）

### 测试
- `scripts/test_bill_parser.py`：解析器单元测试 20 项（三类模板 + 降级 + 真实样例回归）
- 上传识别专项 e2e 12 项：multipart 解析、草稿生成、确认入库、附件回读、401/防冒充

---

## [0.4.1] - 2026-10-24

### 新增
- **2026-10-24 22:51 · workbuddy** — 0.4.1 端到端回归验证 + 部署链路三处误判修复 + MCP 健壮性 + API Key 自动签发 + 技能改走 MCP（文件：scripts/e2e_verify.py scripts/deploy.sh scripts/mcp_server.py auth_server.py site/settings.html skill/SKILL.md docs/API.md docs/DESIGN.md docs/AI_AGENTS.md AGENTS.md CHANGELOG.md .gitignore）
- **2026-10-24 22:48 · workbuddy** — MCP HTTP 端点：POST /mcp 挂入 auth_server（前端与 MCP 同端口 8089），HTTP 通道强制已认证用户，deploy verify 增 /mcp 401 检查；与 21:56 会话的 0.4.1 版本统一合并（文件：scripts/mcp_server.py auth_server.py scripts/deploy.sh docs/API.md docs/DESIGN.md CHANGELOG.md）
- **MCP Streamable HTTP 端点 `POST /mcp`**：MCP 与前端共用 nginx `:8089` 同一端口，公网域名只需转发 8089 即可同时访问网页与 MCP 接口（此前 MCP 仅有 stdio 本地传输，域名无法访问）
  - 复用 `scripts/mcp_server.py` 全部 10 个工具与实现，工具清单单一来源
  - 鉴权复用 auth_server 三通道（Cookie / Bearer / Basic），远程推荐 Bearer API Key（网页「设置」重置获取）
  - 支持 JSON-RPC batch 与纯通知（`202 Accepted`）；`GET /mcp` 返回 405
  - `deploy.sh verify` 增加 `/mcp` 未鉴权 401 检查（auth_server 直连 + nginx 反代）
- **端到端回归脚本 `scripts/e2e_verify.py`**：41 项检查，用临时用户/家庭/账单真跑一遍
  MCP 十个工具、家庭共享同等权限、网页用户管理 API、金额不变式，跑完自动清理
  - 已接入 `deploy.sh install` / `upgrade`，未通过则直接判定该版本不可发布
  - `UL_SKIP_E2E=1` 可跳过（仅限排障，不推荐）
- **API Key 首次自动签发**：`/api/tokens` 列表为空时自动签发一把，并随该次响应一次性返回明文
  （列表接口平时只回前缀，新用户不必先猜「重置」才有 Key 可用）
- **家庭共享**：`family_members` 表 + `share-family` / `unshare-family` / `list-members`，
  被共享者与拥有者权限等同（可读、可写、可删）；网页「设置」可增删成员

### 修复
- **`deploy.sh` 误判服务不可用**：环境存在 `HTTP_PROXY` 时，`curl 127.0.0.1:...` 会把请求发给代理
  并拿到 502。全脚本改为 `curl --noproxy '*'`，本地探测不再受代理污染
- **`deploy.sh` 谎报 launchd 成功**：`launchctl load` 失败也返回 0。改以「服务是否真的注册进
  launchd」为判据；无 GUI 会话上下文（SSH / CI / 自动化环境）时自动回退独立后台进程，
  服务真的起来了才算通过
- **shell 变量名吞中文**：UTF-8 下 `$PIDFILE）` 会被 bash 当成变量名的一部分，
  `set -u` 下直接 unbound variable；改用 `${}`
- **MCP 服务可被一次误调用打死**：`utility.py` 用 `sys.exit(1)` 表达「操作被拒绝」，
  而 `SystemExit` 不是 `Exception`，穿透后会终止整个 stdio 服务进程 —— 已在工具层与主循环双层拦截
- **`list_members` 抛异常**：MySQL 返回的 `datetime` 无法 JSON 序列化（SQLite 环境测不出来）。
  mcp_server 统一改走带 `default=` 的序列化入口，双后端行为一致
- **表数量写死导致误报**：验证改为「核心表缺失数量」，版本新增表不再需要同步改期望值

### 安全
- HTTP MCP 通道以**已认证用户强制执行**（`threading.local` 请求上下文覆盖工具参数 `user`），登录用户无法冒充他人读写账单
- `POST /mcp` 请求体上限 1MB，非法 Content-Length / 超限一律 400/413 并关闭连接

### 变更
- 版本统一 0.4.1（此前 mcp_server 自称 0.4.0、其余文件停在 0.3.1/0.3.2）
- 技能契约 `skill/SKILL.md` 明确「录入走 MCP 服务」：给出 stdio 与 HTTP 两种配置，
  CLI 降为备用入口
- `scripts/mcp_server.py` 的 stdout 重定向从模块级移入 stdio `main()`——该文件被
  auth_server 当库 import 时不再污染网关日志；stdio 本地配置行为不变

---

## [0.3.2] - 2026-10-24

### 修复
- **2026-10-24 21:48 · workbuddy** — 个人信息清理 + git 历史重写 + 源码/运行隔离强化（文件：.gitignore auth_server.py scripts/deploy.sh scripts/pre-commit.py scripts/install_hooks.sh docs/API.md docs/CODE_WALKTHROUGH.md docs/DESIGN.md docs/KNOWN_ISSUES.md AGENTS.md）
- **2026-10-24 21:22 · workbuddy** — 0.3.2 缺陷修复批次：id 跨表冲突/路径穿越/Content-Length/XSS/is_active 等 15 项（文件：scripts/utility.py scripts/db_backend.py auth_server.py site/index.html db/schema.sql db/schema.mysql.sql db/migrations/migrate_families_unique.py docs/DESIGN.md docs/KNOWN_ISSUES.md skill/SKILL.md CHANGELOG.md）
- **id 跨表冲突导致误删误改**（数据损坏）：三张 bills 表各自独立自增，id 空间互不重叠，`find_bill_table()` 按序扫描命中首个即返回 → `delete 1` 永远删的是水费。改为多表命中时报错并要求 `--type` 消歧；`update` / `delete` 新增 `--type water|electric|gas`
- **update/delete 假成功**：缺失 `--user` 时 `WHERE user_id=NULL` 恒不匹配却仍打印成功。补 `require_user` 校验与 `rowcount` 校验
- **`update --sewage-price` / `--month` 静默失效**：别名与键转换条件判「键是否存在」而非「值是否为 None」，条件恒不成立。改为值判空回退，`bill_month` 纳入可写白名单
- **路径穿越**：`serve_static` 用 `str.startswith` 做边界判断，站点目录名为 `site` 时兄弟目录 `site_backup/` 可绕过。改用 `os.path.commonpath` 判断
- **Content-Length 未校验**：负数导致 `rfile.read(-1)` 阻塞至 EOF 占住工作线程；超长不消费 body 导致请求走私。负数/超长→413，非法→400，一律关闭连接
- **停用账号仍可访问**：`is_active=0` 只在 `/login` 表单路径生效，Basic 与 Token 通道未校验。补齐后停用即全通道失效
- **前端存储型 XSS**：家庭名/档位/月份/截图路径/档位明细及 ECharts tooltip 直接拼进 `innerHTML`，而这些字段来自 AI 解析的账单图片（外部输入）。新增 `esc()` 并全面转义
- **`tier_detail` 序列化不对称**：add 无条件 dumps、update 仅对 dict/list dumps，字符串落库为非法 JSON，前端 `JSON.parse` 抛错会中断整张明细表渲染。统一 `_norm_tier_detail()`，前端补 try/catch
- **SQLite 外键从未生效**：`PRAGMA foreign_keys` 是连接级开关，运行时连接未设置。逐连接开启 + WAL 模式
- **并发连接被重置**：`ThreadingHTTPServer` accept 队列默认 backlog=5。新增 `UtilityHTTPServer`，`request_queue_size=128`（80 并发实测全通）
- **每连接重复建表检测**：MySQL 下每次连接一次 `SHOW TABLES` 网络往返。检测结果按「后端+库路径」缓存到进程内
- **SQLite / MySQL 家庭名唯一性语义分叉**：SQLite 全局 UNIQUE vs MySQL `UNIQUE(user_id,name)`。SQLite 侧统一为 `UNIQUE(user_id, name)` + 迁移脚本
- **备注列网页不展示**：`note` 只落库不渲染。三张明细表补「备注」列

### 新增
- CLI 补齐档位参数：`add` / `update` 支持 `--current-tier` / `--tier-remaining` / `--year-usage` / `--tier-detail`，打通 `skill/SKILL.md`「分档计费必须记录」的强制要求
- 迁移脚本 `db/migrations/migrate_families_unique.py`：备份 → 重建表 → 行数校验 → 外键完整性检查 → 失败自动回滚，检测到跨用户重名时中止并列出冲突

### 安全与隔离
- **个人信息清理**：移除文档中的真实小区名、真实账号名、内网仓库域名、
  含用户名的 launchd 标签与本机绝对路径，全部替换为通用示例
- **git 历史重写**：用 `git filter-branch` 清理 21 个提交中的敏感内容，
  删除 `refs/original` 备份引用、过期 reflog 与悬空对象，
  已强制推送到 github 与 gitea（备份见本地 `~/UtilityLog-backup/`）
- **提交前敏感扫描 hook**：`scripts/pre-commit.py` + `scripts/install_hooks.sh`，
  命中本机绝对路径 / 私域域名 / 访问令牌 / API 密钥 / 明文密码时阻止提交并指出位置
- **`.gitignore` 补强**：`*cred*.json` / `*secret*.json` / `*token*.json` /
  `*.sqlite` / `*.sqlite3` / 编辑器临时文件
- **launchd 标签按用户名派生**：`deploy.sh` 原硬编码具体用户名（注释却写「不硬编码」），
  改为 `com.$(id -un).utility-auth`
- **源码 / 运行隔离**：rsync 排除项补 `AGENTS.md` / `*.bak`，
  运行目录只保留「程序副本 + 运行数据 + 凭据」，不含本机协作文件

### 修复
- **账单截图全部 404**：双重原因 —— 0.3.1 脱敏清理时删掉了 `site/images` 软链，
  且 `serve_static` 直接用 `self.path` 未做 URL 解码，中文文件名无法命中磁盘。
  现由 `deploy.sh link_images()` 创建软链，并新增路径解码；
  `serve_static` 改用 `abspath` 保留软链结构 + 显式白名单 `images/` 目录
- `docs/CODE_WALKTHROUGH.md` 的「运行现状（本机实测）」改为通用部署形态描述，
  本机专属信息（进程号 / 用户名标签 / 绝对路径）移入不入库的协作区
- `README.md` / `README.zh-CN.md` 补充一键部署与提交前扫描章节

### 说明
- `update` / `delete` 现在会拒绝无 `--type` 的歧义 id 操作（此前会误伤其他费种账单），AI 录入流程需相应带上 `--type`
- `site/images` 软链在 0.3.1 脱敏清理时被删除，账单截图链接目前 404（已记入 `docs/KNOWN_ISSUES.md` P3-11）
- `docs/KNOWN_ISSUES.md` 重写为含修复状态与新发现的完整版；`docs/DESIGN.md` 同步表结构与修订记录

---

## [0.3.1] - 2026-10-24

### 新增
- 一键部署 / 升级脚本 `scripts/deploy.sh`：`install` 模式完成 MySQL 建库建表 → 源码同步到运行目录 → 生成 `db_config.json` → 配置并加载 launchd → 启动验证；`upgrade` 模式 `git pull` → rsync 同步源码（排除 `data/ images/ entries/ temp* db_config.json .auth_tokens.json .htpasswd *.log` 等运行数据与凭据）→ 幂等 schema → 重启并验证；数据 / 程序分离，升级保留 myapp 运行数据与凭据；变量全部走 `$HOME` 与环境变量
- `docs/API.md`：`auth_server.py` 全路由接口设计（方法 / 路径 / 参数 / 鉴权 / 返回格式 / curl 示例）
- `db_backend.py` 自动建表：MySQL 后端连接后检测缺表时幂等执行 `db/schema.mysql.sql`（`CREATE TABLE IF NOT EXISTS`），SQLite 后端同样幂等，无需手动建表

### 变更
- `docs/DESIGN.md` 表结构设计补全：users / families / bills_water / bills_electric / bills_gas / api_tokens / user_settings 的字段、类型、外键、索引明细
- 版本号统一升至 0.3.1（`auth_server.py` / `db/schema.sql` / `db/schema.mysql.sql`）
- 运行目录 launchd plist 指向 `$UL_APP_DIR/auth_server.py`（程序 / 数据分离），并自动安装 `pymysql` 依赖（用户级）

### 修复
- 部署脚本兼容 macOS 默认 bash 3.2：所有变量与中文 / 全角字符邻接处改用 `${VAR}` 花括号
- MySQL 客户端探测：`PATH` 不含 `/opt/homebrew/bin` 时自动定位 `mysql` 客户端

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

# 已知问题清单

> 状态说明：`[x]` = 已在 0.3.2 修复并实测验证；`[ ]` = 待修。
> 来源：2026-10-24 两轮走查（首轮 + 独立复核），全部经过实测复现。
> 协作版见 `.agent-sync/KNOWN_ISSUES.md`。

---

## ✅ 0.3.2 已修复

### [x] P1-1　`update --sewage-price` 静默失效

**根因**　`update_bill()` 的兼容判定为 `"sewage_unit_price" not in fields`，
但 CLI 侧该键恒存在（默认 `None`），条件永不成立 → 别名永不转换，随后被白名单丢弃。

**修法**　改为值判空回退：`sewage_unit_price` 为 `None` 且 `sewage_price` 非 `None` 时取后者。
**验证**　`update 1 --type water --sewage-price 3.0` → 库中 `sewage_unit_price` 由 2.0 → 3.0 ✅

---

### [x] P1-2　SQLite / MySQL 家庭名唯一性语义不一致

SQLite 原为全局 `name TEXT NOT NULL UNIQUE`，MySQL 为 `UNIQUE(user_id, name)`。
SQLite 下 B 用户无法创建与 A 用户同名的家庭。

**修法**
- `db/schema.sql` 改为 `UNIQUE(user_id, name)`
- 新增 `db/migrations/migrate_families_unique.py`（备份 + 重建表 + 行数校验 + 外键检查 + 失败回滚）
- `docs/DESIGN.md` 字段表同步

**验证**　旧库迁移后约束生效、外键检查通过、数据行数不变；
bob 可创建与 alice 同名的「我家」✅

---

### [x] P1-3　三表 id 空间独立 → `update`/`delete <id>` 误伤其他费种 ⚠️数据损坏

**根因**　三张 bills 表各自 `AUTOINCREMENT`，id 空间互不重叠。
`find_bill_table()` 按 water→electric→gas 顺序逐表扫描，**命中第一个即返回**。
三表都有 `id=1` 时，`delete 1` 永远删的是水费；`list`/`dump` 输出的 id 跨表不唯一。

**复现（修复前）**
```
add water / add electric / add gas  →  三条都是 id=1
delete 1  →  "bill 1 deleted (bills_water)"   ← 删掉的是水费，电费仍在
```

**修法**
- `find_bill_table()` 收集全部命中，>1 张表时返回「需消歧」而非任选其一
- `update` / `delete` 新增 `--type water|electric|gas` 用于消歧
- 新增 `_bill_type_candidates()` 给出冲突提示
- `update` / `delete` 增加 `require_user` 校验与 `rowcount` 校验（消除「假成功」）

**验证**
```
delete 1              → error: id 1 在多个费种表中存在（water, electric, gas），请用 --type 指定
delete 1 --type electric → 只删电费，水费与燃气保留 ✅
```

---

### [x] P1-4　`serve_static` 路径穿越（`startswith` 前缀匹配可绕过）

**根因**　`str(full).startswith(str(ROOT.resolve()))` 缺路径分隔符边界：
站点目录名为 `site` 时，兄弟目录 `site_backup/` 同样满足前缀匹配。
`normpath` 只折叠 `..`，不阻止跳出到兄弟目录。

**修法**　改用 `os.path.commonpath([path, root]) == root` 做真实边界判断（新增 `_is_within()`）。

**验证**　登录后 `GET /../site_backup/secret.txt`、`/../../etc/passwd`、`/../db_config.json` 全部 404，
站内 `/index.html` 正常 200 ✅

---

### [x] P1-5　`Content-Length` 校验缺失 → 线程阻塞 + 请求走私

**根因**　只检查上界未检查下界。负数时 `rfile.read(-1)` **读到 EOF 才返回**，
在 keep-alive 连接上永久阻塞占用工作线程；超长时直接 return 不消费 body，
残留字节被当作下一个请求解析（请求走私）。

**修法**　负数/超长 → 413，非法 → 400，且一律 `close_connection = True`（杜绝走私）。

**验证**
```
CL=-1      → HTTP/1.1 413 Content-Length out of range  (0.00s)   ← 修复前 4s 超时
CL=100000  → HTTP/1.1 413 Content-Length out of range  (0.00s)
CL=abc     → HTTP/1.1 400 invalid Content-Length       (0.01s)
```

---

### [x] P2-1　CLI 未暴露档位参数

**修法**　`add` / `update` 各补 `--current-tier` / `--tier-remaining` / `--year-usage` / `--tier-detail`，
并透传到 `add_bill()` / `update_bill()`。`skill/SKILL.md` 已补对应参数说明。

**验证**　`add ... --current-tier 第一档 --tier-remaining 212 --year-usage 8 --tier-detail '{"一档":{"上限":220,"综合价":4.05}}'`
→ 四个字段全部正确落库 ✅

---

### [x] P2-2　`update --month` 静默失效

**根因**　同 P1-1（键恒存在），且 `bill_month` 不在 `TABLE_FIELDS` 白名单内，双重拦截。

**修法**　`bill_month` 纳入可写白名单；别名转换改为值判空。
**验证**　`update 1 --type water --month 2026-02` → `bill_month` 由 2026-01 → 2026-02 ✅

---

### [x] P2-3　停用账号（`is_active=0`）仍可通过 Basic / Token 通道访问

**根因**　只有 `/login` 表单路径检查 `is_active`，Basic 与 Cookie/Bearer Token 路径均未检查。

**修法**　`auth_from_basic()` 补 `row["is_active"]` 校验；
`token_user()` 的 JOIN 加 `u.is_active=1`（已签发 token 立即失效）。

**验证**　停用测试账号 → 其 token 访问 `/data.js` 得 401；恢复启用 → 200 ✅

---

### [x] P2-4　前端 `innerHTML` 直接拼接用户可控字段 → 存储型 XSS

**根因**　家庭名 / 档位 / 月份 / 截图路径 / 档位明细 全部由 AI 从账单图片解析写入（外部输入），
未经转义直接进 `innerHTML`；ECharts tooltip 的 HTML 同样会被渲染。

**修法**
- 新增 `esc()` 转义函数（`& < > " '`）
- 应用点：`f.name`、`b.current_tier`、`b.month`、`b.image`（属性值）、
  `tier_detail` 的 key 与各价字段、两处 tooltip 的月份
- `switchFamily(${Number(f.id)})` 加 `Number()` 兜底

**验证**　node 实测注入 `<img src=x onerror=alert(1)>` / `<svg onload=alert(1)>` /
`<b onmouseover=...>` / 属性逃逸，全部被转义（`&lt;img` 形式），无未转义命中 ✅

---

### [x] P3-1　`tier_detail` 在 add / update 两条路径序列化不对称

**根因**　`add_bill` 无条件 `json.dumps`（字符串被包成 JSON 字符串），
`update_bill` 仅对 dict/list dumps（字符串原样落库 → 非法 JSON）。
前端 `JSON.parse` 无 try/catch，一旦非法 JSON 会中断整张明细表渲染。

**修法**　统一走 `_norm_tier_detail()`：dict/list → dumps；str → 合法 JSON 原样存，
纯文本包一层；前端 `tierDetailTxtOf()` 补 try/catch 兜底。

---

### [x] P3-2　SQLite 外键约束实际从未生效

**根因**　`PRAGMA foreign_keys` 是**连接级**开关（默认 OFF）。
`schema.sql` 里的声明只对执行该脚本的那一次连接有效，
而 `db_backend.get_conn()` 每次新建连接且从不设置该 pragma。

**修法**　`get_conn()` 的 SQLite 分支逐连接 `PRAGMA foreign_keys = ON`，
并开启 `journal_mode = WAL`（缓解并发写锁竞争）。

---

### [x] P3-3　`ThreadingHTTPServer` accept 队列默认 backlog=5

**根因**　`socketserver.TCPServer.request_queue_size` 默认 5，
第 6 个以上并发连接在 accept 前即被内核 RST。

**修法**　新增 `UtilityHTTPServer(ThreadingHTTPServer)`，`request_queue_size = 128`。

**验证**　并发 16/40/80 → 全部成功（修复前 40 并发失败 14 个）✅

---

### [x] P3-4　每个认证请求都触发一次 `UPDATE ... last_used` 写事务 + 每连接一次 SHOW TABLES

**根因**　`token_user()` 在热路径上写审计字段；`ensure_schema()` 每次连接都做建表检测
（MySQL 下 `SHOW TABLES` 是网络往返）。

**修法**　schema 检测结果按「后端 + 库路径」缓存到进程内（`_SCHEMA_OK` + `_schema_cache_key()`）。

---

### [x] P4-1　`note` 字段落库但网页从不展示

**修法**　三张明细表各增「备注」列（`esc(b.note)`），`detailThead()` 同步加表头。

---

## 🔒 待处理 — 安全

### [ ] SEC-1　git remote 内嵌明文凭据

`.git/config` 中多个 remote 的 URL 含明文 token（形如 `https://<user>:<token>@<host>/...`）。
`.git/config` 本身不入库，但一旦被误提交 / 备份 / 截屏即泄露。

**行动**
1. 轮换 gitea 与 github 两个 token
2. 改用 SSH key 或 credential helper
3. 复查 shell history 与备份文件是否留有副本

> ⚠️ 需项目所有者手动操作，agent 无法代劳。

---

## 🟡 待处理 — 健壮性与文档

### [ ] P3-5　`get_backend()` 不读 `db_config.json` 的 `backend` 字段

文档（README / DESIGN / INSTALL）一致声称优先级为
`UL_BACKEND` > `db_config.json.backend` > `sqlite`，实现只读环境变量。

**现状**　0.3.1 的 `deploy.sh` 已改为在 launchd plist 里显式写 `UL_BACKEND=mysql`，
实际部署不再受影响；但文档与实现的措辞仍不一致，二选一对齐即可。

### [ ] P3-6　`register_user` 吞掉所有异常

```python
except Exception:
    print(f"user already exists: {username}")
```
磁盘满、表不存在等异常都被误报为「用户已存在」。建议区分 `IntegrityError` 与其他异常。

### [ ] P3-7　`_mysql_sql` 的 `usage` 反引号替换作用于全 SQL 字符串

```python
sql = re.sub(r"(?<!`)\busage\b(?!`)", "`usage`", sql)
```
不区分列名与字符串字面量。当前业务 SQL 无此情况，属潜在隐患。

### [ ] P3-8　`_mysql_sql` 的 `?`→`%s` 全局替换会破坏 SQL 字面量中的问号

`sql.replace("?", "%s")` 不区分占位符与字符串字面量。
`LIKE '%?%'` 会被改成 `'%%s%'`，匹配语义完全错误。
当前业务 SQL 无含 `?` 的字面量（已 grep 确认），属潜在隐患。

### [ ] P3-9　`api_tokens.scope` 字段完全未被鉴权读取

全仓库仅 3 处写入、0 处校验。因所有 token 都是 session 级、scope 无差异化语义，
实际危害有限，但属误导性设计——建议实现 scope 校验或删除该列。

### [ ] P3-10　`auth_server.py:265` 的 `__ERR__` 占位符不存在（死分支）

`site/login.html` 用 JS 读 `?err=` 渲染错误，服务端的 `body.replace(b"__ERR__", err)` 永不生效。
行为正确但代码误导，建议删除服务端分支。

### [ ] P3-11　`site/images` 软链缺失导致账单截图全部 404

0.3.1 的脱敏清理删除了 `site/images` 软链，`deploy.sh` 也不创建它。
DB 中 `image` 字段有值且文件真实存在于运行目录 `images/`，但网页链接指向 `images/...` → 404。

**修法**　在 `serve_static` 中允许运行目录 `images/` 作为显式白名单根目录。

### [ ] P4-2　`register` 语法文档与实现不符

文档写 `register <user> <pass>`（位置参数），实现是 `register --password <pass>`。

### [ ] P4-3　版本号标识多处不一致

`docs/API.md`（0.3.1）、`CHANGELOG.md`、`docs/DESIGN.md`（本次已统一为 0.3.2）、
`auth_server.py` 启动横幅（本次已改为 0.3.2）、`db/schema.*.sql`（0.3.1）。
建议版本号单一来源化（如 `__version__` 常量）。

---

## 🟠 待处理 — 语义

### [ ] P2-5　upsert 只更新本次传入的列 → 旧字段残留，破坏「总价=分项之和」

重复录入同一 `(family_id, bill_month)` 时，未传的字段保留旧值，而 `amount` 被覆盖：

```
第一次：amount=40, water_fee=22.5, sewage_fee=18, note="第一次录入"
第二次（只给 --usage 10 --amount 99）：
        → amount=99, water_fee=22.5, sewage_fee=18, note="第一次录入"
```

`amount=99` 而 `water_fee+sewage_fee=40.5` —— **违反「总价=分项之和」核心不变式**。

**这是设计取舍**　「upsert 覆盖」与「缺项不编造」两条原则在此冲突：
前者要求全量覆盖，后者要求缺失留 NULL。
**建议**　明确语义并加开关：`--replace`（全量覆盖，未传字段清 NULL）/ 默认增量保留，
同时在 `add` 成功提示中校验 `amount` 与分项之和是否自洽，不自洽则告警。

---

## ✅ 已验证正常（无需重复排查）

- 用户数据隔离：跨用户 `update` / `delete` 被正确拦截
- 三表 upsert：`UNIQUE(family_id, bill_month)` + `ON CONFLICT DO UPDATE` 生效
- MySQL 方言翻译：`?`→`%s`、`AUTOINCREMENT`、`datetime('now')`、`usage` 保留字
- 鉴权三通道：Cookie(180天) / Bearer Token / Basic 均可用；`/data.js` 按登录用户隔离
- 网关链路：未登录 `/` → 200 登录页；未登录 `/data.js` → 401
- launchd + nginx 部署：KeepAlive 存活，反代正常
- gitignore 覆盖：`git ls-files` 确认无运行数据入库
- `_split_statements` 处理 MySQL DDL 正确（含分号的字面量未被误切）
- 密码比对使用 `secrets.compare_digest`（恒定时间）
- 迁移脚本 `migrate_families_unique.py`：备份 → 重建 → 行数校验 → 外键检查 → 失败回滚，全流程实测通过

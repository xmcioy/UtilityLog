# 已知问题清单（走查发现）

> 来源：2026-10-24 对 v0.3.0（commit `3586948`）的只读走查，全部经过实测复现。
> 详细分析见 [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) 第 7 节。

## 🔴 P1 — 数据正确性

### [ ] P1-1 `update --sewage-price` 静默失效

**复现**
```bash
python3 scripts/utility.py --user alice update 1 --sewage-price 3.0
# → no fields to update      库中 sewage_unit_price 仍为原值
```

**根因**　`scripts/utility.py` `update_bill()` 的兼容代码判定条件为
`"sewage_unit_price" not in fields`，但 CLI 侧 `a.sewage_unit_price` 恒存在（默认 `None`），
条件永不成立 → `sewage_price` 别名永不转换，随后被 `TABLE_FIELDS` 白名单过滤丢弃。

**修法**　判定改为「值为 None 时才回退到别名」：
```python
if fields.get("sewage_unit_price") is None and fields.get("sewage_price") is not None:
    fields["sewage_unit_price"] = fields.pop("sewage_price")
else:
    fields.pop("sewage_price", None)
```

**影响**　`add` 路径正常（`add_bill` 内部处理正确），仅 `update` 路径受影响。

---

### [ ] P1-2 SQLite / MySQL 家庭名唯一性语义不一致

**现状**

| 后端 | 约束 | 语义 |
|---|---|---|
| SQLite `db/schema.sql:17` | `name TEXT NOT NULL UNIQUE` | 全局唯一 ❌ |
| MySQL `db/schema.mysql.sql:20` | `UNIQUE KEY uq_families_user_name (user_id, name)` | 用户内唯一 ✅ |

**复现**
```bash
python3 scripts/utility.py --user alice add-family 我家   # family added
python3 scripts/utility.py --user bob   add-family 我家   # family already exists ❌
```

**违反**　`docs/DESIGN.md:213`「家庭名只在同一用户内唯一」。

**修法**　SQLite 改为 `UNIQUE(user_id, name)`，并写迁移脚本处理存量
（存量库中若有跨用户重名，需先重命名再改约束）。

---

## 🟠 P2 — 功能缺失

### [ ] P2-1 CLI 未暴露档位参数

`TABLE_FIELDS` 与 `add_bill()` 均已定义 `current_tier` / `tier_remaining` / `year_usage` /
`tier_detail`，但 argparse 未提供对应选项：

```bash
python3 scripts/utility.py add ... --current-tier 第一档 --tier-remaining 100 --year-usage 50
# → error: unrecognized arguments
```

**违反**　`skill/SKILL.md` 第 31–36 行、`docs/DESIGN.md:117`（列为必须遵守原则）。

**修法**　`add` / `update` 各补 4 个选项：
```python
p_add.add_argument("--current-tier", dest="current_tier", default=None)
p_add.add_argument("--tier-remaining", dest="tier_remaining", type=float, default=None)
p_add.add_argument("--year-usage", dest="year_usage", type=float, default=None)
p_add.add_argument("--tier-detail", dest="tier_detail", default=None, help="JSON 字符串")
```
`tier_detail` 在 `add_bill` 中已做 `json.dumps`，但仅当传入为 dict/list 时才生效——
字符串会原样落库，需确认是否需要 `json.loads` 兼容。

---

### [ ] P2-2 `update --month` 静默失效

同 P1-1 的成因（键恒存在 + `bill_month` 不在 `TABLE_FIELDS` 白名单），改账期报
`no fields to update`，只能删了重录。

**修法**　把 `bill_month` 纳入 `update_bill` 的可写白名单（它已在 `UNION_COLS` 中出现，
说明设计上是可写的）。

---

## 🟡 P3 — 健壮性与文档一致性

### [ ] P3-1 `get_backend()` 不读 `db_config.json` 的 `backend` 字段

文档（README:51 / DESIGN.md:215,262 / INSTALL.md:30）一致声称优先级为
`UL_BACKEND` > `db_config.json.backend` > `sqlite`，实现只读环境变量：

```python
def get_backend():
    return (os.environ.get("UL_BACKEND") or "sqlite").strip().lower()
```

**本机影响**　`db_config.json` 写着 `"backend": "mysql"`，但 launchd plist 未设 `UL_BACKEND`，
实际跑的是 SQLite。文档与实现二选一对齐。

### [ ] P3-2 `__ERR__` 占位符不存在（死分支）

`auth_server.py:265` 的 `body.replace(b"__ERR__", err)` 永远不生效——`site/login.html`
用的是 JS 读 `?err=` 渲染。行为正确但代码误导，建议删除服务端分支或补占位符。

### [ ] P3-3 `register_user` 吞掉所有异常

```python
except Exception:
    print(f"user already exists: {username}")
```
磁盘满、表不存在等异常都会被误报为「用户已存在」。建议区分
`sqlite3.IntegrityError` / `pymysql.err.IntegrityError` 与其他异常。

### [ ] P3-4 连接数偏多

`add` 命令路径最多开 4~5 次连接（`user_id_by_name` × 2、`family_id_by_name` × 2、
写操作 1 次），每次都 `get_conn()` / `close()`。数据量小时无感，可考虑连接复用。

### [ ] P3-5 `_mysql_sql` 的 `usage` 反引号替换作用于全字符串

```python
sql = re.sub(r"(?<!`)\busage\b(?!`)", "`usage`", sql)
```
不区分列名与字符串字面量。当前 SQL 无此情况，属潜在隐患。

---

## 🔒 安全 — 需尽快处理

### [ ] SEC-1 git remote 内嵌明文凭据

`.git/config` 中 3 个 remote 的 URL 含明文 token：

```
gitea   https://xmcioy:<token>@<gitea-host>/xmcioy/UtilityLog.git
github  https://xmcioy:<token>@github.com/xmcioy/UtilityLog.git
```

`.git/config` 未入库（`.gitignore` 已覆盖），但一旦被误提交 / 备份 / 截屏即泄露。

**行动**
1. 轮换 gitea 与 github 两个 token
2. 改用 SSH key 或 credential helper 存储凭据
3. 复查 shell history 与备份文件是否留有副本

---

## ✅ 已验证正常的部分

- **用户数据隔离**：跨用户 `update` / `delete` 被正确拦截，账单未被篡改
- **三表 upsert**：`UNIQUE(family_id, bill_month)` + `ON CONFLICT DO UPDATE` 生效
- **MySQL 方言翻译**：`?`→`%s`、`AUTOINCREMENT`、`datetime('now')`、`usage` 保留字均已处理
- **鉴权三通道**：Cookie（180 天）、Bearer Token、Basic 均可用；`/data.js` 按登录用户隔离
- **网关链路**：未登录 `/` → 200 登录页；未登录 `/data.js` → 401
- **launchd + nginx 部署**：KeepAlive 服务存活，`/opt/homebrew/etc/nginx/servers/utility.conf` 反代正常
- **gitignore 覆盖**：`git ls-files` 确认无运行数据（DB/data.js/配置/图片）入库

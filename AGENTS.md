# AGENTS.md — UtilityLog 多 Agent 协作入口

> ⚠️ **如果你是一个 AI agent，在修改本项目任何文件前，请先阅读本文件。**

本项目采用**多 agent 并行开发**模式。为避免重复劳动与改动冲突，所有 agent 必须通过
本地协作区 `.agent-sync/` 登记与同步。

---

## 🔴 最重要的一条：改完必须部署验证才能发布

**项目所有者的硬性要求：不允许发布任何没在真实部署上验证过的程序。**

launchd 跑的是运行目录 `~/myapp/utilitylog` 的副本，**不是**源码仓库。
改完源码不同步 = 没改；同步了但不验证 = 可能发布了坏程序。

```bash
cd "$HOME/project/UtilityLog"
bash scripts/deploy.sh upgrade
```

**顺序不可颠倒：改代码 → 部署升级 → 验证通过 → 记录 → 提交 → 推送。**

**只有同时看到 `[deploy] 验证通过 ✅` 和 `[e2e] 全部通过 ✅` 才算合格。**

验证项（`deploy.sh` 自动跑）：
- 未登录 `/` → 200（登录页）
- 未登录 `/data.js` → 401（鉴权生效）
- 未登录 `/api/me` → 401（API 不回登录页）
- nginx `:8089` → 200
- MySQL 核心表齐全（缺失数 = 0）
- **端到端回归 48 项**：`scripts/e2e_verify.py` 用临时用户/家庭/账单真跑一遍
  MCP 十个工具、家庭共享同等权限、网页用户管理 API、upsert 语义、金额不变式，
  跑完自动清理

手工复核时 curl **必须加 `--noproxy '*'`** —— 环境有 `HTTP_PROXY` 时，
`curl 127.0.0.1:8099` 会把请求发给代理拿到 502，造成「服务挂了」的假象。

> launchd 在无 GUI 会话上下文的环境（SSH / CI / 自动化工具）注册不了，
> `deploy.sh` 会自动回退为独立后台进程，服务真的起来了才算通过。
> 要长期常驻，请在本机终端执行：
> `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.<用户名>.utility-auth.plist`
> 或装 cron 守护（服务挂了 2 分钟内自愈，健康时静默）：
> `(crontab -l 2>/dev/null | grep -v ensure_service.sh; echo '*/2 * * * * $HOME/myapp/utilitylog/scripts/ensure_service.sh >> /tmp/ul_watchdog.log 2>&1') | crontab -`
>
> **502 排查顺序**：`lsof -nP -iTCP:8099` 看服务在不在 → 不在就
> `bash scripts/ensure_service.sh`（立即拉起）→ 再查 `~/myapp/utilitylog/auth_server.log`。

**禁止**：先提交再部署 · 部署失败仍提交 · 只跑单元测试不跑部署 ·
「我本地直接跑能通」就认为部署没问题。

---

## 快速开始（五步）

```bash
cd "$HOME/project/UtilityLog"

# 1️⃣ 开工前：读别人的改动 + 状态 + 大纲（必做，不可跳过）
cat .agent-sync/AGENTS.md        # 强制公约
cat .agent-sync/CHANGELOG.md     # 别人做过什么
cat .agent-sync/STATUS.md        # 谁正在改什么（防撞车）
cat .agent-sync/PROJECT.md       # 项目大纲与待办

# 2️⃣ 动代码前：声明占用
bash .agent-sync/claim.sh <你的代号> "<任务简述>" <文件1> <文件2> ...

# 3️⃣ 改完后：部署升级并验证（🔴 不可跳过）
bash scripts/deploy.sh upgrade   # 必须看到「验证通过 ✅」

# 4️⃣ 登记改动（不登记 = 你的改动对其他 agent 隐身）
bash .agent-sync/log.sh <你的代号> "<一句话摘要>" <文件1> <文件2> ...

# 5️⃣ 提交推送（pre-commit hook 会扫描敏感信息）
git add -A && git commit -m "..." && git push
```

---

## 硬性规则速览

| # | 规则 |
|---|---|
| 1 | **不读就改 = 违规。** 开工前必须读 `CHANGELOG.md` + `STATUS.md` + `PROJECT.md` |
| 2 | **不声明就改 = 违规。** 动文件前必须 `claim.sh` 登记，避免撞车 |
| 3 | **🔴 不部署验证就发布 = 严重违规。** 必须跑 `deploy.sh upgrade` 看到验证通过 |
| 4 | **改完不记录 = 违规。** 必须 `log.sh`，否则其他 agent 不知道你做过什么 |
| 5 | `.agent-sync/` **不入公开仓库**，禁止 `git add` 该目录 |
| 6 | 不得违反项目 8 条设计约束（见 `.agent-sync/AGENTS.md`） |
| 7 | 改 schema 必须同时：写迁移脚本 + 更新 `docs/DESIGN.md` + 在旧库副本实测迁移 + CHANGELOG 注明「需迁移」 |
| 8 | 不得擅自回退他人已合入的改动；有异议请在 CHANGELOG 中提出 |

---

## 协作区文件

| 文件 | 作用 |
|---|---|
| `.agent-sync/AGENTS.md` | **强制公约全文**（含 8 条设计约束详解 + 部署验证细则） |
| `.agent-sync/PROJECT.md` | 项目大纲、代码地图、待办队列 |
| `.agent-sync/STATUS.md` | 进行中 / 已完成状态板（防撞车核心） |
| `.agent-sync/CHANGELOG.md` | 全部变更流水账（只追加） |
| `.agent-sync/DECISIONS.md` | 关键设计决策与理由（防止推翻已定设计） |
| `.agent-sync/KNOWN_ISSUES.md` | 协作版问题清单（含复现步骤与修法） |
| `.agent-sync/claim.sh` / `log.sh` | 占用登记 / 完工登记脚本 |

---

## 你的代号

每人/每 agent 一个不重名的代号（如 `codex`、`agent-b`、`claude`…），
在 `claim.sh` / `log.sh` 中使用，便于其他 agent 识别改动来源。

---

*协作区由项目所有者于 2026-10-24 建立。完整规则见 `.agent-sync/AGENTS.md`。*

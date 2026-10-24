# UtilityLog：AI 客户端（Codex / Workbuddy）一段指令安装

把下面整段复制粘贴给你的 AI 编程客户端（Codex、Workbuddy 或其它 agentic CLI），即可自动完成克隆、初始化、配置凭据、启动网关与同步站点。

---

## 中文指令（复制这一段）

请帮我安装并启动开源项目 UtilityLog（家庭水电气账单管理工具）：

1. 使用 `git clone <仓库地址> UtilityLog` 克隆项目，`cd UtilityLog`。
2. 运行 `python3 scripts/utility.py init` 初始化 SQLite 数据库。
3. 运行 `python3 scripts/utility.py add-family 我的家` 创建默认家庭。
4. 若不存在 `auth_config.json`，复制 `auth_config.example.json` 为 `auth_config.json`，并让用户提供用户名密码填入（若用户已提供环境变量 UL_USER/UL_PASS 则跳过）。
5. 后台启动认证网关 `python3 auth_server.py`，确认输出 `listening on 127.0.0.1:8099`。
6. 用 `curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/` 验证服务可访问（未登录应返回 200 登录页）。**必须加 `--noproxy '*'`**：环境若设了 `HTTP_PROXY`，不加会把请求发给代理并拿到 502，误判成服务没起来。
7. 向用户汇报：服务地址、如何登录、如何录入第一笔账单（**首选 MCP 服务 `utilitylog` 的 `add_bill` 工具**；备用 `scripts/utility.py add --type water ...`）与如何同步网页（`python3 scripts/sync_site.py`）。
8. 不要修改项目源码；配置文件 `auth_config.json` 与数据库 `data/` 属本地私有数据，不得提交到 git。

---

## English instruction (copy this block)

Please install and launch the open-source project UtilityLog (household utility bill tracker):

1. Run `git clone <repo-url> UtilityLog`, then `cd UtilityLog`.
2. Run `python3 scripts/utility.py init` to initialize the SQLite database.
3. Run `python3 scripts/utility.py add-family MyHome` to create a default household.
4. If `auth_config.json` does not exist, copy `auth_config.example.json` to `auth_config.json` and ask the user for credentials to fill in (skip if UL_USER/UL_PASS env vars are already set).
5. Start the auth gateway in the background: `python3 auth_server.py`, confirm output `listening on 127.0.0.1:8099`.
6. Verify with `curl -s --noproxy '*' -o /dev/null -w '%{http_code}' http://127.0.0.1:8099/` (should return 200 = login page). **Always pass `--noproxy '*'`**: if an `HTTP_PROXY` is set, the request would be sent to the proxy and come back as 502, which looks like the service is down.
7. Report to the user: service URL, how to log in, how to record the first bill (**preferred: the `add_bill` tool of the MCP server `utilitylog`**; fallback: `scripts/utility.py add --type water ...`), and how to sync the site (`python3 scripts/sync_site.py`).
8. Do not modify the source; `auth_config.json` and `data/` are local private data and must not be committed to git.

---

## 说明

- 上述指令假定已有可克隆的仓库地址（Gitea 私有仓库或 GitHub 公共仓库）。
- 安装后如需 AI 录入账单：把 `skill/SKILL.md` 的内容作为技能上下文提供给 AI 客户端即可。

# UtilityLog 安装指南（传统命令）

## 环境要求

- macOS / Linux / Windows（Python 3.9+，仅标准库，零 pip 依赖）
- 可选：nginx（公网反代）、Cloudflare Tunnel（公网域名）

## 1. 获取代码

```bash
git clone <仓库地址> UtilityLog
cd UtilityLog
```

## 2. 初始化数据库

```bash
python3 scripts/utility.py init
python3 scripts/utility.py add-family 我的家     # 可添加多个家庭
```

- `init` 自动创建 `data/utility.db`（families + bills_water / bills_electric / bills_gas）
- 也可直接用 `db/schema.sql` 的 DDL 手动建库

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
python3 auth_server.py
# UtilityLog auth gateway listening on 127.0.0.1:8099
```

网关功能：
- `POST /login`（user/pass 表单）→ 种 180 天 HttpOnly Cookie → 302 到 /
- `POST /logout` → 注销
- 其它请求校验 Cookie / Basic Auth，通过则返回 `site/` 静态文件
- 支持环境变量 `UL_ROOT` 覆盖项目根（默认从脚本位置推导）

## 5. 录入账单

水费：

```bash
python3 scripts/utility.py add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --prev-reading 100 --cur-reading 112.5 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5 \
  --bill-date 2026-10-08
```

电费（峰谷分项）：

```bash
python3 scripts/utility.py add --type electric --family 我的家 --month 2026-10 \
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
python3 scripts/utility.py add --type gas --family 我的家 --month 2026-10 \
  --usage 20 --amount 60.00 --unit-price 3.00 \
  --prev-reading 300 --cur-reading 320 \
  --current-tier 第一档 --tier-remaining 290 --year-usage 20 \
  --bill-date 2026-10-15
```

其它命令：

```bash
python3 scripts/utility.py list --family 我的家 --month 2026-10 --type water
python3 scripts/utility.py update --type electric --family 我的家 --month 2026-10 --amount 120.00
python3 scripts/utility.py delete --type gas --family 我的家 --month 2026-10
python3 scripts/utility.py dump     # 三表 UNION 全量导出
```

## 6. 同步网页

```bash
python3 scripts/sync_site.py
# site synced: site/data.js (N bills, M families, v<version>)
```

- 从 SQLite 导出 `site/data.js`（`window.UTILITY_DATA`）
- 自动为 `site/index.html` 中 `data.js?v=` 打版本号，规避缓存

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

## 常见问题

- **登录页打不开 / 401 循环**：确认 `auth_config.json` 或环境变量已配置，且 `site/` 目录存在 `login.html`、`index.html`。
- **数据没更新**：每次入库后必须执行 `sync_site.py`；浏览器强刷（Cmd+Shift+R）。
- **端口占用**：修改 `auth_server.py` 底部 `ThreadingHTTPServer(("127.0.0.1", 8099), ...)` 端口后重启。
- **数据库路径**：默认 `<项目根>/data/utility.db`，可用环境变量 `UL_ROOT` / `UL_DB` 覆盖。

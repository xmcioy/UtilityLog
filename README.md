# UtilityLog

![Version](https://img.shields.io/badge/version-0.5.2-2563eb) ![License](https://img.shields.io/badge/license-MIT-green) ![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab)

Self-hosted utility bill (water / electricity / gas) tracker for multiple households.
Three ways to enter bills: **web upload with automatic PDF recognition**, manual entry, or an **AI skill (MCP)** — all into one private database with an ECharts dashboard.

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

## Features

- 📄 **Upload & auto-recognize** — the "＋ 上传账单" button on the dashboard; month, usage, peak/valley readings and tiered-pricing fields are parsed automatically, you confirm, done. Pick or create a family on the spot. Image bills can be recognized via a configurable vision-model API
- 🏠 **Multi-family** — per-family ledgers; sharing a family grants members equal management rights
- ⚡ **Tiered & split pricing kept** — water fee + sewage fee, peak/valley readings and prices, tier level / remaining / yearly usage are first-class columns, never merged
- 🤖 **AI skill via MCP** — local stdio and remote Streamable HTTP (`/mcp`, same port as the web UI), Bearer API Key auth
- 🔐 **Private by default** — password-protected web, tokens in DB, sensitive files never committed
- 🗄 **SQLite (zero-dependency) or MySQL 8+**, switchable via config

![Architecture](docs/images/architecture.svg)

| Sample bill | Upload → review → save |
|---|---|
| ![Water bill sample](docs/images/bill-sample-water.png) | Dashboard "＋ 上传账单" button: pick/create family → upload PDF/screenshot → parsed draft → confirm & save |

## Quick start

Requirements: Python 3.9+ (Windows: `python`), no pip dependencies by default —
optional `pymysql` for the MySQL backend and `pypdf` for bill-PDF recognition.
nginx / Cloudflare Tunnel only if you expose it publicly.

### One-command deploy (recommended)

```bash
git clone <repo-url> UtilityLog && cd UtilityLog
# Cross-platform (macOS / Linux / Windows)
python3 scripts/deploy.py install     # sync code, deps, DB, service start, verify
python3 scripts/deploy.py upgrade     # upgrade: replace code only, keep data & credentials
# macOS also: bash scripts/deploy.sh install|upgrade (launchd-managed)
```

`deploy.py` picks the service manager automatically: launchd (macOS) → systemd user
unit (Linux) → background process (Windows / fallback). Every upgrade ends with an
end-to-end regression (`scripts/e2e_verify.py`, 48 checks on throwaway data) — it must
print both **`验证通过 ✅`** and **`全部通过 ✅`** before the build is publishable.

Other commands: `doctor` (environment check), `start` / `stop` / `status` / `verify`,
`--port` (or `UL_AUTH_PORT`), `--service auto|launchd|systemd|process|none`,
`--sim windows|linux` (preview another platform). Offline: `UL_SKIP_DEPS=1`.

### Run by hand

```bash
python3 scripts/utility.py init
python3 auth_server.py          # listens on 127.0.0.1:8099, put nginx in front
```

Credentials: copy `auth_config.example.json` → `auth_config.json` and fill in
`user` / `pass`, or export `UL_USER` / `UL_PASS`. Without either, logins are refused.

### Source / runtime separation

Programs live in the git repo; **data, credentials and logs live in a separate
runtime directory** (gitignored), so upgrades never touch your bills:

| Path | Contents |
|---|---|
| `~/project/UtilityLog` (repo) | code, templates, docs |
| `~/myapp/utilitylog` (runtime) | `data/utility.db`, `db_config.json`, `auth_config.json`, `.auth_tokens.json`, `images/`, `*.log` |

Runtime dir resolution: `UL_APP_DIR` > `UL_ROOT` > repo root. Backend selection:
`UL_BACKEND` > `db_config.json` `backend` field > `sqlite` (default).

### MySQL backend (optional)

```bash
pip install pymysql
```

```sql
CREATE DATABASE utilitylog DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'ul_app'@'localhost' IDENTIFIED BY '<strong-random-password>';
CREATE USER 'ul_app'@'127.0.0.1' IDENTIFIED BY '<strong-random-password>';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'localhost';
GRANT SELECT,INSERT,UPDATE,DELETE,CREATE,DROP,ALTER,INDEX,REFERENCES ON utilitylog.* TO 'ul_app'@'127.0.0.1';
FLUSH PRIVILEGES;
```

Save `{ "backend": "mysql", "host": "127.0.0.1", "port": 3306, "user": "ul_app",
"password": "<strong-random-password>", "database": "utilitylog" }` as
`<runtime>/db_config.json` (template: `db_config.example.json`), then
`UL_BACKEND=mysql python3 scripts/utility.py init`.

The app account only holds privileges on its own database; the config file stays in
the runtime dir and is never committed.

### nginx reverse proxy (public access)

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

Static assets, login and `/mcp` all share port 8099 — no extra locations needed.
Remember `client_max_body_size` large enough for bill PDFs.

### Entering bills

Web upload: dashboard "＋ 上传账单" → pick/create family → upload → confirm.
Manual entry (CLI, keeps tiered and split-pricing fields):

```bash
python3 scripts/utility.py --user <user> add --type water --family 我的家 --month 2026-10 \
  --usage 12.5 --amount 50.63 --water-fee 28.13 --sewage-fee 22.50 \
  --water-unit-price 2.25 --sewage-unit-price 2.00 \
  --prev-reading 100 --cur-reading 112.5 \
  --current-tier 第一档 --tier-remaining 207.5 --year-usage 12.5 --bill-date 2026-10-08
```

Electric adds the four peak/valley readings (`--peak-prev-reading`,
`--peak-cur-reading`, `--valley-prev-reading`, `--valley-cur-reading`) plus
`--peak-usage/--peak-price/--valley-usage/--valley-price`; gas adds `--unit-price`.
Re-entering the same family+month+type upserts: by default only the fields you pass
are overwritten, add `--replace` to clear the rest.

AI skill: point your MCP client at the `utilitylog` server (stdio runs
`scripts/mcp_server.py`; HTTP uses `https://<your-domain>/mcp` with a Bearer API Key).
The key is issued from the web "设置" page. Contract: [skill/SKILL.md](skill/SKILL.md).

Other CLI: `register` (`--user <name> register --password <pass>`), `list-users`,
`add-family`, `list`, `update`, `delete`, `dump`, `share-family`, `unshare-family`,
`list-members`. `update` / `delete` need `--type` when an id exists in several
bill tables. Web sync: `python3 scripts/sync_site.py` (the gateway exports
`/data.js` dynamically per logged-in user).

## Troubleshooting

- **Login page won't open / 401 loop** — check `auth_config.json` or `UL_USER`/`UL_PASS`.
- **`curl 127.0.0.1:8099` returns 502** — an `HTTP_PROXY` is hijacking local requests;
  use `curl --noproxy '*'`.
- **Service not registered in launchd** — SSH/CI/agent sessions lack a GUI context and
  `launchctl bootstrap gui/$UID` fails; `deploy.sh` falls back to a background process
  (PID in `<runtime>/.auth_server.pid`). For a persistent service run
  `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.<user>.utility-auth.plist`
  once in a real terminal.
- **Data not updating** — the gateway exports `/data.js` dynamically; hard-refresh the
  browser. Port conflict: set `UL_AUTH_PORT=9099` and restart.
- **Remote credentials** — stored in the macOS Keychain via `credential.helper=osxkeychain`
  (never embedded in remote URLs). Rotate tokens if they were ever pasted into a URL,
  shell history or backup.

## Documentation

| Doc | Content |
|---|---|
| [docs/API.md](docs/API.md) | HTTP API & MCP endpoint reference |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture & schema design |
| [docs/TESTING.md](docs/TESTING.md) | Test suite & deployment verification |
| [docs/CODE_WALKTHROUGH.md](docs/CODE_WALKTHROUGH.md) | Code map for maintainers |
| [skill/SKILL.md](skill/SKILL.md) | AI skill contract (sanitized template) |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

## Roadmap

Near term: more bill-parse templates (other regions/companies), parse self-learning
from user corrections, in-dashboard bill edit/delete, inline PDF/image preview.
Mid term: due-date reminders and monthly budgets, year-over-year comparison charts,
CSV/Excel export, mobile polish. Ideas: multi-instance aggregation, local OCR,
PWA offline dashboard, UI i18n.

## License

MIT — see [LICENSE](LICENSE).

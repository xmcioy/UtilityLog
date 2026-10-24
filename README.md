# UtilityLog

![Version](https://img.shields.io/badge/version-0.5.1-2563eb) ![License](https://img.shields.io/badge/license-MIT-green) ![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab)

Self-hosted utility bill (water / electricity / gas) tracker for multiple households.
Three ways to enter bills: **web upload with automatic PDF recognition**, manual entry, or an **AI skill (MCP)** — all into one private database with an ECharts dashboard.

中文说明见 [README.zh-CN.md](README.zh-CN.md)。

## Features

- 📄 **Upload & auto-recognize** — drop a bill PDF into the web UI; month, usage, peak/valley readings and tiered-pricing fields are parsed automatically, you confirm, done. Image bills can be recognized via a configurable vision-model API
- 🏠 **Multi-family** — per-family ledgers; sharing a family grants members equal management rights
- ⚡ **Tiered & split pricing kept** — water fee + sewage fee, peak/valley readings and prices, tier level / remaining / yearly usage are first-class columns, never merged
- 🤖 **AI skill via MCP** — local stdio and remote Streamable HTTP (`/mcp`, same port as the web UI), Bearer API Key auth
- 🔐 **Private by default** — password-protected web, tokens in DB, sensitive files never committed
- 🗄 **SQLite (zero-dependency) or MySQL 8+**, switchable via config

![Architecture](docs/images/architecture.svg)

| Sample bill | Upload → review → save |
|---|---|
| ![Water bill sample](docs/images/bill-sample-water.png) | Settings page "账单上传识别": upload PDF/screenshot → parsed draft → confirm & save |

## Quick start

```bash
git clone <repo-url> UtilityLog && cd UtilityLog
# Cross-platform (macOS / Linux / Windows; use `python` on Windows)
python3 scripts/deploy.py install
python3 scripts/deploy.py upgrade
# macOS also: bash scripts/deploy.sh install|upgrade (launchd-managed)
```

Or run by hand: `python3 scripts/utility.py init && python3 auth_server.py` (listens on 127.0.0.1:8099, put nginx in front). See [docs/INSTALL.md](docs/INSTALL.md).

## Documentation

| Doc | Content |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | Detailed install, MySQL backend, nginx |
| [docs/API.md](docs/API.md) | HTTP API & MCP endpoint reference |
| [docs/DESIGN.md](docs/DESIGN.md) | Architecture & schema design |
| [docs/TESTING.md](docs/TESTING.md) | Test suite & deployment verification |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Roadmap & ideas |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Known issues |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

## License

MIT — see [LICENSE](LICENSE).

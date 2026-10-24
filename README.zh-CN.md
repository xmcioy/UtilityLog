# UtilityLog

![Version](https://img.shields.io/badge/version-0.5.0-2563eb) ![License](https://img.shields.io/badge/license-MIT-green) ![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab)

家庭水/电/燃气账单自托管记录系统（多家庭 · 多费种）。支持**网页上传账单自动识别**、手工录入、AI 技能（MCP）三种录入方式，统一存入私有数据库并可视化展示。

English README: [README.md](README.md)

## 功能

- 📄 **账单上传自动识别**：网页上传账单 PDF，账期、用量、峰谷示数、阶梯档位等字段自动解析，核对后入库；图片账单可配置视觉模型 API 自动识别
- 🏠 **多家庭**：家庭独立账本，家庭共享后成员拥有同等管理权限
- ⚡ **阶梯与分项计费**：水费+污水费分项、峰谷四示数与单价、档位/剩余/年累计全部独立成列，绝不合并
- 🤖 **AI 技能（MCP）**：本地 stdio 与远程 HTTP（`/mcp`，与网页同端口）双传输，Bearer API Key 鉴权
- 🔐 **隐私优先**：密码保护、token 入库、敏感文件永不入库
- 🗄 **双后端**：SQLite 默认零依赖，可切换 MySQL 8+

![架构](docs/images/architecture.svg)

| 账单样例 | 上传识别 → 核对 → 入库 |
|---|---|
| ![账单样例](docs/images/bill-sample-water.png) | 设置页「账单上传识别」：上传 PDF/截图 → 自动解析草稿 → 核对保存 |

## 快速开始

```bash
git clone <仓库地址> UtilityLog && cd UtilityLog
bash scripts/deploy.sh install     # 首次部署：建库 → 同步 → launchd → 自动验证
bash scripts/deploy.sh upgrade     # 升级：只换程序，数据与凭据保留
```

或手动运行：`python3 scripts/utility.py init && python3 auth_server.py`（监听 127.0.0.1:8099，前面配 nginx 反代）。详见 [docs/INSTALL.md](docs/INSTALL.md)。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | 详细安装、MySQL 后端、nginx |
| [docs/API.md](docs/API.md) | HTTP API 与 MCP 端点说明 |
| [docs/DESIGN.md](docs/DESIGN.md) | 架构与表结构设计 |
| [docs/TESTING.md](docs/TESTING.md) | 测试套件与部署验证 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 版本展望与想法 |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | 已知问题 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新记录 |

## 协议

MIT — 见 [LICENSE](LICENSE)。

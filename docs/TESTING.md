# 测试说明（TESTING.md）

> 项目测试分三层：解析器单元测试 → 端到端回归 → 部署验证。
> **铁律：三层全部通过才算可发布**（`deploy.sh upgrade` 会自动跑后两层）。

## 1. 解析器单元测试（账单识别）

```bash
python3 scripts/test_bill_parser.py
```

覆盖 `scripts/bill_parser.py` 的三类账单模板（电费分时/非分时、燃气阶梯、水费分项），
含真实 PDF 样例回归（样例含个人信息不入库，位于本机 `/tmp/ul_bills/`，存在时自动跑）、
pypdf 缺失降级、PDF 损坏容错等 20 项断言。

关键断言：**金额不变式** ——
水 `amount = water_fee + sewage_fee`；
电 `amount = peak_usage×peak_price + valley_usage×valley_price`；
气 `amount = usage × unit_price`。

## 2. 端到端回归（scripts/e2e_verify.py）

```bash
cd <运行目录>
UL_BACKEND=mysql UL_APP_DIR=<运行目录> python3 scripts/e2e_verify.py --no-server
```

41 项检查，全部用临时用户/家庭/账单真跑，结束自动清理：

- MCP stdio 十个工具（initialize / tools/list / add / list / summary / share…）
- 家庭共享同等权限（读写删、成员表、取消共享）
- 网页 API（登录、API Key 签发与重置、Bearer/Basic 通道、密码修改）
- 页面可用性与金额不变式

## 3. 功能专项端到端（账单上传识别，0.5.0）

```bash
# 临时 SQLite 实例 + 真实样例 PDF，覆盖 multipart 解析、草稿生成、
# 确认入库、附件回读、越权防护、新建家庭 16 项断言
python3 /tmp/ul_upload_e2e.py   # 脚本不入库，验收时由会话重建
```

覆盖：

- 未鉴权上传/保存 → 401；伪造 `user` 字段被忽略
- 电费 PDF → `POST /api/bills/upload` 返回完整草稿（峰谷四示数 + 档位 + year_usage）
- 燃气 PDF → 草稿含阶梯剩余（跨行「立方米」容错）
- `POST /api/bills` 确认入库 → 读回唯一行、金额不变式、附件经 `/images/uploads/` 可访问

## 4. 部署验证（deploy.sh）

```bash
bash scripts/deploy.sh upgrade
```

自动执行并必须看到「验证通过 ✅」+「e2e 全部通过 ✅」：

| 检查 | 期望 |
|---|---|
| auth_server 直连 /login.html、/settings.html | 200 |
| auth_server 直连 /data.js、/api/me、/mcp（未鉴权 POST） | 401 |
| nginx 反代 /login.html、/mcp（未鉴权） | 200 / 401 |
| MySQL 核心表缺失数量 | 0 |
| e2e_verify 41 项 | 全部 PASS |

`UL_SKIP_E2E=1` 可跳过 e2e（仅限排障，不推荐）。

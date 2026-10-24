#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog MCP 服务（stdio 传输，零依赖）

让 AI 技能通过 MCP（Model Context Protocol）调用账单录入/查询能力，
而不是让 AI 直接拼 shell 命令。这样：
  - 参数有 schema 约束，AI 不会拼错参数名
  - 返回结构化结果，AI 不需要解析 stdout 文本
  - 档位/峰谷/分项等复杂字段有明确文档，避免漏录

协议：JSON-RPC 2.0，两种传输方式：
  1) stdio（默认）：消息按行分隔（NDJSON）。
     日志一律写 stderr —— stdout 只用于协议消息，这是 MCP 的硬性要求。
  2) HTTP：由 auth_server.py 以「POST /mcp」方式把本模块当库复用
     （import 本文件后调用 handle()），不做任何 stdout 重定向。
     鉴权由 auth_server 的 Cookie/Bearer/Basic 三通道承担，本模块只管协议。

用法（供 MCP 客户端本地 stdio 配置）：
  {
    "mcpServers": {
      "utilitylog": {
        "command": "python3",
        "args": ["/path/to/scripts/mcp_server.py"],
        "env": {"UL_APP_DIR": "/path/to/runtime", "UL_USER": "your-username"}
      }
    }
  }

HTTP 远程配置（同一份工具，走 nginx :8089 → auth_server /mcp）：
  {
    "mcpServers": {
      "utilitylog": {
        "url": "https://<your-domain>/mcp",
        "headers": {"Authorization": "Bearer <API Key>"}
      }
    }
  }
  API Key 在网页「设置」里重置获得（scope='api'，长期有效）。

环境变量：
  UL_APP_DIR      运行目录（数据库所在），同 CLI
  UL_BACKEND      sqlite | mysql，同 CLI
  UL_USER         默认操作用户（工具参数 user 可覆盖；HTTP 通道下被
                  已认证用户强制覆盖，防止越权指定他人）
"""
import datetime
import decimal
import json
import os
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import utility as U  # noqa: E402

SERVER_NAME = "utilitylog"
# 版本号与项目整体版本保持一致（0.5.2），不要各写各的
SERVER_VERSION = "0.5.2"


# MySQL 后端返回 DATETIME/DECIMAL 对象，SQLite 返回字符串/浮点 ——
# 直接 json.dumps 会在 MySQL 下抛 TypeError（SQLite 环境测不出来）。
# 全文件统一走这个序列化入口，保证双后端行为一致。
_JSON_DUMPS = json.dumps


def _json_default(obj):
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", "replace")
    return str(obj)


def _dumps(obj, **kw):
    kw.setdefault("ensure_ascii", False)
    return _JSON_DUMPS(obj, default=_json_default, **kw)
DEFAULT_PROTOCOL = "2024-11-05"

# stdio 模式专用协议输出句柄（main() 内初始化；HTTP 模式不使用）
_PROTOCOL_OUT = None

# ---------------------------------------------------------------------------
# 每线程请求上下文：HTTP 通道下由 auth_server 设置已认证用户名，
# 强制覆盖工具参数里的 user（否则任何登录用户都能冒充他人操作）。
# ThreadingHTTPServer 每请求一线程，threading.local 天然隔离，无并发竞争。
# ---------------------------------------------------------------------------
_CTX = threading.local()


def set_request_user(username):
    """设置当前线程的强制用户（HTTP 通道专用；传 None 恢复默认行为）"""
    _CTX.user = username


def _default_user():
    return os.environ.get("UL_USER") or os.environ.get("UL_MCP_USER")


def _resolve_user(args):
    return getattr(_CTX, "user", None) or args.get("user") or _default_user()


def _ok(text):
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def tool_add_bill(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user：请在工具参数或环境变量 UL_USER 中指定用户名")
    for k in ("family", "month", "type", "usage", "amount"):
        if a.get(k) is None:
            return _err(f"缺少必填参数 {k}")

    tier_detail = a.get("tier_detail")
    if isinstance(tier_detail, (dict, list)):
        tier_detail = _dumps(tier_detail, ensure_ascii=False)

    try:
        U.add_bill(
            family=a["family"], month=a["month"], btype=a["type"],
            usage=float(a["usage"]), amount=float(a["amount"]), user=user,
            bill_date=a.get("bill_date"), image=a.get("image"), note=a.get("note"),
            prev_reading=a.get("prev_reading"), cur_reading=a.get("cur_reading"),
            unit_price=a.get("unit_price"),
            water_unit_price=a.get("water_unit_price"),
            sewage_unit_price=a.get("sewage_unit_price"),
            water_fee=a.get("water_fee"), sewage_fee=a.get("sewage_fee"),
            peak_usage=a.get("peak_usage"), peak_price=a.get("peak_price"),
            valley_usage=a.get("valley_usage"), valley_price=a.get("valley_price"),
            peak_prev_reading=a.get("peak_prev_reading"),
            peak_cur_reading=a.get("peak_cur_reading"),
            valley_prev_reading=a.get("valley_prev_reading"),
            valley_cur_reading=a.get("valley_cur_reading"),
            current_tier=a.get("current_tier"),
            tier_remaining=a.get("tier_remaining"),
            year_usage=a.get("year_usage"),
            tier_detail=tier_detail,
        )
    except SystemExit:
        return _err("录入失败（参数校验未通过，见服务端日志）")
    except Exception as e:
        return _err(f"录入失败：{e}")

    # 回读确认
    rows = U.list_bills(user, a["family"], a["month"], a["type"])
    if rows:
        b = rows[0]
        return _ok(_dumps({
            "saved": True,
            "id": b.get("id"),
            "family": b.get("family"),
            "month": b.get("month"),
            "type": b.get("type"),
            "usage": b.get("usage"),
            "amount": b.get("amount"),
            "water_fee": b.get("water_fee"),
            "sewage_fee": b.get("sewage_fee"),
            "current_tier": b.get("current_tier"),
            "tier_remaining": b.get("tier_remaining"),
            "year_usage": b.get("year_usage"),
        }, ensure_ascii=False, indent=2))
    return _ok("已写入，但回读未找到记录，请用 list_bills 确认")


def tool_list_bills(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    rows = U.list_bills(user, a.get("family"), a.get("month"), a.get("type"))
    keep = ("id", "family", "month", "type", "usage", "usage_unit", "amount",
            "water_fee", "sewage_fee", "peak_usage", "valley_usage",
            "peak_prev_reading", "peak_cur_reading",
            "valley_prev_reading", "valley_cur_reading",
            "current_tier", "tier_remaining", "year_usage", "note", "image")
    slim = [{k: r.get(k) for k in keep if k in r} for r in rows]
    return _ok(_dumps({"count": len(slim), "bills": slim},
                          ensure_ascii=False, indent=2))


def tool_list_families(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    rows = U.list_families(user)
    return _ok(_dumps(rows, ensure_ascii=False, indent=2))


def tool_add_family(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    name = a.get("name")
    if not name:
        return _err("缺少必填参数 name")
    U.add_family(name, user)
    return _ok(_dumps({"family": name, "added": True}, ensure_ascii=False))


def tool_update_bill(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    bid = a.get("id")
    if bid is None:
        return _err("缺少必填参数 id")
    skip = {"id", "user", "type_for_lookup"}
    fields = {k: v for k, v in a.items() if k not in skip and v is not None}
    if not fields:
        return _err("没有要更新的字段")
    try:
        ok = U.update_bill(int(bid), user=user, btype=a.get("type_for_lookup"), **fields)
    except Exception as e:
        return _err(f"更新失败：{e}")
    if not ok:
        return _err(
            f"未更新 id={bid}：记录不存在、不属于 {user}，或 id 在多个费种表中冲突"
            f"（后者需传 type_for_lookup）")
    return _ok(_dumps({"updated": True, "id": bid,
                           "fields": sorted(fields)}, ensure_ascii=False))


def tool_delete_bill(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    bid = a.get("id")
    if bid is None:
        return _err("缺少必填参数 id")
    try:
        ok = U.delete_bill(int(bid), user=user, btype=a.get("type"))
    except Exception as e:
        return _err(f"删除失败：{e}")
    if not ok:
        return _err(
            f"未删除 id={bid}：记录不存在、不属于 {user}，或 id 在多个费种表中冲突"
            f"（后者需传 type）")
    return _ok(_dumps({"deleted": True, "id": bid}, ensure_ascii=False))


def tool_share_family(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    if a.get("family_id") is None or not a.get("to_user"):
        return _err("缺少必填参数 family_id 与 to_user")
    ok, msg = U.share_family(int(a["family_id"]), a["to_user"], user)
    return _ok(msg) if ok else _err(msg)


def tool_unshare_family(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    if a.get("family_id") is None or not a.get("from_user"):
        return _err("缺少必填参数 family_id 与 from_user")
    ok, msg = U.unshare_family(int(a["family_id"]), a["from_user"], user)
    return _ok(msg) if ok else _err(msg)


def tool_list_members(a):
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    if a.get("family_id") is None:
        return _err("缺少必填参数 family_id")
    rows = U.list_family_members(int(a["family_id"]), user)
    if not rows:
        return _err("家庭不存在，或你不是该家庭成员")
    return _ok(_dumps(rows, ensure_ascii=False, indent=2))


def tool_get_summary(a):
    """按年汇总三类账单的用量与费用，并给出分项构成。"""
    user = _resolve_user(a)
    if not user:
        return _err("缺少 user")
    year = a.get("year")
    rows = U.list_bills(user, a.get("family"))
    if year:
        rows = [r for r in rows if str(r.get("month", "")).startswith(str(year))]
    agg = {}
    for r in rows:
        t = r.get("type")
        d = agg.setdefault(t, {"count": 0, "usage": 0.0, "amount": 0.0,
                               "water_fee": 0.0, "sewage_fee": 0.0,
                               "peak_usage": 0.0, "valley_usage": 0.0})
        d["count"] += 1
        d["usage"] += r.get("usage") or 0
        d["amount"] += r.get("amount") or 0
        d["water_fee"] += r.get("water_fee") or 0
        d["sewage_fee"] += r.get("sewage_fee") or 0
        d["peak_usage"] += r.get("peak_usage") or 0
        d["valley_usage"] += r.get("valley_usage") or 0
    for d in agg.values():
        for k in ("usage", "amount", "water_fee", "sewage_fee",
                  "peak_usage", "valley_usage"):
            d[k] = round(d[k], 2)
    total = round(sum(d["amount"] for d in agg.values()), 2)
    return _ok(_dumps({"user": user, "year": year or "全部",
                           "total_amount": total, "by_type": agg},
                          ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# 工具声明（MCP tools/list 返回）
# ---------------------------------------------------------------------------

_TIER_PROPS = {
    "current_tier": {"type": "string",
                     "description": "当前档位，如「第一档」。水电气均按阶梯计费，必录"},
    "tier_remaining": {"type": "number",
                       "description": "本档剩余量 = 本档年上限 − 年累计用量"},
    "year_usage": {"type": "number", "description": "年累计用量"},
    "tier_detail": {"type": ["object", "string"],
                    "description": "各档明细 JSON，如 "
                                   '{"一档":{"上限":220,"综合价":4.05}}；'
                                   "电费含峰价/谷价，水费含分项水费价+污水价+污水比例"},
}

_SHARED_PROPS = {
    "family": {"type": "string", "description": "家庭名"},
    "month": {"type": "string", "description": "账期 YYYY-MM"},
}

TOOLS = [
    {
        "name": "add_bill",
        "description": (
            "录入一笔账单（同家庭同月同类型为 upsert，重复录入会覆盖不产生重复行）。\n"
            "金额不变式（必须自洽）：水 amount=water_fee+sewage_fee；"
            "电 amount=peak_usage×peak_price+valley_usage×valley_price；"
            "气 amount=usage×unit_price。\n"
            "档位四字段为强制记录项（阶梯计费），缺项请留空而非编造。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                **_SHARED_PROPS,
                "type": {"type": "string", "enum": ["water", "electric", "gas"],
                         "description": "费种"},
                "usage": {"type": "number", "description": "用量（水/气 m³，电 kWh）"},
                "amount": {"type": "number", "description": "总费用（元），须等于分项之和"},
                "user": {"type": "string", "description": "操作用户，省略则用 UL_USER"},
                "bill_date": {"type": "string", "description": "账单日期"},
                "image": {"type": "string", "description": "截图相对路径，如 2026-10/xxx.jpg"},
                "note": {"type": "string", "description": "备注（如「账单未印阶梯，按标准推算」）"},
                "prev_reading": {"type": "number", "description": "上次示数（水/气）"},
                "cur_reading": {"type": "number", "description": "本次示数（水/气）"},
                "unit_price": {"type": "number", "description": "单价（电综合/燃气）"},
                "water_unit_price": {"type": "number", "description": "水费单价（水）"},
                "sewage_unit_price": {"type": "number", "description": "污水单价（水）"},
                "water_fee": {"type": "number", "description": "水费金额（水）"},
                "sewage_fee": {"type": "number", "description": "污水费金额（水）"},
                "peak_usage": {"type": "number", "description": "峰电量（电）"},
                "peak_price": {"type": "number", "description": "峰单价（电）"},
                "valley_usage": {"type": "number", "description": "谷电量（电）"},
                "valley_price": {"type": "number", "description": "谷单价（电）"},
                "peak_prev_reading": {"type": "number", "description": "峰上期示数（电）"},
                "peak_cur_reading": {"type": "number", "description": "峰本期示数（电）"},
                "valley_prev_reading": {"type": "number", "description": "谷上期示数（电）"},
                "valley_cur_reading": {"type": "number", "description": "谷本期示数（电）"},
                **_TIER_PROPS,
            },
            "required": ["family", "month", "type", "usage", "amount"],
        },
    },
    {
        "name": "list_bills",
        "description": "查询账单，可按家庭/账期/费种过滤。返回结构化列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "family": {"type": "string", "description": "家庭名（可选）"},
                "month": {"type": "string", "description": "账期 YYYY-MM（可选）"},
                "type": {"type": "string", "enum": ["water", "electric", "gas"],
                         "description": "费种（可选）"},
                "user": {"type": "string", "description": "操作用户，省略则用 UL_USER"},
            },
        },
    },
    {
        "name": "list_families",
        "description": "列出当前用户可见的家庭（含别人共享给他的）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "user": {"type": "string", "description": "操作用户，省略则用 UL_USER"},
            },
        },
    },
    {
        "name": "add_family",
        "description": "新建家庭。家庭名在同一用户内唯一。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "家庭名"},
                "user": {"type": "string", "description": "操作用户，省略则用 UL_USER"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "update_bill",
        "description": (
            "按 id 修改账单的部分字段。\n"
            "⚠️ 三张 bills 表 id 空间独立，同一 id 可能同时存在于多个费种表；"
            "此时必须传 type_for_lookup 消歧，否则会拒绝执行。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "账单 id"},
                "type_for_lookup": {"type": "string",
                                    "enum": ["water", "electric", "gas"],
                                    "description": "用于定位所在的费种表"},
                "month": {"type": "string", "description": "新账期 YYYY-MM"},
                "usage": {"type": "number"},
                "amount": {"type": "number"},
                "note": {"type": "string"},
                "image": {"type": "string"},
                **_TIER_PROPS,
                "user": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_bill",
        "description": (
            "按 id 删除账单。\n"
            "⚠️ 三张 bills 表 id 空间独立，同一 id 可能命中多个费种，"
            "此时必须传 type 消歧。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "账单 id"},
                "type": {"type": "string", "enum": ["water", "electric", "gas"],
                         "description": "费种（id 跨表冲突时必传）"},
                "user": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "share_family",
        "description": (
            "把家庭共享给另一个用户。共享后对方拥有**同等管理权限**"
            "（可查看、新增、修改、删除该家庭的账单）。仅家庭拥有者可操作。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "family_id": {"type": "integer", "description": "家庭 id（用 list_families 查）"},
                "to_user": {"type": "string", "description": "被共享的用户名"},
                "user": {"type": "string", "description": "操作用户（须为拥有者）"},
            },
            "required": ["family_id", "to_user"],
        },
    },
    {
        "name": "unshare_family",
        "description": "取消某用户对家庭的共享。仅家庭拥有者可操作，不能移除拥有者自己。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "family_id": {"type": "integer", "description": "家庭 id"},
                "from_user": {"type": "string", "description": "要取消共享的用户名"},
                "user": {"type": "string", "description": "操作用户（须为拥有者）"},
            },
            "required": ["family_id", "from_user"],
        },
    },
    {
        "name": "list_members",
        "description": "列出家庭成员（含拥有者与被共享成员）。仅家庭成员可见。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "family_id": {"type": "integer", "description": "家庭 id"},
                "user": {"type": "string"},
            },
            "required": ["family_id"],
        },
    },
    {
        "name": "get_summary",
        "description": "按年汇总水电气三类账单的条数、用量、费用与分项构成。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "year": {"type": "string", "description": "年份 YYYY（省略则全部）"},
                "family": {"type": "string", "description": "家庭名（可选）"},
                "user": {"type": "string"},
            },
        },
    },
]

HANDLERS = {
    "add_bill": tool_add_bill,
    "list_bills": tool_list_bills,
    "list_families": tool_list_families,
    "add_family": tool_add_family,
    "update_bill": tool_update_bill,
    "delete_bill": tool_delete_bill,
    "share_family": tool_share_family,
    "unshare_family": tool_unshare_family,
    "list_members": tool_list_members,
    "get_summary": tool_get_summary,
}


# ---------------------------------------------------------------------------
# JSON-RPC 分发
# ---------------------------------------------------------------------------

def handle(msg):
    """处理一条 JSON-RPC 消息，返回响应 dict 或 None（通知无响应）"""
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # 通知（无 id）不回复
    is_notification = "id" not in msg

    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        return None if is_notification else {
            "jsonrpc": "2.0", "id": msg_id, "result": result}

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return None if is_notification else {
            "jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return None if is_notification else {
            "jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"未知工具: {name}"}}
        try:
            payload = fn(args)
        except SystemExit:
            # utility.py 内部一律用 sys.exit(1) 表达「操作被拒绝」（用户不存在、
            # 家庭不可见、id 跨表冲突等）。SystemExit 不是 Exception，
            # 若不在这里拦下，它会一路穿到最外层把整个 MCP 服务进程打死 ——
            # 对长驻服务来说，一次误调用就全挂是不可接受的。
            traceback.print_exc(file=sys.stderr)
            payload = _err("操作被拒绝：请检查用户名/家庭是否存在，以及是否有权限")
        except Exception:
            traceback.print_exc(file=sys.stderr)
            payload = _err("工具执行异常，详见服务端 stderr 日志")
        return {"jsonrpc": "2.0", "id": msg_id, "result": payload}

    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"未知方法: {method}"}}


def send(obj):
    _PROTOCOL_OUT.write(_dumps(obj, ensure_ascii=False) + "\n")
    _PROTOCOL_OUT.flush()


def main():
    # 仅 stdio 模式重定向 stdout：utility.py 会 print() 进度信息，
    # 而 stdio MCP 的 stdout 只能承载 JSON-RPC 消息。HTTP 模式（被
    # auth_server 当库 import）不做重定向，否则会污染网关日志。
    global _PROTOCOL_OUT
    _PROTOCOL_OUT = sys.stdout
    sys.stdout = sys.stderr

    print(f"[utilitylog-mcp] started, backend={U.db_backend.get_backend()}, "
          f"app_dir={U.db_backend.resolve_app_dir()}", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            send({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": f"解析失败: {e}"}})
            continue
        try:
            resp = handle(msg)
        except SystemExit:
            # 兜底：任何漏网的 sys.exit 都不允许终止服务进程
            traceback.print_exc(file=sys.stderr)
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": "内部错误"}}
        except Exception:
            traceback.print_exc(file=sys.stderr)
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": "内部错误"}}
        if resp is not None:
            send(resp)


if __name__ == "__main__":
    main()

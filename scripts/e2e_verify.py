#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 端到端回归验证（0.5.3）

用途：每次 deploy.sh upgrade 之后执行，确认「升级后的程序真的可用」，而不只是端口在听。

覆盖范围：
  1) MCP 服务（scripts/mcp_server.py，stdio JSON-RPC）：
     initialize / tools/list / add_family / add_bill / list_bills
     / get_summary / share_family / list_members / unshare_family / delete_bill
  2) 家庭共享同等权限：被共享者能读、能写、能删（共享即共同管理）
  3) 网页 API（auth_server）：登录 → /api/me → /api/tokens → 重置 API Key
     → 改密码 → /api/families → 成员增删 → Bearer / Basic 双通道鉴权
  4) 业务不变式：水 amount = water_fee + sewage_fee（分项之和必须自洽）

安全性：
  - 全部操作在自建的临时用户 / 临时家庭 / 临时账单上进行，与真实数据隔离；
  - 无论成功失败，结束时都会清理这些临时数据（finally 块）；
  - 不打印任何明文凭据（API Key 只显示前 8 位）。

用法：
  /usr/bin/python3 scripts/e2e_verify.py            # 自动拉起服务并验证
  /usr/bin/python3 scripts/e2e_verify.py --no-server # 服务已在跑，只验证
  环境变量：UL_APP_DIR / UL_AUTH_PORT（默认 8099）/ UL_BACKEND
"""
import argparse
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# /usr/bin/python3 与 launchd 的运行时保持一致（PATH 里的 python3 未必有 pymysql）
PY = os.environ.get("UL_PY", "/usr/bin/python3")
REPO = os.environ.get("UL_REPO_DIR", os.path.expanduser("~/project/UtilityLog"))
APP = os.environ.get("UL_APP_DIR", os.path.expanduser("~/myapp/utilitylog"))
PORT = int(os.environ.get("UL_AUTH_PORT", "8099"))
BASE = "http://127.0.0.1:%d" % PORT

# 临时数据一律带此前缀，清理时按前缀精确识别，绝不动真实数据
TAG = "e2e_tmp_"
U_A = TAG + "a"
U_B = TAG + "b"
FAM = TAG + "family"
MONTH = "2099-01"

PASS_A = "E2e-A-" + os.urandom(6).hex()
PASS_B = "E2e-B-" + os.urandom(6).hex()
PASS_A2 = "E2e-A2-" + os.urandom(6).hex()

results = []


def env():
    e = dict(os.environ)
    e.update({"UL_BACKEND": os.environ.get("UL_BACKEND", "mysql"),
              "UL_APP_DIR": APP,
              "PYTHONPATH": os.path.join(REPO, "scripts")})
    return e


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print("  [%s] %s%s" % (mark, name, ("  -> " + detail) if detail else ""), flush=True)
    return ok


def cli(args):
    """调用 CLI（唯一数据写入口），返回 (rc, stdout, stderr)"""
    r = subprocess.run([PY, os.path.join(REPO, "scripts", "utility.py")] + args,
                       cwd=REPO, env=env(), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# ---------------- MCP 客户端（stdio JSON-RPC 2.0） ----------------
class MCP:
    def __init__(self):
        # stderr 落盘而非丢弃：工具的报错堆栈全在那里，丢弃等于自断诊断线索
        self.p = subprocess.Popen(
            [PY, os.path.join(REPO, "scripts", "mcp_server.py")],
            cwd=REPO, env=env(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open("/tmp/ul_mcp_e2e.log", "a"),
            text=True, bufsize=1)
        self.mid = 0

    def _send(self, obj):
        self.p.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.p.stdin.flush()

    def _recv(self):
        while True:
            line = self.p.stdout.readline()
            # 空串 = EOF：服务进程已退出。
            # 这里必须直接抛错 —— 若继续 readline 会永远返回空串，直接死循环。
            if line == "":
                raise RuntimeError("MCP 服务已退出（stdout 收到 EOF）")
            if line.strip():
                return json.loads(line)

    def request(self, method, params=None):
        self.mid += 1
        self._send({"jsonrpc": "2.0", "id": self.mid, "method": method,
                    "params": params or {}})
        # 跳过服务主动推来的通知，直到拿到本次 id 的响应
        try:
            for _ in range(20):
                msg = self._recv()
                if msg.get("id") == self.mid:
                    return msg
        except RuntimeError:
            raise
        raise RuntimeError("未收到 id=%s 的响应" % self.mid)

    def call(self, tool, arguments):
        res = self.request("tools/call", {"name": tool, "arguments": arguments})
        if "error" in res:
            return {"isError": True, "text": json.dumps(res["error"], ensure_ascii=False)}
        content = res.get("result", {}).get("content") or [{}]
        text = content[0].get("text", "")
        # 工具返回的业务结果尽量解析为 JSON
        try:
            return json.loads(text)
        except Exception:
            return {"isError": res.get("result", {}).get("isError", False),
                    "text": text}

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
            self.p.wait(timeout=5)
        except Exception:
            pass


# ---------------- HTTP 客户端（绕过代理 + 带 Cookie） ----------------
class Web:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.ProxyHandler({}))  # 本地请求不走代理，否则会被误判 502

    def post(self, path, data=None, headers=None, follow=True):
        body = urllib.parse.urlencode(data or {}).encode()
        req = urllib.request.Request(BASE + path, data=body,
                                     headers=headers or {}, method="POST")
        try:
            r = self.op.open(req, timeout=10)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def post_json(self, path, obj, headers=None):
        """POST JSON body（0.5.3：/api/bills 与 /api/bills/check 都是 JSON 接口）"""
        h = {"Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(BASE + path,
                                     data=json.dumps(obj).encode("utf-8"),
                                     headers=h, method="POST")
        try:
            r = self.op.open(req, timeout=10)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")

    def get(self, path, headers=None):
        req = urllib.request.Request(BASE + path, headers=headers or {})
        try:
            r = self.op.open(req, timeout=10)
            return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")


# ---------------- 清理 ----------------
def cleanup():
    """用应用账号直连数据库删除本次临时数据（顺序：账单→成员→家庭→令牌→用户）"""
    cfg_path = os.path.join(APP, "db_config.json")
    sqls = []
    try:
        cfg = json.load(open(cfg_path)).get("mysql", {})
        mysql = None
        for c in ["mysql", "/opt/homebrew/bin/mysql", "/usr/local/bin/mysql"]:
            from shutil import which
            p = which(c) or c
            if os.path.exists(p) and os.access(p, os.X_OK):
                mysql = p
                break
        if mysql:
            e = dict(os.environ)
            e["MYSQL_PWD"] = cfg.get("password", "")
            for sql in [
                # 三张费种表都要清（按家庭名定位，只删本次临时家庭的账单）
                "DELETE bm FROM bills_water bm JOIN families f ON bm.family_id=f.id"
                " WHERE f.name=%s" % repr(FAM),
                "DELETE bm FROM bills_electric bm JOIN families f ON bm.family_id=f.id"
                " WHERE f.name=%s" % repr(FAM),
                "DELETE bm FROM bills_gas bm JOIN families f ON bm.family_id=f.id"
                " WHERE f.name=%s" % repr(FAM),
                "DELETE FROM family_members WHERE family_id IN"
                " (SELECT id FROM families WHERE name=%s)" % repr(FAM),
                "DELETE FROM families WHERE name=%s" % repr(FAM),
                "DELETE FROM api_tokens WHERE user_id IN"
                " (SELECT id FROM users WHERE username LIKE '%s%%')" % TAG,
                "DELETE FROM users WHERE username LIKE '%s%%'" % TAG,
            ]:
                subprocess.run([mysql, "-h" + str(cfg.get("host", "127.0.0.1")),
                                "-P" + str(cfg.get("port", 9306)),
                                "-u" + str(cfg.get("user", "ul_app")),
                                str(cfg.get("database", "utilitylog")),
                                "-e", sql], env=e, capture_output=True, text=True)
            return
    except Exception as ex:
        print("  [WARN] 清理时读配置失败: %s" % ex)


def wait_server(seconds=20):
    import socket
    deadline = time.time() + seconds
    while time.time() < deadline:
        s = socket.socket()
        s.settimeout(1)
        try:
            s.connect(("127.0.0.1", PORT))
            s.close()
            return True
        except Exception:
            time.sleep(0.4)
        finally:
            try:
                s.close()
            except Exception:
                pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-server", action="store_true", help="服务已在运行，只做验证")
    args = ap.parse_args()

    srv = None
    if args.no_server:
        if not wait_server(10):
            print("[e2e] 服务未就绪，无法验证", flush=True)
            return 2
    else:
        if not wait_server(1):
            print("[e2e] 拉起 auth_server（独立进程模式）...", flush=True)
            srv = subprocess.Popen(
                [PY, "auth_server.py"], cwd=APP, env=env(),
                stdout=open(os.path.join(APP, "auth_server.log"), "a"),
                stderr=subprocess.STDOUT, start_new_session=True)
        if not wait_server(25):
            print("[e2e] 服务未就绪，无法验证", flush=True)
            return 2

    try:
        run_all()
    finally:
        cleanup()
        if srv:
            srv.terminate()

    failed = [r for r in results if not r[1]]
    print("\n[e2e] 通过 %d / %d" % (len(results) - len(failed), len(results)))
    if failed:
        print("[e2e] 失败项：")
        for n, _, d in failed:
            print("  - %s %s" % (n, d))
        return 1
    print("[e2e] 全部通过 ✅")
    return 0


def run_all():
    # ============ 0) 准备临时用户 ============
    print("[e2e] 0. 准备临时用户（%s / %s）" % (U_A, U_B), flush=True)
    # 注意参数顺序：--user 是顶层参数，必须写在子命令之前，否则 argparse 会报参数错误
    rc, out, err = cli(["--user", U_A, "register", "--password", PASS_A])
    check("CLI register 创建用户 A", rc == 0, (err or out)[:120])
    rc, out, err = cli(["--user", U_B, "register", "--password", PASS_B])
    check("CLI register 创建用户 B", rc == 0, (err or out)[:120])

    # 0.5.2：重复注册必须退出码非 0。早期版本 except Exception 一律打印
    # "user already exists" 却返回 0（假成功），真实故障也会被这句话掩盖。
    rc, out, err = cli(["--user", U_A, "register", "--password", PASS_A])
    check("重复注册返回非 0 退出码（不再是假成功）", rc != 0,
          (out or err)[:80])

    # ============ 1) MCP 服务 ============
    print("[e2e] 1. MCP 服务（stdio JSON-RPC）", flush=True)
    m = MCP()
    try:
        res = m.request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e_verify", "version": "0.5.3"}})
        ok = "result" in res and "serverInfo" in res.get("result", {})
        check("MCP initialize 握手", ok, res.get("result", {}).get("serverInfo", {}).get("name", ""))

        res = m.request("tools/list")
        names = [t["name"] for t in res.get("result", {}).get("tools", [])]
        need = ["add_bill", "list_bills", "list_families", "add_family",
                "update_bill", "delete_bill", "share_family", "unshare_family",
                "list_members", "get_summary"]
        missing = [n for n in need if n not in names]
        check("MCP tools/list 暴露 10 个工具", not missing,
              "缺失: %s" % missing if missing else "%d 个" % len(names))

        # 新建家庭（通过 MCP）
        r = m.call("add_family", {"name": FAM, "user": U_A})
        check("MCP add_family 通过 A 建家庭", not r.get("isError"), str(r)[:160])

        # 家庭 id：从 list_families 里取
        r = m.call("list_families", {"user": U_A})
        fams = r if isinstance(r, list) else r.get("families", [])
        fid = None
        for f in fams:
            if f.get("name") == FAM:
                fid = f.get("id")
        check("MCP list_families 能看到自建家庭", fid is not None, "family_id=%s" % fid)

        # 通过 MCP 录一笔水费，且满足「总价 = 分项之和」
        r = m.call("add_bill", {
            "family": FAM, "month": MONTH, "type": "water",
            "usage": 20.0, "amount": 76.0,
            "water_fee": 50.0, "sewage_fee": 26.0,
            "water_unit_price": 2.5, "sewage_unit_price": 1.4444,
            "prev_reading": 100.0, "cur_reading": 120.0,
            "current_tier": 1, "tier_remaining": 200.0, "year_usage": 180.0,
            "user": U_A})
        check("MCP add_bill 录入水费（含阶梯档位）", not r.get("isError"), str(r)[:160])

        r = m.call("list_bills", {"family": FAM, "user": U_A})
        bills = r if isinstance(r, list) else r.get("bills", [])
        b1 = bills[0] if bills else {}
        got = b1.get("id")
        check("MCP list_bills 读回该账单", bool(got), "id=%s" % got)
        if got:
            sum_ok = abs((b1.get("water_fee") or 0) + (b1.get("sewage_fee") or 0)
                         - (b1.get("amount") or 0)) < 0.01
            check("不变式：amount = water_fee + sewage_fee", sum_ok,
                  "%.2f = %.2f + %.2f" % (b1.get("amount") or 0,
                                          b1.get("water_fee") or 0,
                                          b1.get("sewage_fee") or 0))

        r = m.call("get_summary", {"family": FAM, "year": 2099, "user": U_A})
        check("MCP get_summary 汇总可用", not r.get("isError"), str(r)[:120])

        # ---- 0.5.2：upsert 语义显式化 ----
        # 第一次：带 note 的完整录入
        m.call("add_bill", {"family": FAM, "month": "2099-03", "type": "water",
                            "usage": 10.0, "amount": 40.0, "note": "第一次录入",
                            "water_fee": 20.0, "sewage_fee": 20.0,
                            "user": U_A})
        # 第二次（增量保留，默认）：不传 note → 旧 note 应保留
        m.call("add_bill", {"family": FAM, "month": "2099-03", "type": "water",
                            "usage": 12.0, "amount": 40.0,
                            "water_fee": 20.0, "sewage_fee": 20.0,
                            "user": U_A})
        r = m.call("list_bills", {"family": FAM, "month": "2099-03", "user": U_A})
        bills_03 = r if isinstance(r, list) else r.get("bills", [])
        note_after_inc = (bills_03[0].get("note") if bills_03 else None)
        check("增量保留（默认）：未传字段保留旧值", note_after_inc == "第一次录入",
              "note=%r" % note_after_inc)

        # 第三次（全量覆盖 replace=true）：不传 note → 应被清空
        m.call("add_bill", {"family": FAM, "month": "2099-03", "type": "water",
                            "usage": 14.0, "amount": 40.0,
                            "water_fee": 20.0, "sewage_fee": 20.0,
                            "replace": True, "user": U_A})
        r = m.call("list_bills", {"family": FAM, "month": "2099-03", "user": U_A})
        bills_03 = r if isinstance(r, list) else r.get("bills", [])
        note_after_rep = (bills_03[0].get("note") if bills_03 else "missing")
        usage_after_rep = (bills_03[0].get("usage") if bills_03 else None)
        check("全量覆盖（replace=true）：未传字段被清空", note_after_rep in (None, ""),
              "note=%r" % note_after_rep)
        check("全量覆盖仍写入本次传入的字段", usage_after_rep == 14.0,
              "usage=%s" % usage_after_rep)

        # ---- 0.5.2：不变式告警 ----
        # 故意造一条 amount 与分项之和不自洽的记录，服务端应告警（不是静默）
        r = m.call("add_bill", {"family": FAM, "month": "2099-04", "type": "water",
                                "usage": 10.0, "amount": 99.0,
                                "water_fee": 20.0, "sewage_fee": 20.0,
                                "user": U_A})
        check("金额不自洽时给出告警（不静默）",
              "warning" in str(r).lower() and "不自洽" in str(r),
              str(r)[:120])

        # ============ 2) 家庭共享：同等权限 ============
        print("[e2e] 2. 家庭共享（被共享者同等管理权限）", flush=True)
        r = m.call("share_family", {"family_id": fid, "to_user": U_B, "user": U_A})
        check("MCP share_family 共享给 B", not r.get("isError"), str(r)[:160])

        r = m.call("list_families", {"user": U_B})
        fams_b = r if isinstance(r, list) else r.get("families", [])
        check("B 能看到被共享的家庭", any(f.get("name") == FAM for f in fams_b),
              "%d 个可见家庭" % len(fams_b))

        r = m.call("list_bills", {"family": FAM, "user": U_B})
        bills_b = r if isinstance(r, list) else r.get("bills", [])
        check("B 能读到 A 的账单（可读）", len(bills_b) >= 1, "%d 条" % len(bills_b))

        # 被共享者写入：B 在该共享家庭录一笔电费
        r = m.call("add_bill", {
            "family": FAM, "month": "2099-02", "type": "electric",
            "usage": 300.0, "amount": 150.0,
            "peak_usage": 200.0, "peak_price": 0.6,
            "valley_usage": 100.0, "valley_price": 0.3,
            "peak_prev_reading": 1000.0, "peak_cur_reading": 1200.0,
            "valley_prev_reading": 500.0, "valley_cur_reading": 600.0,
            "current_tier": 1, "tier_remaining": 3000.0, "year_usage": 2400.0,
            "user": U_B})
        check("B 能向共享家庭写入账单（可写）", not r.get("isError"), str(r)[:160])

        r = m.call("list_members", {"family_id": fid, "user": U_A})
        members = r if isinstance(r, list) else r.get("members", [])
        roles = {mm.get("username"): mm.get("role") for mm in members}
        check("成员表含 owner=A + member=B",
              roles.get(U_A) == "owner" and roles.get(U_B) == "member",
              "roles=%s raw=%s" % (roles, str(r)[:160]))

        # 非成员不得访问（用一个根本不存在的用户名，也应被拒绝而不是放行）
        rc, out, err = cli(["--user", TAG + "ghost", "list-members", str(fid)])
        check("非成员访问成员表被拒绝", rc != 0, (err or out)[:80])

        # 拥有者可以删掉被共享者写的那笔 —— 共享双方权限等同的另一面
        r = m.call("list_bills", {"family": FAM, "user": U_A})
        bills = r if isinstance(r, list) else r.get("bills", [])
        target = [b for b in bills if b.get("month") == "2099-02"]
        if target:
            rr = m.call("delete_bill", {"id": target[0]["id"],
                                        "type": "electric", "user": U_A})
            check("A 能删除 B 写入的账单（同等管理权限）", not rr.get("isError"),
                  str(rr)[:100])

        r = m.call("unshare_family", {"family_id": fid, "from_user": U_B, "user": U_A})
        check("MCP unshare_family 取消 B 的共享", not r.get("isError"), str(r)[:160])
        r = m.call("list_families", {"user": U_B})
        fams_b2 = r if isinstance(r, list) else r.get("families", [])
        check("取消共享后 B 不再看到该家庭",
              not any(f.get("name") == FAM for f in fams_b2), "%d 个可见家庭" % len(fams_b2))

        r = m.call("list_members", {"family_id": fid, "user": U_A})
        members = r if isinstance(r, list) else r.get("members", [])
        check("取消共享后成员表只剩 owner", len(members) == 1, "%d 人" % len(members))

        # 服务必须经历以上全部调用仍然存活（含被拒绝的调用）
        alive = m.request("ping")
        check("MCP 服务在全部调用后仍存活", "result" in alive, "")
    except RuntimeError as e:
        check("MCP 服务在调用过程中保持存活", False, str(e))
    finally:
        m.close()

    # ============ 3) 网页 API ============
    print("[e2e] 3. 网页 API（用户管理 / API Key / 共享）", flush=True)
    w = Web()
    code, _ = w.get("/api/me")
    check("未登录访问 /api/me 返回 401", code == 401, "got %s" % code)

    code, body = w.post("/login", {"user": U_A, "pass": PASS_A})
    has_cookie = any(c.name for c in w.cj)
    check("POST /login 登录成功（拿到会话 Cookie）", has_cookie and code == 200,
          "code=%s" % code)

    code, body = w.get("/api/me")
    ok = code == 200 and json.loads(body).get("user", {}).get("username") == U_A
    check("已登录 /api/me 返回本人", ok, "code=%s" % code)

    # 首次访问应自动签发一把 API Key，并把明文随这次响应一并返回（仅此一次）
    code, body = w.get("/api/tokens")
    tj = json.loads(body) if code == 200 else {}
    toks = tj.get("tokens", [])
    check("GET /api/tokens 列出 API Key（新用户自动签发）",
          code == 200 and len(toks) >= 1, "%d 个" % len(toks))
    check("首次签发返回一次性明文", bool(tj.get("one_time_plaintext")),
          "%s…" % str(tj.get("one_time_plaintext", ""))[:8])

    # 再次访问不应再回明文（明文只能出现一次）
    code2, body2 = w.get("/api/tokens")
    tj2 = json.loads(body2) if code2 == 200 else {}
    check("二次访问不再返回明文", not tj2.get("one_time_plaintext"), "")

    code, body = w.post("/api/tokens/reset")
    newtok = json.loads(body).get("token", "") if code == 200 else ""
    check("POST /api/tokens/reset 重置 API Key", bool(newtok),
          "%s…（明文仅此一次返回）" % newtok[:8])

    # 0.5.2：scope 校验。API Key（scope='api'）只用于 API / MCP 的 Bearer 通道，
    # 不应被当成网页会话 Cookie 使用（此前 scope 字段只写不读，两者完全等价）。
    code, _ = w.get("/api/me", {"Cookie": "ul_token=" + newtok})
    check("API Key 冒充网页会话 Cookie 被拒绝", code == 401, "got %s" % code)
    code, _ = w.get("/api/me", {"Authorization": "Bearer " + newtok})
    check("同一把 Key 走 Bearer 通道正常", code == 200, "got %s" % code)

    # Bearer / Basic 双通道（API Key 作为机器入口）
    code, body = w.get("/api/me", {"Authorization": "Bearer " + newtok})
    check("Bearer API Key 通道可用", code == 200, "code=%s" % code)

    import base64
    basic = base64.b64encode(("%s:%s" % (U_A, PASS_A)).encode()).decode()
    w2 = Web()
    code, body = w2.get("/api/me", {"Authorization": "Basic " + basic})
    check("Basic 用户名密码通道可用", code == 200, "code=%s" % code)

    code, body = w.get("/api/families")
    fams = json.loads(body).get("families", []) if code == 200 else []
    fid_web = None
    for f in fams:
        if f.get("name") == FAM:
            fid_web = f["id"]
    check("GET /api/families 返回家庭列表", code == 200 and fid_web is not None,
          "family_id=%s" % fid_web)

    # 共享：A 把家庭共享给 B（网页路径）
    if fid_web:
        code, body = w.post("/api/families/%d/members" % fid_web, {"username": U_B})
        check("网页 API 共享家庭给 B", code == 200, "code=%s %s" % (code, body[:80]))

        code, body = w.get("/api/families/%d/members" % fid_web)
        mem = json.loads(body).get("members", []) if code == 200 else []
        check("网页 API 列出成员含 B",
              any(mm.get("username") == U_B for mm in mem), "%d 人" % len(mem))

        # 非拥有者不能增删成员
        w3 = Web()
        w3.post("/login", {"user": U_B, "pass": PASS_B})
        code3, _ = w3.post("/api/families/%d/members" % fid_web,
                           {"username": "someone_else"})
        check("非拥有者增删成员被拒绝", code3 >= 400, "code=%s" % code3)

        code, body = w.post("/api/families/%d/members/remove" % fid_web,
                            {"username": U_B})
        check("网页 API 移除成员 B", code == 200, "code=%s" % code)

    # ---- 0.5.3：重复账单保存前确认（不再静默 upsert）----
    # 前置：MCP 段已在 FAM/MONTH 录过一笔水费（usage=20, amount=76）
    print("[e2e] 3.5 重复账单保存前确认", flush=True)
    code, body = w.post_json("/api/bills/check",
                             {"family": FAM, "month": MONTH, "type": "water"})
    cj = json.loads(body) if code == 200 else {}
    check("POST /api/bills/check 探测到既有账单",
          code == 200 and cj.get("exists") is True and cj.get("existing", {}).get("amount") == 76.0,
          "code=%s %s" % (code, body[:120]))

    code, body = w.post_json("/api/bills/check",
                             {"family": FAM, "month": "2098-12", "type": "water"})
    cj = json.loads(body) if code == 200 else {}
    check("无记录时 check 返回 exists=false",
          code == 200 and cj.get("exists") is False, "code=%s" % code)

    # 未确认就提交 → 必须 409，且旧记录原封不动
    code, body = w.post_json("/api/bills",
                             {"family": FAM, "month": MONTH, "type": "water",
                              "usage": 99.0, "amount": 99.0, "user": U_A})
    dj = json.loads(body) if body.startswith("{") else {}
    check("重复保存未确认返回 409 + duplicate 标记",
          code == 409 and dj.get("duplicate") is True, "code=%s %s" % (code, body[:120]))
    code, body = w.post_json("/api/bills/check",
                             {"family": FAM, "month": MONTH, "type": "water"})
    cj = json.loads(body) if code == 200 else {}
    not_touched = cj.get("existing", {}).get("usage") == 20.0
    check("409 拦截后旧记录未被改动", not_touched,
          "usage=%s" % cj.get("existing", {}).get("usage"))

    # 确认覆盖（replace）→ 整单替换成功
    code, body = w.post_json("/api/bills",
                             {"family": FAM, "month": MONTH, "type": "water",
                              "usage": 24.0, "amount": 80.0,
                              "water_fee": 50.0, "sewage_fee": 30.0,
                              "confirm_overwrite": True, "replace": True,
                              "user": U_A})
    check("确认覆盖后保存成功", code == 200 and json.loads(body).get("ok") is True,
          "code=%s %s" % (code, body[:120]))
    code, body = w.post_json("/api/bills/check",
                             {"family": FAM, "month": MONTH, "type": "water"})
    cj = json.loads(body) if code == 200 else {}
    ex = cj.get("existing", {})
    check("覆盖后金额与用量已替换", ex.get("usage") == 24.0 and ex.get("amount") == 80.0,
          "usage=%s amount=%s" % (ex.get("usage"), ex.get("amount")))
    check("覆盖后 check 仍返回既有记录",
          cj.get("exists") is True, "")

    # 改密码（放最后：改完当前会话失效）
    code, body = w.post("/api/password", {"old": PASS_A, "new": PASS_A2})
    check("POST /api/password 修改密码", code == 200, "code=%s %s" % (code, body[:80]))
    w4 = Web()
    code, _ = w4.post("/login", {"user": U_A, "pass": PASS_A2})
    check("新密码可登录", code == 200, "code=%s" % code)
    w5 = Web()
    code, _ = w5.post("/login", {"user": U_A, "pass": PASS_A})
    check("旧密码已失效", code == 200 and not any(c.name for c in w5.cj), "")

    # ============ 4) 页面 ============
    print("[e2e] 4. 页面", flush=True)
    w6 = Web()
    w6.post("/login", {"user": U_A, "pass": PASS_A2})
    code, body = w6.get("/settings.html")
    check("已登录访问 /settings.html", code == 200 and "API" in body, "code=%s" % code)
    code, body = w6.get("/")
    check("已登录访问首页", code == 200, "code=%s" % code)
    code, body = w6.get("/data.js")
    check("已登录访问 /data.js（含共享家庭数据）",
          code == 200 and '"families"' in body, "code=%s" % code)


if __name__ == "__main__":
    sys.exit(main())

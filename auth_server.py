#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 站点认证网关（0.4.1 双后端版：Cookie 会话 + Bearer Token + Basic 兼容）
监听 127.0.0.1:8099，nginx 反代全部请求到此：
  - POST /register  注册新用户（users 表存 PBKDF2 哈希），成功即登录
  - POST /login      校验 users 表用户名密码，种 180 天 HttpOnly Cookie，302 到 /
  - POST /logout     清除 Cookie 与 token
  - POST /mcp        MCP Streamable HTTP 端点（JSON-RPC 2.0，复用 MCP 工具层），
                     鉴权与普通 API 一致：Bearer <API Key> / Basic / Cookie。
                     前端与 MCP 共用 nginx :8089 同一端口，域名只需转发一个端口
  - GET  /data.js    按当前会话用户动态导出数据（window.UTILITY_DATA = {...}）
  - 其它 GET         校验 Cookie / Bearer / Basic，通过则返回 site/ 静态文件，
                     否则页面请求回 login.html、脚本请求回 401

凭据说明：
  - 登录/注册基于 users 表（password_hash，PBKDF2-SHA256）
  - 仓库内不含任何真实密码；本地 auth_config.json 仅用于 0.2 迁移脚本创建初始用户
  - 后端：SQLite 默认 / MySQL 可选（UL_BACKEND + 运行目录 db_config.json）
  - 路径：静态模板取自源码 site/（随仓库），运行时数据（data/、db、日志、配置）位于
    运行目录 APP_DIR（UL_APP_DIR 优先 → UL_ROOT → 仓库根）
会话/API token 持久化于 api_tokens 表（绑定 user_id）
"""
import base64
import email.parser
import email.policy
import hashlib
import json
import os
import re
import secrets
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import db_backend  # noqa: E402

APP_DIR = db_backend.resolve_app_dir()
DB_PATH = os.environ.get("UL_DB", str(APP_DIR / "data" / "utility.db"))
ROOT = Path(__file__).resolve().parent / "site"   # 源码静态模板（随仓库）
SCRIPTS = str(Path(__file__).resolve().parent / "scripts")
sys.path.insert(0, SCRIPTS)  # 幂等
from utility import __version__, dump_json, user_id_by_name  # noqa: E402
import mcp_server  # noqa: E402  （MCP 工具层：/mcp 端点复用其 handle() 与工具声明）
import bill_parser  # noqa: E402  （0.5.0 账单上传识别）

COOKIE_NAME = "ul_token"
COOKIE_MAX_AGE = 15552000  # 180 天
SESSION_LIFE = 180 * 24 * 3600

_lock = threading.Lock()


def get_conn():
    return db_backend.get_conn()


# ---------------- 建表（auth 相关，按后端方言） ----------------

def ensure_auth_tables():
    """确保 users / api_tokens / user_settings 存在（启动时调用）"""
    conn = get_conn()
    try:
        if db_backend.get_backend() == "mysql":
            ddl = """
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT NOT NULL AUTO_INCREMENT,
                username VARCHAR(64) NOT NULL,
                password_hash VARCHAR(512) NOT NULL,
                display_name VARCHAR(128),
                created_at DATETIME NOT NULL DEFAULT NOW(),
                is_active TINYINT NOT NULL DEFAULT 1,
                PRIMARY KEY (id), UNIQUE KEY uq_users_username (username)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            CREATE TABLE IF NOT EXISTS api_tokens (
                id BIGINT NOT NULL AUTO_INCREMENT,
                user_id BIGINT NOT NULL,
                token VARCHAR(255) NOT NULL,
                scope VARCHAR(32) NOT NULL DEFAULT 'bill:write',
                expires_at VARCHAR(32),
                created_at DATETIME NOT NULL DEFAULT NOW(),
                last_used VARCHAR(32),
                PRIMARY KEY (id), UNIQUE KEY uq_api_tokens_token (token)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id BIGINT NOT NULL PRIMARY KEY,
                model_api_base VARCHAR(512),
                model_api_key TEXT,
                model_name VARCHAR(128),
                theme VARCHAR(16) DEFAULT 'light',
                updated_at VARCHAR(32)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """
        else:
            ddl = """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name  TEXT,
                created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                is_active     INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS api_tokens (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL REFERENCES users(id),
                token      TEXT NOT NULL UNIQUE,
                scope      TEXT NOT NULL DEFAULT 'bill:write',
                expires_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                last_used  TEXT
            );
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id         INTEGER PRIMARY KEY REFERENCES users(id),
                model_api_base  TEXT,
                model_api_key   TEXT,
                model_name      TEXT,
                theme           TEXT DEFAULT 'light',
                updated_at      TEXT
            );
            """
        conn.executescript(ddl)
        conn.commit()
    finally:
        conn.close()


# ---------------- 用户与 Token 存取 ----------------

def db_user_by_name(username):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    finally:
        conn.close()


def db_user_by_id(uid):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    finally:
        conn.close()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return f"pbkdf2_sha256$120000${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(iters))
        return secrets.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def create_user(username, password, display_name=None):
    if db_user_by_name(username) is not None:
        return False, "用户名已存在"
    if not password or len(password) < 4:
        return False, "密码至少 4 位"
    conn = get_conn()
    try:
        conn.execute("INSERT INTO users(username, password_hash, display_name) VALUES (?,?,?)",
                     (username, hash_password(password), display_name or username))
        conn.commit()
        return True, ""
    finally:
        conn.close()


def issue_token(user_id, scope="session"):
    token = secrets.token_urlsafe(32)
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO api_tokens(user_id, token, scope, expires_at) VALUES (?,?,?,?)",
            (user_id, token, scope,
             time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + SESSION_LIFE))))
        conn.commit()
        conn.close()
    return token


def revoke_token(token):
    if not token:
        return
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM api_tokens WHERE token=?", (token,))
        conn.commit()
        conn.close()


# ---------------- 长期 API Key（供技能 / 外部脚本调用）----------------
#
# 与网页 session 区分：session 存在同一张 api_tokens 表但 scope='session'、
# 带过期时间；API key 为 scope='api' 且不过期。
# 重置 API key 只删 scope='api' 的记录，不会把用户从网页踢下线。

API_SCOPE = "api"


def issue_api_token(user_id):
    """为指定用户新建一个长期 API key（scope='api'，不过期）"""
    token = secrets.token_urlsafe(32)
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO api_tokens(user_id, token, scope, expires_at) VALUES (?,?,?,NULL)",
            (user_id, token, API_SCOPE))
        conn.commit()
        conn.close()
    return token


def list_api_tokens(user_id):
    """列出该用户的 API key（不含明文，只给前缀与元信息）"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, token, created_at, last_used FROM api_tokens "
            "WHERE user_id=? AND scope=? ORDER BY id DESC",
            (user_id, API_SCOPE)).fetchall()
        out = []
        for r in rows:
            t = r["token"] or ""
            out.append({
                "id": r["id"],
                # 只展示前缀，避免完整凭据出现在页面/日志/截图里
                "prefix": (t[:6] + "…" + t[-4:]) if len(t) > 12 else "…",
                "created_at": r["created_at"],
                "last_used": r["last_used"],
            })
        return out
    finally:
        conn.close()


def reset_api_token(user_id):
    """吊销该用户全部 API key 并新建一个，返回明文（仅此一次可见）"""
    with _lock:
        conn = get_conn()
        conn.execute("DELETE FROM api_tokens WHERE user_id=? AND scope=?",
                     (user_id, API_SCOPE))
        conn.commit()
        conn.close()
    return issue_api_token(user_id)


def change_password(user_id, old_password, new_password):
    """修改密码。校验旧密码，成功后吊销该用户全部 session（强制重新登录）。

    返回 (ok, message)。
    """
    if not new_password or len(new_password) < 6:
        return False, "新密码至少 6 位"
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            return False, "用户不存在"
        if not verify_password(old_password, row["password_hash"]):
            return False, "原密码不正确"
        if verify_password(new_password, row["password_hash"]):
            return False, "新密码不能与原密码相同"
    finally:
        conn.close()

    new_hash = hash_password(new_password)
    with _lock:
        conn = get_conn()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
        # 改密后所有会话失效，避免旧会话被继续使用
        conn.execute("DELETE FROM api_tokens WHERE user_id=? AND scope<>?",
                     (user_id, API_SCOPE))
        conn.commit()
        conn.close()
    return True, "密码已修改，请重新登录"


def token_user(token, scopes=None):
    """token -> (user_id, username)；无效 / 停用 / scope 不符返回 None

    scopes=None 表示不限制 scope（仅供内部确认 token 是否存在时使用）；
    网页 Cookie 只接受 scope='session'，API / MCP 的 Bearer 接受
    scope='api' 与 'session'。

    0.5.2 之前这里完全不校验 scope —— `api_tokens.scope` 全仓库只有写入、
    没有读取，长期 API Key 与网页会话完全等价（误导性设计）。
    """
    if not token:
        return None
    conn = get_conn()
    try:
        sql = ("SELECT t.user_id, u.username FROM api_tokens t JOIN users u ON t.user_id=u.id "
               "WHERE t.token=? AND u.is_active=1 "
               "AND (t.expires_at IS NULL OR t.expires_at > datetime('now','localtime'))")
        args = [token]
        if scopes:
            sql += " AND t.scope IN (%s)" % ",".join("?" * len(scopes))
            args += list(scopes)
        # u.is_active=1：账号停用后，已签发的 token 立即失效
        row = conn.execute(sql, tuple(args)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE api_tokens SET last_used=datetime('now','localtime') WHERE token=?", (token,))
        conn.commit()
        return row["user_id"], row["username"]
    finally:
        conn.close()


# ---------------- 鉴权 ----------------

# 网页会话 token 的 scope；API Key 走 Bearer，见 API_SCOPE
SESSION_SCOPES = ("session",)
# Bearer 通道：长期 API Key 与网页会话都接受（脚本/技能两种用法都要照顾）
BEARER_SCOPES = ("api", "session")


def auth_from_cookie(headers):
    cookie = headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(COOKIE_NAME + "="):
            # Cookie 只认会话 token：API Key 不该被当成网页会话用
            return token_user(part[len(COOKIE_NAME) + 1:], SESSION_SCOPES)
    return None


def auth_from_bearer(headers):
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return token_user(auth.split(" ", 1)[1].strip(), BEARER_SCOPES)
    return None


def auth_from_basic(headers):
    auth = headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        u, p = raw.split(":", 1)
    except Exception:
        return None
    row = db_user_by_name(u)
    # is_active：停用账号不得通过 Basic 通道登录
    if row is None or not row["is_active"] or not verify_password(p, row["password_hash"]):
        return None
    return row["id"], row["username"]


def current_user(headers):
    """按 Cookie / Bearer / Basic 依次鉴权，返回 (user_id, username) 或 None"""
    return (auth_from_cookie(headers)
            or auth_from_bearer(headers)
            or auth_from_basic(headers))


# ---------------- 页面与静态服务 ----------------

def send_login_page(handler):
    """渲染登录页。错误提示由页面 JS 读 query string 自行渲染。

    早期版本这里有个 `body.replace(b"__ERR__", err)` 的分支，而 login.html 里
    根本没有 `__ERR__` 占位符（用的是 JS 读 `?err=`）—— 属于永不生效的死代码，
    已删除（0.5.2）。
    """
    html = ROOT / "login.html"
    if html.exists():
        body = html.read_bytes()
    else:
        body = b"<html><body>Login required</body></html>"
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def send_data_js(handler, uid, username):
    data = dump_json(username)
    row = db_user_by_id(uid)
    data["user"] = {
        "id": uid,
        "username": username,
        "display_name": row["display_name"] if row else username,
    }
    js = "window.UTILITY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    body = js.encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/javascript; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _json_default(o):
    """json.dumps 兜底：datetime → 'YYYY-MM-DD HH:MM:SS'，其余转字符串"""
    import datetime as _dt
    if isinstance(o, (_dt.datetime, _dt.date)):
        return o.isoformat(sep=" ") if isinstance(o, _dt.datetime) else o.isoformat()
    return str(o)


def _is_within(path, root):
    """判断 path 是否位于 root 之内（含 root 本身）。

    不能用 str.startswith()：站点目录名为 `site` 时，兄弟目录 `site_backup/`
    同样满足前缀匹配，会被路径穿越绕过。用 os.path.commonpath 做真实边界判断。
    """
    try:
        return os.path.commonpath([str(path), str(root)]) == str(root)
    except ValueError:
        # 不同盘符 / 相对与绝对路径混用时无法比较，视为越界
        return False


# 允许读取的额外根目录（运行期产物所在处，不在站点目录内）
# 账单截图放在 <APP_DIR>/images/，站点通过 site/images 软链访问。
# 软链指向站点目录之外，若按解析后的真实路径做边界检查会被误判越界，
# 故这里显式白名单化 —— 只放行 images 目录，不放开整个运行目录。
EXTRA_ROOTS = (APP_DIR / "images",)


def _decode_path(raw):
    """URL 路径解码：把 %XX 转成原始字符。

    必须解码，否则中文文件名（账单截图如「202610-水费-…jpg」）无法命中磁盘文件。
    解码后仍由 serve_static 做边界检查，因此 %2e%2e%2f 这类编码过的穿越
    会在解码后被 normpath 折叠并被 _is_within 拦下。
    """
    try:
        return urllib.parse.unquote(raw, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return raw


def serve_static(handler, path):
    # 路径规范化，防 ../ 跳出
    norm = os.path.normpath(_decode_path(path).lstrip("/"))
    # 用 abspath 而非 resolve()：保留软链结构，才能识别 site/images → images/ 的映射
    full = Path(os.path.abspath(ROOT / norm))
    # 边界检查基于「未解析软链」的路径 + 软链目标的白名单，二者取其一通过即可
    roots = [ROOT.resolve()] + [r.resolve() for r in EXTRA_ROOTS if r.exists()]
    if not any(_is_within(full, r) for r in roots):
        handler.send_error(404)
        return
    if not full.exists() or full.is_dir():
        handler.send_error(404)
        return
    # 软链目标还需单独校验：确保最终落在白名单内（防 site/images 软链被指到别处）
    real = full.resolve()
    if not any(_is_within(real, r) for r in roots):
        handler.send_error(404)
        return
    import mimetypes
    ctype = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
    body = full.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    if full.suffix in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico"):
        handler.send_header("Cache-Control", "public, max-age=604800")
    elif full.suffix == ".js":
        handler.send_header("Cache-Control", "no-cache, must-revalidate")
    handler.end_headers()
    handler.wfile.write(body)


def set_session_cookie(handler, token):
    handler.send_header("Set-Cookie",
                        f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={COOKIE_MAX_AGE}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _read_form(self):
        raw_len = self.headers.get("Content-Length")
        try:
            length = int(raw_len) if raw_len else 0
        except (TypeError, ValueError):
            self.close_connection = True
            self.send_error(400, "invalid Content-Length")
            return {}
        # 负数会让 rfile.read(-1) 阻塞到 EOF，占住工作线程；
        # 超长时不消费 body 会导致请求走私（残留字节被当作下一个请求解析）
        if length < 0 or length > 65536:
            self.close_connection = True
            self.send_error(413, "Content-Length out of range")
            return {}
        raw = self.rfile.read(length) if length else b""
        try:
            return urllib.parse.parse_qs(raw.decode("utf-8"))
        except Exception:
            return {}

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]

        # 账单上传识别 / 手工录入（0.5.0，需登录；在 _read_form 之前处理，
        # 因为它们分别是 multipart 与 JSON body）
        if path == "/api/bills/upload":
            user = current_user(self.headers)
            if not user:
                self._json_err("未登录", 401)
                return
            self._handle_bill_upload(user[0], user[1])
            return
        if path == "/api/bills":
            user = current_user(self.headers)
            if not user:
                self._json_err("未登录", 401)
                return
            self._handle_bill_save(user[1])
            return

        # MCP Streamable HTTP 端点（与前端共用 8089 端口，鉴权同 API）
        if path == "/mcp":
            self._handle_mcp()
            return

        # 用户管理 / 共享管理 API（需登录）
        if path.startswith("/api/"):
            user = current_user(self.headers)
            if not user:
                self._json_err("未登录", 401)
                return
            self._handle_api_post(path, user[0], user[1])
            return

        if path not in ("/login", "/logout", "/register"):
            self.send_error(404)
            return
        form = self._read_form()

        if path == "/login":
            u = (form.get("user") or [""])[0]
            p = (form.get("pass") or [""])[0]
            row = db_user_by_name(u)
            if row is not None and row["is_active"] and verify_password(p, row["password_hash"]):
                token = issue_token(row["id"])
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                set_session_cookie(self, token)
                self.end_headers()
            else:
                self._redirect("/login.html?err=1")

        elif path == "/register":
            u = (form.get("user") or [""])[0].strip()
            p = (form.get("pass") or [""])[0]
            dn = (form.get("display_name") or [""])[0].strip() or None
            ok, msg = create_user(u, p, dn)
            if ok:
                row = db_user_by_name(u)
                token = issue_token(row["id"])
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                set_session_cookie(self, token)
                self.end_headers()
            else:
                self._redirect("/login.html?err=2&msg=" + urllib.parse.quote(msg))

        else:  # /logout
            cookie = self.headers.get("Cookie", "")
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith(COOKIE_NAME + "="):
                    revoke_token(part[len(COOKIE_NAME) + 1:])
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.send_header("Content-Length", "0")
            self.send_header("Set-Cookie",
                             f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.end_headers()

    # ---------------- 用户管理 / 家庭共享 API ----------------
    # 全部要求已登录（Cookie / Bearer / Basic 任一通道）。
    # 响应一律 JSON；失败用相应 HTTP 状态码，便于前端区分。

    def _json(self, obj, status=200):
        # MySQL 后端返回的 DATETIME 是 datetime 对象，SQLite 是字符串 ——
        # 直接用 json.dumps 会在 MySQL 下抛 TypeError（SQLite 环境测不出来）。
        # 这里统一兜底序列化，保证双后端行为一致。
        body = json.dumps(obj, ensure_ascii=False, default=_json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json_err(self, msg, status=400):
        self._json({"ok": False, "error": msg}, status)

    # ---------------- MCP Streamable HTTP 端点 ----------------
    # 复用 scripts/mcp_server.py 的工具层（同一份工具声明与实现），
    # 鉴权复用 current_user 三通道。已认证用户名强制覆盖工具参数里的
    # user 字段（防止登录用户冒充他人），见 mcp_server.set_request_user。

    MCP_MAX_BODY = 1 << 20  # 1MB，JSON-RPC 消息足够大，防滥用

    def _mcp_202(self):
        # 全部为通知（无 id）→ 202 Accepted 无响应体（Streamable HTTP 规范）
        self.send_response(202)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_mcp(self):
        user = current_user(self.headers)
        if not user:
            self._json_err("未登录：请携带 Authorization: Bearer <API Key> "
                           "（网页「设置」中重置获取）", 401)
            return

        raw_len = self.headers.get("Content-Length")
        try:
            length = int(raw_len) if raw_len else 0
        except (TypeError, ValueError):
            self.close_connection = True
            self._json_err("invalid Content-Length", 400)
            return
        if length < 0 or length > self.MCP_MAX_BODY:
            self.close_connection = True
            self._json_err("Content-Length out of range", 413)
            return
        raw = self.rfile.read(length) if length else b""

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._json({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": f"解析失败: {e}"}}, 400)
            return

        if not isinstance(payload, (dict, list)):
            self._json({"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32600, "message": "无效请求"}},
                       400)
            return

        mcp_server.set_request_user(user[1])
        try:
            if isinstance(payload, list):
                # JSON-RPC batch（MCP Streamable HTTP 允许）
                responses = []
                for msg in payload:
                    if not isinstance(msg, dict):
                        continue
                    try:
                        r = mcp_server.handle(msg)
                    except Exception:
                        traceback.print_exc()
                        r = {"jsonrpc": "2.0", "id": msg.get("id"),
                             "error": {"code": -32603, "message": "内部错误"}}
                    if r is not None:
                        responses.append(r)
                if responses:
                    self._json(responses)
                else:
                    self._mcp_202()
            else:
                try:
                    r = mcp_server.handle(payload)
                except Exception:
                    traceback.print_exc()
                    r = {"jsonrpc": "2.0", "id": payload.get("id"),
                         "error": {"code": -32603, "message": "内部错误"}}
                if r is None:
                    self._mcp_202()
                else:
                    self._json(r)
        finally:
            mcp_server.set_request_user(None)

    def _handle_api_get(self, path, uid, username):
        import utility as U

        if path == "/api/me":
            conn = get_conn()
            try:
                row = conn.execute(
                    "SELECT id, username, display_name, created_at FROM users WHERE id=?",
                    (uid,)).fetchone()
            finally:
                conn.close()
            self._json({"ok": True, "user": dict(row) if row else {"id": uid,
                                                                  "username": username}})
            return

        if path == "/api/tokens":
            toks = list_api_tokens(uid)
            # 新注册的用户还没有 API Key。与其让设置页空着、逼用户猜要「重置」，
            # 首次访问时直接签发一把，并把明文随这次响应一并返回（仅此一次）。
            # 列表接口平时只回前缀，绝不回明文 —— 明文只在这一条路径上出现。
            plaintext = None
            if not toks:
                plaintext = reset_api_token(uid)
                toks = list_api_tokens(uid)
            self._json({"ok": True, "tokens": toks,
                        "one_time_plaintext": plaintext})
            return

        if path == "/api/families":
            try:
                fams = U.list_families(username)
            except SystemExit:
                fams = []
            # 标注当前用户对该家庭的可管理性（仅拥有者可增删成员）
            for f in fams:
                f["can_manage_members"] = (f.get("role") == "owner")
            self._json({"ok": True, "families": fams})
            return

        # /api/families/<id>/members
        m = re.match(r"^/api/families/(\d+)/members$", path)
        if m:
            try:
                rows = U.list_family_members(int(m.group(1)), username)
            except SystemExit:
                rows = []
            if not rows:
                self._json_err("家庭不存在或你不是该家庭成员", 404)
                return
            self._json({"ok": True, "members": rows})
            return

        if path == "/api/users":
            # 供共享时选择目标用户；只暴露用户名，不含任何凭据
            conn = get_conn()
            try:
                rows = conn.execute(
                    "SELECT username, display_name FROM users WHERE is_active=1 ORDER BY id"
                ).fetchall()
            finally:
                conn.close()
            self._json({"ok": True,
                        "users": [dict(r) for r in rows if r["username"] != username]})
            return

        self._json_err("未知接口", 404)

    # ---------------- 账单上传识别 / 手工录入（0.5.0） ----------------
    # 行业惯例：两步式 —— 先上传解析出「草稿」（不落库），人工核对后确认入库；
    # 确认入口 POST /api/bills 同时服务手工录入，复用 MCP 工具层做校验与 upsert。

    UPLOAD_MAX = 20 << 20  # 20MB
    IMAGE_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                  "webp": "image/webp", "gif": "image/gif"}

    def _read_raw(self, limit):
        raw_len = self.headers.get("Content-Length")
        try:
            length = int(raw_len) if raw_len else 0
        except (TypeError, ValueError):
            self.close_connection = True
            self._json_err("invalid Content-Length", 400)
            return None
        if length <= 0 or length > limit:
            self.close_connection = True
            self._json_err(f"请求体大小超出限制（> {limit // (1 << 20)}MB）", 413)
            return None
        return self.rfile.read(length)

    def _parse_multipart(self, body):
        """解析 multipart/form-data，返回 (fields, files)。

        用标准库 email 包解析：浏览器上传的二进制 part 无 CTE，
        get_payload(decode=True) 会原样返回字节（base64/QP 则自动解码）。
        """
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return None, None
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + ctype.encode("latin-1") +
            b"\r\nMIME-Version: 1.0\r\n\r\n" + body)
        fields, files = {}, []
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            filename = part.get_filename()
            if filename:
                files.append({"filename": filename, "data": payload})
            else:
                fields[name or ""] = payload.decode("utf-8", "replace").strip()
        return fields, files

    def _handle_bill_upload(self, uid, username):
        body = self._read_raw(self.UPLOAD_MAX)
        if body is None:
            return
        fields, files = self._parse_multipart(body)
        if fields is None:
            self._json_err("Content-Type 必须为 multipart/form-data", 400)
            return
        if not files:
            self._json_err("缺少文件字段", 400)
            return
        f = files[0]
        suffix = f["filename"].rsplit(".", 1)[-1].lower() \
            if "." in f["filename"] else ""
        safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_",
                      f["filename"]).strip() or "bill"
        dest_dir = Path(APP_DIR) / "images" / "uploads"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_{safe}"
        dest.write_bytes(f["data"])
        image_rel = f"uploads/{dest.name}"
        print(f"[upload] user={username} file={dest.name} "
              f"size={len(f['data'])}", flush=True)

        draft = bill_parser.parse_bill_file(str(dest), f["filename"])
        if draft.get("message") == "__IMAGE__":
            # 图片：本地不做 OCR，尝试设置页配置的视觉模型（OpenAI 兼容）
            draft["message"] = "图片账单："
            row = None
            conn = get_conn()
            try:
                row = conn.execute(
                    "SELECT model_api_base, model_api_key, model_name "
                    "FROM user_settings WHERE user_id=?", (uid,)).fetchone()
            finally:
                conn.close()
            model_conf = dict(row) if row else {}
            if model_conf.get("model_api_base") and model_conf.get("model_api_key"):
                fields = bill_parser.parse_image_via_model(
                    str(dest), model_conf["model_api_base"],
                    model_conf["model_api_key"], model_conf.get("model_name"),
                    self.IMAGE_MIME.get(suffix, "image/png"))
                if fields:
                    btype = fields.pop("bill_type", None) or fields.pop("type", None)
                    draft["bill"] = fields
                    draft["bill_type"] = btype if btype in (
                        "water", "electric", "gas") else None
                    core = fields.get("month") and fields.get("usage") is not None \
                        and fields.get("amount") is not None
                    draft["parse_ok"] = bool(core and btype)
                    draft["confidence"] = "medium"
                    draft["message"] = ("模型识别完成，请核对后保存" if draft["parse_ok"]
                                        else "模型已识别部分字段，请补全后保存")
                else:
                    draft["message"] = ("模型识别失败，请手工填写后保存"
                                        "（附件已保存，可对照填写）")
            else:
                draft["message"] = ("图片暂不能本地识别：可在「设置 → 模型 API」配置视觉"
                                    "模型后自动识别，或对照图片手工填写（附件已保存）")

        self._json({"ok": True, "file": image_rel, "draft": draft})

    def _handle_bill_save(self, username):
        """确认入库：JSON body（add_bill 兼容字段）→ 复用 MCP 工具层校验 + upsert"""
        body = self._read_raw(256 * 1024)
        if body is None:
            return
        try:
            args = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._json_err(f"JSON 解析失败: {e}", 400)
            return
        if not isinstance(args, dict):
            self._json_err("请求体必须是 JSON 对象", 400)
            return
        args.pop("user", None)  # 网页通道一律以已登录用户入库，防冒充

        mcp_server.set_request_user(username)
        try:
            result = mcp_server.tool_add_bill(args)
        finally:
            mcp_server.set_request_user(None)
        text = result["content"][0]["text"] if result.get("content") else ""
        if result.get("isError"):
            self._json_err(text or "录入失败", 400)
            return
        saved = None
        try:
            saved = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        self._json({"ok": True, "message": "已保存", "bill": saved})

    def _handle_api_post(self, path, uid, username):
        import utility as U

        # 新建家庭（JSON {name}；网页上传流程里「新建家庭」也用这个接口）
        if path == "/api/families":
            body = self._read_raw(8192)
            if body is None:
                return
            try:
                data = json.loads(body.decode("utf-8"))
                name = (data.get("name") or "").strip()
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                name = ""
            if not name:
                self._json_err("缺少家庭名 name")
                return
            try:
                result = U.add_family(name, username)
            except SystemExit:
                self._json_err(f"家庭「{name}」已存在或名称不合法", 400)
                return
            created = result[1] if isinstance(result, (list, tuple)) else None
            if not created:
                self._json_err(f"家庭「{name}」已存在", 400)
                return
            self._json({"ok": True, "family": name})
            return

        form = self._read_form()

        def field(k):
            return (form.get(k) or [""])[0].strip()

        if path == "/api/tokens/reset":
            token = reset_api_token(uid)
            # 明文只在此次响应中返回，之后页面只显示前缀
            self._json({"ok": True, "token": token,
                        "note": "请立即复制保存，之后无法再查看完整值"})
            return

        if path == "/api/password":
            ok, msg = change_password(uid, field("old"), field("new"))
            if not ok:
                self._json_err(msg, 400)
                return
            # 会话已全部失效，清掉当前 Cookie
            body = json.dumps({"ok": True, "message": msg},
                              ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie",
                             f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.end_headers()
            self.wfile.write(body)
            return

        m = re.match(r"^/api/families/(\d+)/members$", path)
        if m:
            target = field("username")
            if not target:
                self._json_err("缺少 username")
                return
            try:
                ok, msg = U.share_family(int(m.group(1)), target, username)
            except SystemExit:
                ok, msg = False, "无权操作"
            if not ok:
                self._json_err(msg, 400)
                return
            self._json({"ok": True, "message": msg})
            return

        m = re.match(r"^/api/families/(\d+)/members/remove$", path)
        if m:
            target = field("username")
            if not target:
                self._json_err("缺少 username")
                return
            try:
                ok, msg = U.unshare_family(int(m.group(1)), target, username)
            except SystemExit:
                ok, msg = False, "无权操作"
            if not ok:
                self._json_err(msg, 400)
                return
            self._json({"ok": True, "message": msg})
            return

        self._json_err("未知接口", 404)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/mcp":
            # MCP 只支持 POST（SSE 流式响应暂不提供）
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path in ("/login", "/logout", "/register"):
            self.send_error(404)
            return
        user = current_user(self.headers)
        if user:
            uid, username = user
            if path == "/data.js":
                send_data_js(self, uid, username)
                return
            if path.startswith("/api/"):
                self._handle_api_get(path, uid, username)
                return
            serve_static(self, path if path != "/" else "/index.html")
            return
        # 未登录：API 一律 401 JSON；脚本/数据类 401；页面类回登录页
        if path.startswith("/api/"):
            self._json_err("未登录", 401)
            return
        if path.endswith((".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="UtilityLog Private"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            # 登录页的错误提示由页面 JS 读 query string 渲染，服务端无需再算一遍
            # （早期版本在服务端拼 err 文本再替换占位符，而占位符并不存在，属死代码）
            send_login_page(self)


class UtilityHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer 的 accept 队列默认只有 5，
    多用户同时打开看板（每页多个 /data.js + 图片请求）会触发内核 RST 重置连接。
    提到 128 后实测 80 并发全部成功。"""

    request_queue_size = 128
    daemon_threads = True


if __name__ == "__main__":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    ensure_auth_tables()
    # 端口可用 UL_AUTH_PORT 覆盖（跨平台部署常见：Windows/服务器上 8099 可能被占用）
    port = int(os.environ.get("UL_AUTH_PORT") or 8099)
    server = UtilityHTTPServer(("127.0.0.1", port), Handler)
    # 版本号单一来源：scripts/utility.py 的 __version__（0.5.2 起，避免多处各写各的）
    print(f"UtilityLog auth gateway ({__version__}, backend={db_backend.get_backend()}) "
          f"listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()

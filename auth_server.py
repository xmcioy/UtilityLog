#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 站点认证网关（0.3.1 双后端版：Cookie 会话 + Bearer Token + Basic 兼容）
监听 127.0.0.1:8099，nginx 反代全部请求到此：
  - POST /register  注册新用户（users 表存 PBKDF2 哈希），成功即登录
  - POST /login      校验 users 表用户名密码，种 180 天 HttpOnly Cookie，302 到 /
  - POST /logout     清除 Cookie 与 token
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
import hashlib
import json
import os
import secrets
import sys
import threading
import time
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
from utility import dump_json, user_id_by_name  # noqa: E402

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


def token_user(token):
    """token -> (user_id, username)；无效返回 None"""
    if not token:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT t.user_id, u.username FROM api_tokens t JOIN users u ON t.user_id=u.id "
            "WHERE t.token=? AND (t.expires_at IS NULL OR t.expires_at > datetime('now','localtime'))",
            (token,)).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE api_tokens SET last_used=datetime('now','localtime') WHERE token=?", (token,))
        conn.commit()
        return row["user_id"], row["username"]
    finally:
        conn.close()


# ---------------- 鉴权 ----------------

def auth_from_cookie(headers):
    cookie = headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(COOKIE_NAME + "="):
            return token_user(part[len(COOKIE_NAME) + 1:])
    return None


def auth_from_bearer(headers):
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return token_user(auth.split(" ", 1)[1].strip())
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
    if row is None or not verify_password(p, row["password_hash"]):
        return None
    return row["id"], row["username"]


def current_user(headers):
    """按 Cookie / Bearer / Basic 依次鉴权，返回 (user_id, username) 或 None"""
    return (auth_from_cookie(headers)
            or auth_from_bearer(headers)
            or auth_from_basic(headers))


# ---------------- 页面与静态服务 ----------------

def send_login_page(handler, err=None):
    html = ROOT / "login.html"
    if html.exists():
        body = html.read_bytes()
    else:
        body = b"<html><body>Login required</body></html>"
    if err:
        body = body.replace(b"__ERR__", err.encode("utf-8"))
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


def serve_static(handler, path):
    # 路径规范化，防 ../ 跳出
    norm = os.path.normpath(path.lstrip("/"))
    full = (ROOT / norm).resolve()
    if not str(full).startswith(str(ROOT.resolve())) or not full.exists() or full.is_dir():
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
        length = int(self.headers.get("Content-Length") or 0)
        if length > 65536:
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

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/login", "/logout", "/register"):
            self.send_error(404)
            return
        user = current_user(self.headers)
        if user:
            uid, username = user
            if path == "/data.js":
                send_data_js(self, uid, username)
                return
            serve_static(self, path if path != "/" else "/index.html")
            return
        # 未登录：脚本/数据类返回 401，页面类回登录页
        if path.endswith((".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="UtilityLog Private"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            err = None
            if path == "/login.html" and "err=1" in self.path:
                err = "用户名或密码错误，请重试"
            elif path == "/login.html" and "err=2" in self.path:
                qs = urllib.parse.parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
                err = "注册失败：" + (qs.get("msg", [""])[0] or "用户名已存在")
            send_login_page(self, err)


if __name__ == "__main__":
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    ensure_auth_tables()
    server = ThreadingHTTPServer(("127.0.0.1", 8099), Handler)
    print(f"UtilityLog auth gateway (0.3, backend={db_backend.get_backend()}) listening on 127.0.0.1:8099", flush=True)
    server.serve_forever()

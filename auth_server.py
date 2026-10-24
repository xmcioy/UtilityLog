#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 站点认证网关（Cookie 长期登录 + Basic Auth 兼容）
监听 127.0.0.1:8099，nginx 反代全部请求到此：
  - POST /login    校验用户名密码，种 180 天 HttpOnly Cookie，302 到 /
  - POST /logout   清除 Cookie 与 token
  - 其它 GET       校验 Cookie 或 Basic 头，通过则返回 site/ 静态文件，
                   否则页面请求回 login.html、脚本请求回 401

凭据配置（三选一，优先级从高到低）：
  1. 环境变量 UL_USER / UL_PASS
  2. 项目根目录 auth_config.json（{"user": "...", "pass": "..."}）
  3. 未配置时拒绝所有登录（提示管理员配置）

token 持久化于 <项目根>/.auth_tokens.json
"""
import base64
import json
import os
import secrets
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("UL_ROOT", Path(__file__).resolve().parent))
ROOT = PROJECT_ROOT / "site"
TOKEN_FILE = PROJECT_ROOT / ".auth_tokens.json"
CONFIG_FILE = PROJECT_ROOT / "auth_config.json"

COOKIE_NAME = "ul_token"
COOKIE_MAX_AGE = 15552000  # 180 天
TOKEN_LIFE = 180 * 24 * 3600

_lock = threading.Lock()


def load_credentials():
    """按优先级读取凭据；未配置返回 (None, None)"""
    user = os.environ.get("UL_USER")
    passwd = os.environ.get("UL_PASS")
    if user and passwd:
        return user, passwd
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            user = cfg.get("user")
            passwd = cfg.get("pass")
            if user and passwd:
                return user, passwd
        except Exception:
            pass
    return None, None


USER, PASS = load_credentials()


def load_tokens():
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_tokens(tokens):
    TOKEN_FILE.write_text(json.dumps(tokens))


def is_token_valid(token):
    with _lock:
        tokens = load_tokens()
        exp = tokens.get(token, 0)
        return exp > time.time()


def issue_token():
    token = secrets.token_urlsafe(32)
    with _lock:
        tokens = load_tokens()
        tokens[token] = time.time() + TOKEN_LIFE
        save_tokens(tokens)
    return token


def revoke_token(token):
    with _lock:
        tokens = load_tokens()
        tokens.pop(token, None)
        save_tokens(tokens)


def check_basic(auth_header):
    """Authorization: Basic base64(user:pass)"""
    if not auth_header or not auth_header.startswith("Basic "):
        return False
    if not USER or not PASS:
        return False
    try:
        raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
        u, p = raw.split(":", 1)
        return u == USER and p == PASS
    except Exception:
        return False


def check_cookie(headers):
    cookie = headers.get("Cookie", "")
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(COOKIE_NAME + "="):
            return is_token_valid(part[len(COOKIE_NAME) + 1:])
    return False


def send_login_page(handler, err=False):
    html = ROOT / "login.html"
    if html.exists():
        body = html.read_bytes()
    else:
        body = b"<html><body>Login required</body></html>"
    if err:
        body = body.replace(b"__ERR__", "用户名或密码错误，请重试".encode("utf-8"))
    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
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

    def do_POST(self):
        if self.path.split("?")[0] not in ("/login", "/logout"):
            self.send_error(404)
            return
        form = self._read_form()
        if self.path.split("?")[0] == "/login":
            u = (form.get("user") or [""])[0]
            p = (form.get("pass") or [""])[0]
            if USER and PASS and u == USER and p == PASS:
                token = issue_token()
                self.send_response(302)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie",
                                 f"{COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={COOKIE_MAX_AGE}")
                self.end_headers()
            else:
                self.send_response(302)
                self.send_header("Location", "/login.html?err=1")
                self.end_headers()
        else:  # /logout
            cookie = self.headers.get("Cookie", "")
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith(COOKIE_NAME + "="):
                    revoke_token(part[len(COOKIE_NAME) + 1:])
            self.send_response(302)
            self.send_header("Location", "/login.html")
            self.send_header("Set-Cookie",
                             f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0")
            self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/login", "/logout"):
            self.send_error(404)
            return
        authed = check_cookie(self.headers) or check_basic(self.headers.get("Authorization"))
        if authed:
            serve_static(self, path if path != "/" else "/index.html")
            return
        # 未登录：脚本/数据类返回 401，页面类回登录页
        if path.endswith((".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".css")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="UtilityLog Private"')
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            send_login_page(self, path == "/login.html" and "err=1" in self.path)


if __name__ == "__main__":
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not USER or not PASS:
        print("WARNING: credentials not configured (set UL_USER/UL_PASS or auth_config.json); logins will be rejected", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", 8099), Handler)
    print("UtilityLog auth gateway listening on 127.0.0.1:8099", flush=True)
    server.serve_forever()

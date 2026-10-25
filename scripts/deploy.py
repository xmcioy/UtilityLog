#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 跨平台部署工具（0.5.3，纯标准库，macOS / Linux / Windows 通用）

为什么再写一个 Python 版：`scripts/deploy.sh` 依赖 bash / rsync / launchd / brew，
只在 macOS（部分 Linux）可用。本脚本用标准库做同样的事，三平台一致：

| 平台   | 服务托管                                   | 备注 |
|--------|--------------------------------------------|------|
| macOS  | launchd（~/Library/LaunchAgents/*.plist）  | 失败自动回退后台进程 |
| Linux  | systemd --user（~/.config/systemd/user）   | 无 systemd 时回退后台进程 |
| Windows| 后台进程（DETACHED_PROCESS）                | 附 schtasks 常驻命令示例 |

其它跨平台要点：
  - 源码同步用 shutil（不依赖 rsync）
  - 依赖安装用 `sys.executable -m pip install --user`（不依赖包管理器）
  - 图片软链在 Windows 上退回 junction（mklink /J，无需管理员权限）
  - HTTP 验证用 urllib 且显式禁用代理（环境有 HTTP_PROXY 时 curl 会被劫持）

用法：
  python3 scripts/deploy.py doctor                      # 环境体检（依赖/目录/端口/服务方案）
  python3 scripts/deploy.py install                     # 首次部署（同步 + 依赖 + 建库 + 启动 + 验证）
  python3 scripts/deploy.py upgrade                     # 升级（换程序，保留数据与凭据）
  python3 scripts/deploy.py start|stop|status|verify
  python3 scripts/deploy.py doctor --sim windows        # 模拟其它平台看它会怎么做

环境变量（均可缺省）：
  UL_APP_DIR     运行目录（默认 ~/myapp/utilitylog）
  UL_REPO_DIR    源码仓库（默认本文件所在仓库根）
  UL_AUTH_PORT   auth_server 端口（默认 8099）
  UL_NGINX_PORT  nginx 反代端口（默认 8089，仅验证用）
  UL_SERVICE     auto|launchd|systemd|process|none
  UL_SKIP_DEPS   1 则跳过 pip 安装（离线环境）
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("UL_REPO_DIR") or os.path.dirname(HERE)
PORT = int(os.environ.get("UL_AUTH_PORT", "8099"))
NGINX_PORT = int(os.environ.get("UL_NGINX_PORT", "8089"))
APP_DIR = os.environ.get("UL_APP_DIR") or os.path.join(
    os.path.expanduser("~"), "myapp", "utilitylog")
SERVICE_MODE = os.environ.get("UL_SERVICE", "auto")

# 同步到运行目录时排除的内容（运行数据 / 凭据 / 本机协作文件）
EXCLUDE_DIRS = {".git", "__pycache__", "data", "images", "entries",
                ".agent-sync", ".workbuddy", "node_modules"}
EXCLUDE_FILES = {"db_config.json", "auth_config.json", ".auth_tokens.json",
                 ".htpasswd", "site/data.js", ".auth_server.pid"}
EXCLUDE_SUFFIX = {".log", ".pyc", ".bak", ".tmp"}


def log(msg):
    print(f"[deploy.py] {msg}", flush=True)


def warn(msg):
    print(f"[deploy.py ⚠] {msg}", flush=True)


def die(msg):
    print(f"[deploy.py ✗] {msg}", flush=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# 平台判定
# ---------------------------------------------------------------------------

def current_os(sim=None):
    """返回 'windows' | 'linux' | 'macos'；UL_SIM_OS / --sim 供自测用"""
    sim = sim or os.environ.get("UL_SIM_OS")
    if sim in ("windows", "linux", "macos"):
        return sim
    if os.name == "nt" or sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def plan_service(os_name):
    """按平台给出服务托管方案"""
    if SERVICE_MODE in ("launchd", "systemd", "process", "none"):
        return SERVICE_MODE
    if os_name == "macos" and shutil.which("launchctl"):
        return "launchd"
    if os_name == "linux" and shutil.which("systemctl"):
        return "systemd"
    if os_name == "windows":
        return "process"
    return "process"


# ---------------------------------------------------------------------------
# 环境体检
# ---------------------------------------------------------------------------

def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def http_code(port, path="/", method="GET", timeout=8):
    """HTTP 状态码；显式禁用代理，避免 HTTP_PROXY 把本地请求劫到外网"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}{path}"
    try:
        if method == "GET":
            with opener.open(url, timeout=timeout) as r:
                return r.status
        req = urllib.request.Request(url, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def doctor(os_name=None):
    os_name = os_name or current_os()
    log(f"平台：{os_name}（Python {sys.version.split()[0]}，解释器 {sys.executable}）")
    log(f"源码仓库：{REPO}")
    log(f"运行目录：{APP_DIR}")
    print(f"  {'OK ' if os.path.isdir(REPO) else 'MISS'} 源码仓库存在  -> {REPO}")
    print(f"  {'OK ' if os.path.isdir(APP_DIR) else 'NEW'} 运行目录      -> {APP_DIR}")

    svc = plan_service(os_name)
    print(f"  INFO 服务托管方案  -> {svc}（UL_SERVICE 可覆盖）")

    # 依赖：pymysql 必选（MySQL 后端）；pypdf 可选（账单识别）
    for pkg, required in (("pymysql", False), ("pypdf", False)):
        try:
            __import__(pkg)
            print(f"  OK   依赖 {pkg} 可用")
        except ImportError:
            mark = "MISS" if required else "OPT "
            print(f"  {mark} 依赖 {pkg} 未安装"
                  f"（{'MySQL 后端需要' if required else '账单 PDF 识别可选'}）")

    print(f"  {'OK ' if port_open(PORT) else 'DOWN'} auth 端口 :{PORT} "
          f"-> {'在监听' if port_open(PORT) else '未监听'}")
    print(f"  {'OK ' if port_open(NGINX_PORT) else 'DOWN'} nginx 端口 :{NGINX_PORT} "
          f"-> {'在监听' if port_open(NGINX_PORT) else '未监听（可选）'}")
    return os_name


# ---------------------------------------------------------------------------
# 依赖安装（跨平台：用当前解释器自带的 pip）
# ---------------------------------------------------------------------------

def ensure_deps():
    if os.environ.get("UL_SKIP_DEPS") == "1":
        warn("已按 UL_SKIP_DEPS=1 跳过依赖安装")
        return
    for pkg in ("pymysql", "pypdf"):
        try:
            __import__(pkg)
            continue
        except ImportError:
            pass
        log(f"安装依赖 {pkg}（用户级）...")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--user",
                            "--quiet", pkg])
        if r.returncode != 0:
            warn(f"{pkg} 安装失败（{pkg} 缺失时对应功能不可用）")


# ---------------------------------------------------------------------------
# 源码同步（不依赖 rsync）
# ---------------------------------------------------------------------------

def _skip(name, is_dir):
    if is_dir:
        return name in EXCLUDE_DIRS or name.startswith("temp")
    if name in EXCLUDE_FILES:
        return True
    return any(name.endswith(s) for s in EXCLUDE_SUFFIX)


def sync_source():
    os.makedirs(APP_DIR, exist_ok=True)
    copied = skipped = 0
    for root, dirs, files in os.walk(REPO):
        rel = os.path.relpath(root, REPO)
        dirs[:] = [d for d in dirs if not _skip(d, True)]
        dest_dir = APP_DIR if rel == "." else os.path.join(APP_DIR, rel)
        os.makedirs(dest_dir, exist_ok=True)
        for f in files:
            if _skip(f, False):
                skipped += 1
                continue
            src, dst = os.path.join(root, f), os.path.join(dest_dir, f)
            shutil.copy2(src, dst)
            copied += 1
    log(f"源码同步完成：复制 {copied} 个文件，跳过 {skipped} 个运行数据/凭据文件")
    link_images()


def link_images():
    """让 site/images 指向运行目录 images/（账单截图与上传附件经此访问）"""
    images = os.path.join(APP_DIR, "images")
    os.makedirs(images, exist_ok=True)
    link = os.path.join(APP_DIR, "site", "images")
    if os.path.islink(link) or os.path.isdir(link):
        return
    try:
        os.symlink(images, link, target_is_directory=True)
        log(f"已创建图片软链：{link} -> {images}")
    except (OSError, NotImplementedError):
        if current_os() == "windows":
            # Windows 无管理员权限时软链会失败，退回 junction（同样无需管理员）
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, images],
                               capture_output=True)
            if r.returncode == 0:
                log(f"已创建图片目录联接（junction）：{link} -> {images}")
            else:
                warn("无法创建软链/junction，账单附件可能无法从网页访问；"
                     "请以管理员运行或手动复制 images/ 到 site/images/")
        else:
            warn(f"软链创建失败：{link}（请检查文件系统权限）")


# ---------------------------------------------------------------------------
# 数据库（SQLite 自动建表；MySQL 需预先建库建用户，文档有脚本）
# ---------------------------------------------------------------------------

def init_db():
    sys.path.insert(0, os.path.join(APP_DIR, "scripts"))
    sys.path.insert(0, APP_DIR)
    os.environ.setdefault("UL_APP_DIR", APP_DIR)
    backend = os.environ.get("UL_BACKEND", "")
    try:
        import db_backend  # noqa: E402
        conn = db_backend.get_conn()
        conn.close()
        log(f"数据库连接正常（后端 {db_backend.get_backend()}，URL 之外的建表由服务自动完成）")
    except Exception as e:
        warn(f"数据库连接失败：{e}（SQLite 首次运行会自动建表；"
             f"MySQL 需先建库建用户，SQL 见 README「MySQL 后端」）")
        return
    if backend == "mysql":
        log("MySQL 后端：请确保已执行 README「MySQL 后端」的建库建用户语句")


# ---------------------------------------------------------------------------
# 服务托管
# ---------------------------------------------------------------------------

def _python_exe():
    return sys.executable or "python3"


def pid_file():
    return os.path.join(APP_DIR, f".auth_server.{PORT}.pid")


def start_process():
    """跨平台后台进程（无 launchd/systemd 时的通用兜底）"""
    log_path = os.path.join(APP_DIR, "auth_server.log")
    out = open(log_path, "ab")
    popen_kwargs = {"stdout": out, "stderr": subprocess.STDOUT, "cwd": APP_DIR,
                    "env": dict(os.environ, UL_APP_DIR=APP_DIR)}
    if current_os() == "windows":
        popen_kwargs["creationflags"] = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                         | getattr(subprocess, "DETACHED_PROCESS", 0))
    proc = subprocess.Popen([_python_exe(), os.path.join(APP_DIR, "auth_server.py")],
                            **popen_kwargs)
    with open(pid_file(), "w") as f:
        f.write(str(proc.pid))
    log(f"已后台启动 auth_server（pid={proc.pid}，日志 {log_path}）")


def write_launchd_plist():
    label = f"com.{os.environ.get('USER') or os.environ.get('LOGNAME') or 'user'}.utility-auth"
    if PORT != 8099:
        label += f"-{PORT}"
    path = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                        label + ".plist")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{_python_exe()}</string>
         <string>{os.path.join(APP_DIR, 'auth_server.py')}</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>UL_APP_DIR</key><string>{APP_DIR}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>{os.path.join(APP_DIR, 'auth_server.log')}</string>
  <key>StandardErrorPath</key><string>{os.path.join(APP_DIR, 'auth_server.log')}</string>
</dict></plist>
"""
    with open(path, "w") as f:
        f.write(plist)
    return label, path


def write_systemd_unit():
    unit_dir = os.path.join(os.path.expanduser("~"), ".config", "systemd", "user")
    os.makedirs(unit_dir, exist_ok=True)
    path = os.path.join(unit_dir, "utility-auth.service")
    unit = f"""[Unit]
Description=UtilityLog auth gateway
After=network.target

[Service]
Type=simple
Environment=UL_APP_DIR={APP_DIR}
WorkingDirectory={APP_DIR}
ExecStart={_python_exe()} {os.path.join(APP_DIR, 'auth_server.py')}
Restart=always

[Install]
WantedBy=default.target
"""
    with open(path, "w") as f:
        f.write(unit)
    return "utility-auth", path


def start_service(mode=None):
    os_name = current_os()
    mode = mode or plan_service(os_name)
    if mode == "none":
        log(f"UL_SERVICE=none：请手动运行 {_python_exe()} "
            f"{os.path.join(APP_DIR, 'auth_server.py')}")
        return
    if mode == "launchd":
        label, path = write_launchd_plist()
        uid = subprocess.run(["id", "-u"], capture_output=True, text=True)
        domain = f"gui/{uid.stdout.strip()}" if uid.returncode == 0 else "gui/501"
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                       capture_output=True)
        r = subprocess.run(["launchctl", "bootstrap", domain, path],
                           capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"],
                           capture_output=True)
            log(f"launchd 服务已就绪：{label}")
            return
        warn(f"launchd 注册失败（{r.stderr.strip()[:120]}），回退后台进程")
        return start_process()
    if mode == "systemd":
        unit, path = write_systemd_unit()
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        r = subprocess.run(["systemctl", "--user", "enable", "--now", unit],
                           capture_output=True, text=True)
        if r.returncode == 0:
            log(f"systemd 用户服务已启用：{unit}（{path}）")
            return
        warn(f"systemd 启用失败（{r.stderr.strip()[:120]}），回退后台进程")
        return start_process()
    start_process()


def stop_service():
    stopped = False
    pf = pid_file()
    if os.path.exists(pf):
        try:
            pid = int(open(pf).read().strip())
            os.kill(pid, 15)
            log(f"已停止后台进程 pid={pid}")
            stopped = True
        except Exception as e:
            warn(f"停止进程失败：{e}")
        os.remove(pf)
    if current_os() == "macos" and shutil.which("launchctl"):
        label = f"com.{os.environ.get('USER') or 'user'}.utility-auth"
        if PORT != 8099:
            label += f"-{PORT}"
        uid = subprocess.run(["id", "-u"], capture_output=True, text=True)
        domain = f"gui/{uid.stdout.strip()}" if uid.returncode == 0 else "gui/501"
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"],
                       capture_output=True)
        stopped = True
    if current_os() == "linux" and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "stop", "utility-auth"],
                       capture_output=True)
        stopped = True
    if not stopped:
        warn("没有找到可停止的服务（可能未运行）")


# ---------------------------------------------------------------------------
# 验证
# ---------------------------------------------------------------------------

def verify():
    log("验证服务...")
    checks = [
        (PORT, "/login.html", "GET", 200),
        (PORT, "/data.js", "GET", 401),
        (PORT, "/api/me", "GET", 401),
        (PORT, "/mcp", "POST", 401),
    ]
    ok = True
    for port, path, method, expect in checks:
        code = http_code(port, path, method)
        good = code == expect
        ok = ok and good
        print(f"  auth_server :{port} {path:14s}({method:4s}) -> {code}"
              f"（期望 {expect}）{' ✅' if good else ' ❌'}")
    if port_open(NGINX_PORT):
        code = http_code(NGINX_PORT, "/login.html")
        mcp_code = http_code(NGINX_PORT, "/mcp", "POST")
        print(f"  nginx 反代 :{NGINX_PORT} /login.html -> {code}（期望 200）")
        print(f"  nginx 反代 :{NGINX_PORT} /mcp(未鉴权 POST) -> {mcp_code}（期望 401）")
        # 大 body 探测：账单上传 PDF 可到 20MB，nginx client_max_body_size
        # 默认 1MB 会在应用层之前返回 413（未鉴权大 body 正常应先拿到 401）
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            tf.write(b"x" * (2 << 20))
            big = tf.name
        try:
            with open(big, "rb") as f:
                big_body = f.read()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(
                f"http://127.0.0.1:{NGINX_PORT}/mcp", data=big_body, method="POST",
                headers={"Content-Type": "application/json"})
            try:
                with opener.open(req, timeout=10) as r:
                    big_code = r.status
            except urllib.error.HTTPError as e:
                big_code = e.code
        finally:
            os.remove(big)
        print(f"  nginx 反代 :{NGINX_PORT} /mcp(2MB 大body) -> {big_code}"
              f"（期望 401；413 = client_max_body_size 太小，账单上传会被挡）")
        if code != 200 or mcp_code != 401:
            ok = False
        if big_code == 413:
            warn("nginx client_max_body_size 过小：账单上传（≤20MB）会被 413 拦截，"
                 "请在反代配置中加 client_max_body_size 25m")
            ok = False
    else:
        warn(f"nginx :{NGINX_PORT} 未监听（未装 nginx 也可直接用 :{PORT} 访问）")
    if ok:
        log("验证通过 ✅")
    else:
        die("验证未通过，请查看运行目录 auth_server.log")
    return ok


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------

def do_install(args, mode):
    if not os.path.isfile(os.path.join(REPO, "auth_server.py")):
        die(f"{REPO} 不是 UtilityLog 源码仓库根（缺少 auth_server.py）")
    ensure_deps()
    sync_source()
    os.environ.setdefault("UL_APP_DIR", APP_DIR)
    init_db()
    start_service(mode)
    time.sleep(1.5)
    verify()
    log(f"安装完成。运行目录：{APP_DIR}")


def do_upgrade(args, mode):
    if not os.path.isfile(os.path.join(REPO, "auth_server.py")):
        die(f"{REPO} 不是 UtilityLog 源码仓库根（缺少 auth_server.py）")
    ensure_deps()
    sync_source()          # 只换程序：运行数据与凭据不在同步列表内
    os.environ.setdefault("UL_APP_DIR", APP_DIR)
    init_db()
    start_service(mode)    # 重启生效
    time.sleep(1.5)
    verify()
    log("升级完成（数据与凭据保留）")


def main():
    global APP_DIR, PORT, NGINX_PORT, SERVICE_MODE
    p = argparse.ArgumentParser(description="UtilityLog 跨平台部署工具")
    p.add_argument("command", choices=["doctor", "install", "upgrade", "start",
                                       "stop", "status", "verify"])
    p.add_argument("--app-dir", default=APP_DIR)
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--nginx-port", type=int, default=NGINX_PORT)
    p.add_argument("--service", default=SERVICE_MODE,
                   choices=["auto", "launchd", "systemd", "process", "none"])
    p.add_argument("--sim", choices=["macos", "linux", "windows"],
                   help="模拟其它平台（自测用，不改变实际行为）")
    args = p.parse_args()

    APP_DIR = os.path.abspath(os.path.expanduser(args.app_dir))
    PORT = args.port
    NGINX_PORT = args.nginx_port
    SERVICE_MODE = args.service
    os.environ["UL_APP_DIR"] = APP_DIR
    os.environ["UL_AUTH_PORT"] = str(PORT)

    os_name = current_os(args.sim)
    mode = plan_service(os_name)

    if args.command == "doctor":
        doctor(os_name)
        log("提示：--sim windows|linux 可预览其它平台的部署行为")
    elif args.command == "install":
        do_install(args, mode)
    elif args.command == "upgrade":
        do_upgrade(args, mode)
    elif args.command == "start":
        start_service(mode)
    elif args.command == "stop":
        stop_service()
    elif args.command == "status":
        print(json.dumps({
            "os": os_name, "service": mode, "app_dir": APP_DIR,
            "auth_port": PORT, "auth_listening": port_open(PORT),
            "nginx_listening": port_open(NGINX_PORT),
        }, ensure_ascii=False, indent=2))
    elif args.command == "verify":
        verify()


if __name__ == "__main__":
    main()

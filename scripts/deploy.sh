#!/usr/bin/env bash
# ============================================================
# UtilityLog 一键部署 / 升级脚本（0.3.1）
#
# 两种模式：
#   install  首次部署：解析 MySQL 连接 → 建库建表 → 同步源码到运行目录
#            → 生成 db_config.json → 配置并加载 launchd → 启动并验证
#   upgrade  升级：git pull 拉最新源码 → 同步源码到运行目录（排除运行数据与凭据）
#            → 幂等 schema 变更 → 重启 launchd → 验证
#
# 设计要点：
#   - 数据与程序分离：程序（源码）与运行数据（data/ images/ 凭据/日志）分目录，
#     升级只替换程序，不触碰运行数据与凭据。
#   - 变量尽量用 $HOME 与环境变量，不硬编码用户路径。
#   - 幂等：重复执行 install / upgrade 均安全。
#
# 用法：
#   ./deploy.sh install          # 首次部署（需 root 密码建库建用户）
#   ./deploy.sh upgrade          # 升级（git pull + 同步 + 重启）
# 环境变量（均可覆盖默认值）：
#   UL_REPO_DIR  UL_APP_DIR  UL_DB_NAME  UL_DB_USER  UL_DB_PASS
#   UL_MYSQL_HOST  UL_MYSQL_PORT  UL_MYSQL_ROOT_USER  UL_MYSQL_ROOT_PASS
#   UL_AUTH_PORT  UL_NGINX_PORT
# ============================================================
set -euo pipefail

# ---------- 路径与环境（$HOME 推导，不硬编码用户名） ----------
REPO_DIR="${UL_REPO_DIR:-$HOME/project/UtilityLog}"
APP_DIR="${UL_APP_DIR:-$HOME/myapp/utilitylog}"
# launchd 标签由当前用户名派生（可用 UL_LAUNCHD_LABEL 覆盖），不硬编码具体用户名
LAUNCHD_LABEL="${UL_LAUNCHD_LABEL:-com.$(id -un).utility-auth}"
PLIST="$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist"

DB_NAME="${UL_DB_NAME:-utilitylog}"
DB_USER="${UL_DB_USER:-ul_app}"
DB_PASS="${UL_DB_PASS:-}"
MYSQL_HOST="${UL_MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${UL_MYSQL_PORT:-9306}"
MYSQL_ROOT_USER="${UL_MYSQL_ROOT_USER:-root}"
MYSQL_ROOT_PASS="${UL_MYSQL_ROOT_PASS:-}"
AUTH_PORT="${UL_AUTH_PORT:-8099}"
NGINX_PORT="${UL_NGINX_PORT:-8089}"

# 同步源码时排除的运行时产物 / 凭据 / 日志（升级必须保留）
# 原则：运行目录只放「程序副本 + 运行数据 + 凭据」，
#       不放本机协作文件（AGENTS.md / .agent-sync/ / .workbuddy/）。
RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='data/'
  --exclude='images/'
  --exclude='entries/'
  --exclude='temp*'
  --exclude='site/data.js'
  --exclude='db_config.json'
  --exclude='auth_config.json'
  --exclude='.auth_tokens.json'
  --exclude='.htpasswd'
  --exclude='*.log'
  --exclude='*.bak'
  --exclude='__pycache__/'
  --exclude='.DS_Store'
  --exclude='skill/'
  --exclude='.workbuddy/'
  --exclude='.agent-sync/'
  --exclude='AGENTS.md'
)

log()  { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[deploy-warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[deploy-error]\033[0m %s\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1（请先安装）"; }

# 探测 mysql 客户端（PATH 可能不含 /opt/homebrew/bin）
detect_mysql() {
  local c
  for c in "$(command -v mysql 2>/dev/null)" /opt/homebrew/bin/mysql /usr/local/bin/mysql /usr/bin/mysql; do
    [ -x "$c" ] && { MYSQL_CLI="$c"; return 0; }
  done
  die "未找到 mysql 客户端，请安装（brew install mysql）"
}
MYSQL_CLI=""

# 确保系统 python3 具备运行依赖（launchd 使用 /usr/bin/python3）
ensure_python_deps() {
  if ! /usr/bin/python3 -c "import pymysql" >/dev/null 2>&1; then
    log "安装 python 依赖 pymysql（用户级）..."
    /usr/bin/python3 -m pip install --user --quiet pymysql || die "pymysql 安装失败"
  fi
  /usr/bin/python3 -c "import pymysql" >/dev/null 2>&1 || die "pymysql 仍不可用，请手动安装"
}

usage() {
  cat <<'EOF'
UtilityLog deploy.sh 0.3.1

用法:
  ./deploy.sh install    首次部署（建库建表 + 安装程序 + 配置 launchd + 验证）
  ./deploy.sh upgrade    升级（git pull + 同步程序 + schema 变更 + 重启 + 验证）

环境变量:
  UL_REPO_DIR           源码仓库路径（默认 $HOME/project/UtilityLog）
  UL_APP_DIR            运行目录（默认 $HOME/myapp/utilitylog）
  UL_DB_NAME            数据库名（默认 utilitylog）
  UL_DB_USER            低权限应用账号（默认 ul_app）
  UL_DB_PASS            应用账号密码（install 未指定则自动生成）
  UL_MYSQL_HOST          MySQL 主机（默认 127.0.0.1）
  UL_MYSQL_PORT          MySQL 端口（默认 9306）
  UL_MYSQL_ROOT_USER    MySQL 管理账号（默认 root）
  UL_MYSQL_ROOT_PASS    MySQL 管理密码（install 必填，交互输入或环境变量）
  UL_AUTH_PORT          auth_server 监听端口（默认 8099）
  UL_NGINX_PORT         nginx 反代端口（默认 8089，仅用于验证）
EOF
}

# ---------- 工具函数 ----------

mysql_root() {
  # 用管理账号执行 SQL（密码从环境变量或交互输入）
  if [ -z "$MYSQL_ROOT_PASS" ]; then
    read -rsp "请输入 MySQL $MYSQL_ROOT_USER 密码: " MYSQL_ROOT_PASS
    echo
  fi
  MYSQL_PWD="$MYSQL_ROOT_PASS" "$MYSQL_CLI" -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$MYSQL_ROOT_USER" "$@"
}

mysql_app() {
  MYSQL_PWD="$DB_PASS" "$MYSQL_CLI" -h"$MYSQL_HOST" -P"$MYSQL_PORT" -u"$DB_USER" "$@"
}

sync_source() {
  # 源码 → 运行目录；排除运行数据 / 凭据 / 日志
  mkdir -p "$APP_DIR"
  log "同步源码到运行目录: $APP_DIR"
  rsync -a --delete "${RSYNC_EXCLUDES[@]}" "$REPO_DIR/" "$APP_DIR/"
}

link_images() {
  # 站点静态模板在运行目录的 site/ 下，账单截图在运行目录的 images/ 下。
  # 用软链把 site/images 指向 images/，使网页里的 images/<YYYY-MM>/xxx.jpg 可访问。
  # 软链是运行期产物，不随源码入库（.gitignore 已排除 site/images）。
  local site_dir="$APP_DIR/site" img_dir="$APP_DIR/images"
  mkdir -p "$site_dir" "$img_dir"
  if [ -L "$site_dir/images" ]; then
    local cur
    cur=$(readlink "$site_dir/images")
    if [ "$cur" = "$img_dir" ]; then
      log "site/images 软链已就绪"
      return 0
    fi
    rm -f "$site_dir/images"
  elif [ -e "$site_dir/images" ]; then
    # 是真实目录而非软链：备份后重建，避免覆盖用户已有数据
    warn "site/images 是真实目录（非软链），已备份为 site/images.bak-*"
    mv "$site_dir/images" "$site_dir/images.bak-$(date '+%Y%m%d%H%M%S')"
  fi
  ln -s "$img_dir" "$site_dir/images"
  log "已创建软链: site/images -> $img_dir"
}

write_db_config() {
  cat > "$APP_DIR/db_config.json" <<EOF
{
  "backend": "mysql",
  "mysql": {
    "host": "$MYSQL_HOST",
    "port": $MYSQL_PORT,
    "user": "$DB_USER",
    "password": "$DB_PASS",
    "database": "$DB_NAME",
    "charset": "utf8mb4"
  }
}
EOF
  chmod 600 "$APP_DIR/db_config.json"
  log "已生成运行目录 db_config.json（权限 600）"
}

write_plist() {
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LAUNCHD_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>$APP_DIR/auth_server.py</string>
    </array>
    <key>WorkingDirectory</key><string>$APP_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>UL_APP_DIR</key><string>$APP_DIR</string>
        <key>UL_BACKEND</key><string>mysql</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$APP_DIR/auth_server.log</string>
    <key>StandardErrorPath</key><string>$APP_DIR/auth_server.log</string>
</dict>
</plist>
EOF
  chmod 644 "$PLIST"
  log "已生成 launchd plist: ${PLIST}（程序指向运行目录，实现程序/数据分离）"
}

restart_service() {
  launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null \
    || launchctl unload "$PLIST" 2>/dev/null || true
  if ! launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null; then
    launchctl load "$PLIST"
  fi
  log "launchd 服务已重新加载: ${LAUNCHD_LABEL}"
  # 等待服务端口就绪（launchd 拉起 + python 启动需要时间）
  local i code
  i=0
  while [ "$i" -lt 40 ]; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${AUTH_PORT}/login.html" 2>/dev/null || true)
    [ "$code" = "200" ] && return 0
    sleep 0.5
    i=$((i + 1))
  done
  return 1
}

apply_schema() {
  # 幂等建表（schema 均为 CREATE TABLE IF NOT EXISTS）
  log "执行幂等 schema（$APP_DIR/db/schema.mysql.sql）"
  mysql_app "$DB_NAME" < "$APP_DIR/db/schema.mysql.sql"
}

verify() {
  log "验证服务..."
  local login_code data_code
  login_code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${AUTH_PORT}/login.html" || true)
  data_code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${AUTH_PORT}/data.js" || true)
  echo "  auth_server 直连 :${AUTH_PORT} /login.html -> ${login_code}（期望 200）"
  echo "  auth_server 直连 :${AUTH_PORT} /data.js    -> ${data_code}（期望 401）"

  if command -v curl >/dev/null && [ "${NGINX_PORT}" != "${AUTH_PORT}" ]; then
    local ngx_code
    ngx_code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${NGINX_PORT}/login.html" || true)
    echo "  nginx 反代 :${NGINX_PORT} /login.html -> ${ngx_code}（期望 200）"
  fi

  local tables
  tables=$(mysql_app -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='${DB_NAME}'" 2>/dev/null || echo "N/A")
  echo "  MySQL ${DB_NAME} 表数量 -> ${tables}（期望 7）"

  if [ "${login_code}" != "200" ] || [ "${data_code}" != "401" ]; then
    die "服务验证未通过，请检查 auth_server.log：${APP_DIR}/auth_server.log"
  fi
  log "验证通过 ✅"
}

# ---------- 首次部署 ----------
do_install() {
  need_cmd rsync
  need_cmd curl
  detect_mysql
  ensure_python_deps
  [ -d "$REPO_DIR" ] || die "源码仓库不存在: $REPO_DIR"
  [ -f "$REPO_DIR/auth_server.py" ] || die "$REPO_DIR 不是 UtilityLog 源码仓库根（缺少 auth_server.py）"

  # 1) 解析 MySQL 连接信息（root 建库建用户）
  log "检查 MySQL $MYSQL_HOST:$MYSQL_PORT 可达性"
  if [ -z "$DB_PASS" ]; then
    DB_PASS=$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)
    log "已为 $DB_USER 生成随机密码（保存在运行目录 db_config.json）"
  fi

  # 2) 建库建表（幂等）
  mysql_root <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` DEFAULT CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
CREATE USER IF NOT EXISTS '$DB_USER'@'%' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'%';
FLUSH PRIVILEGES;
SQL
  log "数据库 $DB_NAME 与账号 $DB_USER 就绪"

  # 3) 同步源码到运行目录（程序分离）
  sync_source

  # 3.1) 站点软链：site/images → 运行目录 images/（账单截图访问）
  link_images

  # 4) 生成 db_config.json
  write_db_config

  # 5) 幂等建表
  apply_schema

  # 6) 配置并加载 launchd
  write_plist
  restart_service

  # 7) 验证
  verify
  log "首次部署完成。访问: http://127.0.0.1:$NGINX_PORT"
}

# ---------- 升级模式 ----------
do_upgrade() {
  need_cmd rsync
  need_cmd curl
  detect_mysql
  ensure_python_deps
  [ -d "$REPO_DIR" ] || die "源码仓库不存在: $REPO_DIR"
  [ -f "$APP_DIR/db_config.json" ] || die "运行目录缺少 db_config.json，请先执行 install"

  # 从现有 db_config.json 读取连接信息（升级不需要 root 密码，保留原凭据）
  if [ -z "$DB_PASS" ]; then
    read_cfg() {
      python3 -c "import json,sys;print(json.load(open('$APP_DIR/db_config.json')).get('mysql',{}).get(sys.argv[1],''))" "$1"
    }
    DB_USER=$(read_cfg user)
    DB_PASS=$(read_cfg password)
    MYSQL_HOST=$(read_cfg host)
    MYSQL_PORT=$(read_cfg port)
    DB_NAME=$(read_cfg database)
    log "已从运行目录 db_config.json 读取 MySQL 连接信息（${DB_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${DB_NAME}）"
  fi

  # 1) git pull 拉取最新源码（失败不阻塞，继续用本地源码）
  if [ -d "$REPO_DIR/.git" ]; then
    log "git pull 拉取最新源码..."
    ( cd "$REPO_DIR" && git pull --ff-only ) || warn "git pull 失败，继续使用本地源码"
  fi

  # 2) 同步源码到运行目录（排除运行数据与凭据 → 保留 myapp 运行数据）
  sync_source

  # 2.1) 站点软链：site/images → 运行目录 images/（账单截图访问）
  link_images

  # 3) 必要 schema 变更（幂等，不触碰数据）
  apply_schema

  # 4) 刷新 launchd plist（确保程序指向运行目录，实现程序/数据分离）
  write_plist

  # 5) 重启 launchd 服务
  restart_service

  # 6) 验证
  verify
  log "升级完成。myapp 运行数据与凭据已保留（data/ db_config.json .auth_tokens.json 等未覆盖）"
}

# ---------- 入口 ----------
case "${1:-}" in
  install) do_install ;;
  upgrade) do_upgrade ;;
  *) usage; exit 1 ;;
esac

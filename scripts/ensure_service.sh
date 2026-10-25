#!/usr/bin/env bash
# ============================================================
# UtilityLog 服务守护（0.5.2）
#
# 用途：launchd 注册不了的环境（SSH / CI / agent 会话没有 GUI 上下文），
#       由 cron 每 2 分钟调用一次，发现服务没在听就拉起来。
#       服务正常时本脚本立即退出，不做任何操作。
#
# 与 deploy.sh 的关系：deploy.sh 负责「升级时重启」，本脚本负责「挂了自愈」。
# 两者都遵守同一约定 —— 服务必须真的可用，而不是假装可用。
#
# 安装（本机终端执行一次）：
#   (crontab -l 2>/dev/null; echo '*/2 * * * * $HOME/myapp/utilitylog/scripts/ensure_service.sh >> /tmp/ul_watchdog.log 2>&1') | crontab -
# 查看：crontab -l | grep ensure_service
# ============================================================
set -u

APP_DIR="${UL_APP_DIR:-$HOME/myapp/utilitylog}"
PORT="${UL_AUTH_PORT:-8099}"
LOG="$APP_DIR/auth_server.log"
PIDFILE="$APP_DIR/.auth_server.pid"

stamp() { date '+%Y-%m-%d %H:%M:%S'; }

# 用 bash 内置的 /dev/tcp 探测，避免内嵌 python 的引号地狱（也少一次进程启动）
port_up() {
  (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null
}

# 已在跑 → 什么都不做（守护脚本必须足够安静，否则日志会被刷爆）
if port_up; then
  exit 0
fi

echo "[watchdog $(stamp)] 服务未在 127.0.0.1:${PORT} 监听，尝试启动" >> "$LOG"

# 启动前清理可能残留的 pid 记录，避免误判
rm -f "$PIDFILE"
cd "$APP_DIR" || { echo "[watchdog $(stamp)] 运行目录不存在: $APP_DIR" >> "$LOG"; exit 1; }

UL_APP_DIR="$APP_DIR" UL_BACKEND="${UL_BACKEND:-mysql}" \
  nohup /usr/bin/python3 auth_server.py >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"

# 给进程一点时间绑定端口，再确认一次
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if port_up; then
    # 先把 PID 取出来再拼字符串：bash 3.2 对「双引号里嵌带引号的命令替换」解析不稳定
    pid=$(cat "$PIDFILE" 2>/dev/null || echo "?")
    echo "[watchdog $(stamp)] 服务已恢复（PID ${pid}，端口 ${PORT}）" >> "$LOG"
    exit 0
  fi
  sleep 1
done

echo "[watchdog $(stamp)] 启动失败，请检查 $LOG" >> "$LOG"
exit 1

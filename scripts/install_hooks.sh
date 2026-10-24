#!/usr/bin/env bash
# ============================================================
# UtilityLog · 安装 git hooks
#
# 把 pre-commit 敏感信息扫描装到 .git/hooks/ 下。
# 源码仓库（.git 在仓库根）与运行目录副本都可能需要，按实际存在情况安装。
#
# 用法：bash scripts/install_hooks.sh
# ============================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK_SRC="$SCRIPT_DIR/pre-commit.py"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$HOOK_SRC" ]; then
    echo "错误：找不到 $HOOK_SRC" >&2
    exit 1
fi

# hook 文件必须是可执行的 Python 脚本（用 python3 shebang）
install_hook() {
    local git_dir="$1"
    cp "$HOOK_SRC" "$git_dir/hooks/pre-commit"
    chmod +x "$git_dir/hooks/pre-commit"
    echo "✅ 已安装: $git_dir/hooks/pre-commit"
}

installed=0

# 安装到仓库自身的 .git/hooks（源码仓库）
if [ -d "$REPO_ROOT/.git" ]; then
    install_hook "$REPO_ROOT/.git"
    installed=1
fi

# 安装到运行目录的 .git/hooks（若运行目录也是 git 仓库）
APP_DIR="${UL_APP_DIR:-$HOME/myapp/utilitylog}"
if [ -d "$APP_DIR/.git" ] && [ "$APP_DIR/.git" != "$REPO_ROOT/.git" ]; then
    install_hook "$APP_DIR/.git"
    installed=1
fi

if [ "$installed" -eq 0 ]; then
    echo "ℹ️  未找到 .git 目录，跳过安装。"
    echo "   若之后在此目录初始化 git，可重新运行本脚本。"
fi

echo ""
echo "提示：pre-commit hook 会在每次提交前扫描暂存区，"
echo "      命中本机绝对路径 / 私域域名 / 令牌 / 明文密码时阻止提交。"
echo "      紧急情况可用 git commit --no-verify 跳过（请自行确认安全）。"

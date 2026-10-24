#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog · 提交前敏感信息扫描（git pre-commit hook）

作用：在 commit 之前扫描暂存区内容，命中敏感模式则阻止提交。
安装：bash scripts/install_hooks.sh

设计原则：
  - 只拦「明确的私密信息」（真实路径、私域域名、凭据、密钥、明文密码）
  - 文档中的示例占位符（<token>、$HOME、我的家、测试账号）不误伤
  - 命中时列出具体文件与行，便于定位

实现说明：用 Python 而非 bash —— bash 数组 + 正则的引号处理极易出错。
"""
import re
import subprocess
import sys

# (正则, 说明) —— 每一项对应一类明确的私密信息
PATTERNS = [
    # 本机绝对路径（应改用 $HOME）
    (r"/Users/[a-zA-Z0-9._-]+/(project|myapp|Desktop|Documents|Downloads|Library)/",
     "本机绝对路径"),
    # 私有仓库 / 内网域名
    (r"[a-zA-Z0-9-]+\.(hyper\.online|mygt\.[a-z]+)\b",
     "内网 / 私有仓库域名"),
    # GitHub / GitLab PAT
    (r"\b(gh[pousr]_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,})\b",
     "GitHub 访问令牌"),
    # 通用 API 密钥
    (r"\bsk-[A-Za-z0-9]{20,}\b",
     "API 密钥"),
    # 云文档 file_id
    (r"\b(docwx|fileid)[0-9A-Za-z_-]{20,}\b",
     "云文档 file_id"),
    # 私钥块
    (r"BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY",
     "私钥文件"),
    # 配置中的明文密码（排除占位符 CHANGE_ME / xxx）
    (r'"password"\s*:\s*"(?!(CHANGE_ME|<|\$|xxx|your)[^"]{0,20})[^"]{6,}"',
     "配置文件中的明文密码"),
    # 疑似手机号
    (r"\b1[3-9]\d{9}\b",
     "疑似手机号"),
]

RED = "\033[1;31m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


def staged_files():
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [f for f in out.splitlines() if f.strip()]


def scan(files):
    """扫描暂存文件的新增内容，返回 [(说明, 文件名, 行号, 内容)]"""
    hits = []
    for path in files:
        try:
            blob = subprocess.run(
                ["git", "show", f":{path}"],
                capture_output=True, check=True).stdout
        except subprocess.CalledProcessError:
            continue
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            continue  # 二进制文件跳过
        for i, line in enumerate(text.splitlines(), 1):
            for pat, desc in PATTERNS:
                if re.search(pat, line):
                    hits.append((desc, path, i, line.strip()[:100]))
    return hits


def main():
    files = staged_files()
    if not files:
        return 0

    hits = scan(files)
    if not hits:
        return 0

    print(f"{RED}")
    print("=" * 60)
    print(" 提交被阻止：检测到可能的敏感信息")
    print("=" * 60)
    print(f"{NC}")
    for desc, path, lineno, content in hits[:20]:
        print(f"{RED}✖ {desc}{NC}")
        print(f"    {path}:{lineno}")
        print(f"    {content}")
    if len(hits) > 20:
        print(f"    …另有 {len(hits) - 20} 处")
    print(f"{YELLOW}")
    print(" 请处理后再提交。若确属误报（如确为示例值），可：")
    print("   git commit --no-verify")
    print(" 但请先确认该内容确实不含真实凭据。")
    print(f"{NC}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

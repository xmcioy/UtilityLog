#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 站点数据同步脚本
- 从 utility.db 导出完整数据 -> site/data.js
- 自动为 site/index.html 中 data.js 引用打版本号（规避 Cloudflare 缓存）
用法: python3 sync_site.py
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = os.environ.get("UL_ROOT", str(Path(__file__).resolve().parent.parent))
DB = os.environ.get("UL_DB", os.path.join(ROOT, "data", "utility.db"))
SITE = os.path.join(ROOT, "site")
DATA_JS = os.path.join(SITE, "data.js")
INDEX_HTML = os.path.join(SITE, "index.html")

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from utility import dump_json  # noqa: E402


def main():
    data = dump_json()
    js = "window.UTILITY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(js)

    # 版本号：时间戳 + 数据条数
    version = f"v{data['bills'].__len__()}-{int(__import__('time').time() * 1000)}"

    if os.path.exists(INDEX_HTML):
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()
        html = re.sub(r"data\.js\?v=[0-9a-zA-Z\-_]+", f"data.js?v={version}", html)
        with open(INDEX_HTML, "w", encoding="utf-8") as f:
            f.write(html)

    print(f"site synced: {DATA_JS} ({len(data['bills'])} bills, {len(data['families'])} families, {version})")


if __name__ == "__main__":
    main()

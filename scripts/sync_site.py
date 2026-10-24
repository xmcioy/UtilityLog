#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 站点数据同步脚本（0.3 双后端版）
- 从后端（SQLite / MySQL）导出配置凭据用户数据 -> <APP_DIR>/site/data.js（运行目录）
- 自动为源码 site/index.html 中 data.js 引用打版本号（规避 Cloudflare 缓存）
用法: python3 sync_site.py
"""
import json
import os
import re
import sys
from pathlib import Path

import db_backend

APP_DIR = db_backend.resolve_app_dir()
SITE = APP_DIR / "site"                     # 运行目录下站点数据（data.js 等运行时产物）
DATA_JS = SITE / "data.js"
INDEX_HTML = Path(__file__).resolve().parent.parent / "site" / "index.html"  # 源码模板

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from utility import dump_json, DEFAULT_USER  # noqa: E402


def main():
    # 0.2/0.3 多用户：导出配置凭据用户（auth_config.json / UL_USER）的数据
    user = os.environ.get("UL_SYNC_USER", DEFAULT_USER)
    if not user:
        raise SystemExit("ERROR: no sync user configured (set UL_USER or auth_config.json or UL_SYNC_USER)")
    data = dump_json(user)
    SITE.mkdir(parents=True, exist_ok=True)
    js = "window.UTILITY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(js)

    # 版本号：时间戳 + 数据条数
    version = f"v{data['bills'].__len__()}-{int(__import__('time').time() * 1000)}"

    if INDEX_HTML.exists():
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            html = f.read()
        html = re.sub(r"data\.js\?v=[0-9a-zA-Z\-_]+", f"data.js?v={version}", html)
        with open(INDEX_HTML, "w", encoding="utf-8") as f:
            f.write(html)

    print(f"site synced: {DATA_JS} (user={user}, {len(data['bills'])} bills, "
          f"{len(data['families'])} families, {version}, backend={db_backend.get_backend()})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 数据库后端层单元测试（0.5.2）

覆盖 db_backend 的两类纯函数（不需要真连数据库）：
  - `_mysql_sql` 方言翻译：占位符、保留字、datetime、**字符串字面量保护**
  - `upsert_sql`：SQLite / MySQL 两种 upsert 语法
  - `get_backend` 优先级：UL_BACKEND > db_config.json.backend > sqlite

这些是 0.5.2 修掉的「静默错误」类缺陷的回归防线：
  修之前 `?`→`%s` 与 usage 反引号都是全局替换，会污染字符串字面量
  （`LIKE '%?%'` 会变成 `'%%s%'`），而不报错、结果不对。

用法：
  python3 scripts/test_db_backend.py
退出码：全部通过 0，任一失败 1。
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db_backend  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print("  [%s] %s%s" % ("PASS" if ok else "FAIL", name,
                           ("  -> " + detail) if detail else ""))
    return ok


def t_dialect():
    print("1. _mysql_sql 方言翻译")
    # 基础替换
    s = db_backend._mysql_sql("SELECT id, usage FROM bills_water WHERE family_id=? AND bill_month=?")
    check("占位符 ? -> %s", "%s" in s and "?" not in s, s)
    check("usage 加反引号", "`usage`" in s)
    check("AUTOINCREMENT -> AUTO_INCREMENT",
          "AUTO_INCREMENT" in db_backend._mysql_sql("CREATE TABLE t(id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    check("datetime('now','localtime') -> NOW()",
          "NOW()" in db_backend._mysql_sql(
              "SELECT * FROM t WHERE created_at > datetime('now','localtime')"))
    check("last_insert_rowid() -> LAST_INSERT_ID()",
          "LAST_INSERT_ID()" in db_backend._mysql_sql("SELECT last_insert_rowid()"))

    # 字面量保护（0.5.2 新增，防静默错误）
    s = db_backend._mysql_sql("SELECT * FROM t WHERE note LIKE '%?%'")
    check("字面量里的 ? 不被替换", "'%?%'" in s and "%s" not in s, s)
    s = db_backend._mysql_sql("SELECT * FROM t WHERE name = 'usage_report'")
    check("字面量里的 usage 不加反引号", "'usage_report'" in s, s)
    s = db_backend._mysql_sql("INSERT INTO t(a, b) VALUES (?, 'x?y')")
    check("混合：占位符替换 + 字面量里的 ? 原样",
          s.count("%s") == 1 and "'x?y'" in s, s)
    s = db_backend._mysql_sql("SELECT * FROM t WHERE note = 'it''s ? here' AND id=?")
    check("SQL 转义单引号 '' 不破坏保护", "it''s ? here" in s, s)
    s = db_backend._mysql_sql("SELECT * FROM t WHERE a='1' AND usage=? AND b='2'")
    check("多个字面量与占位符混排", s.count("%s") == 1 and "`usage`" in s
          and "'1'" in s and "'2'" in s, s)


def t_upsert():
    print("2. upsert_sql 双方言")
    old = os.environ.get("UL_BACKEND")
    try:
        os.environ["UL_BACKEND"] = "sqlite"
        s = db_backend.upsert_sql("bills_water",
                                  ["family_id", "user_id", "bill_month", "usage"],
                                  4, ["family_id", "bill_month"], ["usage"])
        check("SQLite ON CONFLICT", "ON CONFLICT(family_id, bill_month) DO UPDATE SET usage=excluded.usage" in s, s)
        os.environ["UL_BACKEND"] = "mysql"
        s = db_backend.upsert_sql("bills_water",
                                  ["family_id", "user_id", "bill_month", "usage"],
                                  4, ["family_id", "bill_month"], ["usage"])
        check("MySQL ON DUPLICATE KEY", "ON DUPLICATE KEY UPDATE usage=VALUES(usage)" in s, s)
        check("MySQL 占位符为 %s", "%s" in s and "?" not in s, s)
    finally:
        if old is None:
            os.environ.pop("UL_BACKEND", None)
        else:
            os.environ["UL_BACKEND"] = old


def t_backend_priority():
    print("3. get_backend 优先级（0.5.2 起与文档一致）")
    old_env = os.environ.get("UL_BACKEND")
    old_cfg = os.environ.get("UL_DB_CONFIG")
    tmp = tempfile.mkdtemp(prefix="ul_test_backend_")
    cfg = Path(tmp) / "db_config.json"
    cfg.write_text(json.dumps({"backend": "mysql", "mysql": {"backend": "mysql"}}), encoding="utf-8")
    try:
        os.environ["UL_DB_CONFIG"] = str(cfg)
        os.environ.pop("UL_BACKEND", None)
        check("未设环境变量 -> 读 db_config.json.backend",
              db_backend.get_backend() == "mysql")
        os.environ["UL_BACKEND"] = "sqlite"
        check("环境变量优先于配置文件",
              db_backend.get_backend() == "sqlite")
        os.environ.pop("UL_BACKEND", None)
        cfg.write_text(json.dumps({"mysql": {"user": "u"}}), encoding="utf-8")
        check("配置文件无 backend 字段 -> 默认 sqlite",
              db_backend.get_backend() == "sqlite")
        os.environ["UL_DB_CONFIG"] = str(Path(tmp) / "missing.json")
        check("配置文件不存在 -> 默认 sqlite",
              db_backend.get_backend() == "sqlite")
    finally:
        os.environ.pop("UL_DB_CONFIG", None)
        if old_cfg is not None:
            os.environ["UL_DB_CONFIG"] = old_cfg
        os.environ.pop("UL_BACKEND", None)
        if old_env is not None:
            os.environ["UL_BACKEND"] = old_env
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print("[test_db_backend] backend=%s" % db_backend.get_backend())
    t_dialect()
    t_upsert()
    t_backend_priority()
    failed = [r for r in RESULTS if not r[1]]
    print("\n[test_db_backend] 通过 %d / %d" % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        for n, _, d in failed:
            print("  FAIL %s %s" % (n, d))
        sys.exit(1)
    print("[test_db_backend] 全部通过 ✅")
    sys.exit(0)

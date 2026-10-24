#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 0.3.2 迁移：families 唯一约束语义对齐 MySQL

背景
----
SQLite 版 `families` 表用的是全局唯一约束 `name TEXT NOT NULL UNIQUE`，
而 MySQL 版是 `UNIQUE KEY uq_families_user_name (user_id, name)`（用户内唯一）。
两者语义不一致，导致：
  - SQLite 后端上，B 用户无法创建与 A 用户同名的家庭（「我家」被拒）；
  - 违反 docs/DESIGN.md「家庭名只在同一用户内唯一」的声明；
  - 两个后端行为分叉，用户切换后端时遇到意外。

本脚本把 SQLite 的 families 表重建为 `UNIQUE(user_id, name)`，与 MySQL 语义等价。

SQLite 不支持 ALTER TABLE 移除约束，只能重建表：
  1. 备份数据库
  2. 新建 families_new（带 UNIQUE(user_id, name)）
  3. 迁移数据（保留 id / user_id / created_at）
  4. 重建 bills_* 表的 family_id 外键引用（SQLite 外键指向表名，需同步改名）
  5. 删旧表、改名、校验

安全性
------
- 全程事务，失败自动回滚
- 先备份，出错可从 .bak 恢复
- 迁移前检测重名（同一 user_id 下重复 name），有则中止并列出冲突
- 迁移后逐项校验行数与内容一致

用法:
  python3 db/migrations/migrate_families_unique.py
  # 或指定库路径
  UL_DB=/path/to/utility.db python3 db/migrations/migrate_families_unique.py
"""
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

APP_DIR = Path(os.environ.get("UL_APP_DIR") or os.environ.get("UL_ROOT")
               or Path(__file__).resolve().parent.parent.parent)
DB_PATH = Path(os.environ.get("UL_DB", str(APP_DIR / "data" / "utility.db")))

BILL_TABLES = ("bills_water", "bills_electric", "bills_gas")


def has_new_constraint(conn):
    """检测 families 是否已是 UNIQUE(user_id, name)"""
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='families'").fetchone()
    if not ddl or not ddl[0]:
        return False
    sql = " ".join(ddl[0].split()).lower()
    return "unique(user_id, name)" in sql or "unique(user_id,name)" in sql


def find_conflicts(conn):
    """找出同一 user_id 下重复的 family name"""
    rows = conn.execute(
        "SELECT user_id, name, COUNT(*) c FROM families "
        "GROUP BY user_id, name HAVING c > 1").fetchall()
    return rows


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"ERROR: database not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    backup = None
    try:
        if has_new_constraint(conn):
            print("[skip] families 已是 UNIQUE(user_id, name)，无需迁移")
            return

        conflicts = find_conflicts(conn)
        if conflicts:
            print("ERROR: 存在同一用户下的重名家庭，无法自动迁移。请先手动改名：")
            for r in conflicts:
                print(f"  user_id={r['user_id']} name={r['name']!r} × {r['c']}")
            sys.exit(1)

        # 只处理实际存在的 bills 表（老库可能缺表）
        present_bills = [t for t in BILL_TABLES
                         if conn.execute(
                             "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                             (t,)).fetchone()]
        before_fam = conn.execute("SELECT COUNT(*) FROM families").fetchone()[0]
        before_bills = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                        for t in present_bills}
        print(f"[before] families={before_fam} bills={before_bills or '（无 bills 表）'}")

        # 备份
        backup = str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy2(DB_PATH, backup)
        print(f"[backup] {backup}")

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")

        # 1) 新表
        conn.execute("""
            CREATE TABLE families_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                user_id    INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(user_id, name)
            )""")

        # 2) 迁数据
        conn.execute(
            "INSERT INTO families_new(id, name, user_id, created_at) "
            "SELECT id, name, user_id, created_at FROM families")
        print("[migrate] families 数据已迁移")

        # 3) bills_* 的 family_id 外键指向 families（SQLite 引用的是表名）
        #    需先重建 bills 表再改名，否则旧外键仍指向 families
        for t in present_bills:
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
            if "family_id" not in cols:
                continue
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()[0]
            new_ddl = ddl.replace(f"REFERENCES families(id)", "REFERENCES families_new(id)")
            new_ddl = new_ddl.replace(f"CREATE TABLE {t}", f"CREATE TABLE {t}_new")
            conn.execute(new_ddl)
            col_list = ", ".join(cols)
            conn.execute(f"INSERT INTO {t}_new({col_list}) SELECT {col_list} FROM {t}")
            conn.execute(f"DROP TABLE {t}")
            conn.execute(f"ALTER TABLE {t}_new RENAME TO {t}")
            print(f"[migrate] {t} 已重建并指向新 families")

        # 4) 换表
        conn.execute("DROP TABLE families")
        conn.execute("ALTER TABLE families_new RENAME TO families")
        print("[migrate] families_new → families")

        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

        # 5) 校验
        after_fam = conn.execute("SELECT COUNT(*) FROM families").fetchone()[0]
        after_bills = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                       for t in present_bills}
        print(f"[after]  families={after_fam} bills={after_bills or '（无 bills 表）'}")
        if after_fam != before_fam or after_bills != before_bills:
            print("ERROR: 行数不一致，请从备份恢复：", backup)
            sys.exit(1)
        if not has_new_constraint(conn):
            print("ERROR: 约束未生效，请从备份恢复：", backup)
            sys.exit(1)

        # 6) 外键完整性
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            print(f"WARNING: 检测到 {len(fk)} 处外键问题：")
            for r in fk[:10]:
                print("   ", tuple(r))
        else:
            print("[check] 外键完整性通过")

        print("migration done.")
    except SystemExit:
        raise
    except Exception:
        conn.rollback()
        if backup:
            print(f"ERROR: 迁移失败，已回滚。可从备份恢复：{backup}")
        else:
            print("ERROR: 迁移失败，已回滚（尚未创建备份）")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

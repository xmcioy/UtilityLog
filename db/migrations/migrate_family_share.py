#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 0.4.0 迁移：建立 family_members 表并回填拥有者记录

背景
----
0.4.0 引入家庭共享：`family_members` 记录家庭成员，共享成员拥有与拥有者
同等的管理权限（可查看/新增/修改/删除该家庭账单）。

权限判断已改为「family_id ∈ 该用户可见家庭」，而可见家庭由
`families.user_id`（拥有者）与 `family_members`（成员）共同决定。
存量库的旧家庭没有 `family_members` 记录 —— 虽然 `families.user_id`
仍能让拥有者看到，但为保持数据一致（成员列表、role 展示、后续扩展），
需要为每个存量家庭补一条 `role='owner'` 记录。

本脚本：
  1. 备份数据库（SQLite；MySQL 请用 mysqldump）
  2. 建 family_members 表（IF NOT EXISTS）
  3. 为每个 families.user_id 非空的家庭回填 owner 记录
  4. 校验：每个家庭至少有一条 owner 记录；无孤儿成员

用法
----
  # SQLite
  python3 db/migrations/migrate_family_share.py

  # MySQL（表由 schema.mysql.sql 建好后运行，或脚本内部幂等建表）
  UL_BACKEND=mysql UL_APP_DIR=~/myapp/utilitylog python3 db/migrations/migrate_family_share.py

安全性
------
- 幂等：重复执行不会产生重复记录（INSERT ... 已存在则跳过）
- 先备份（SQLite）
- 失败自动回滚（SQLite 事务）；MySQL 逐条提交但每步幂等
"""
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import db_backend as D  # noqa: E402

DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS family_members (
    family_id  INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role       TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (family_id, user_id)
)
"""

DDL_MYSQL = """
CREATE TABLE IF NOT EXISTS family_members (
    family_id  BIGINT NOT NULL,
    user_id    BIGINT NOT NULL,
    role       VARCHAR(16) NOT NULL DEFAULT 'member',
    created_at DATETIME NOT NULL DEFAULT NOW(),
    PRIMARY KEY (family_id, user_id),
    KEY idx_family_members_user (user_id),
    CONSTRAINT fk_fm_family FOREIGN KEY (family_id) REFERENCES families(id) ON DELETE CASCADE,
    CONSTRAINT fk_fm_user   FOREIGN KEY (user_id)   REFERENCES users(id)   ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""


def main():
    backend = D.get_backend()
    print(f"[backend] {backend}")
    print(f"[app_dir] {D.resolve_app_dir()}")

    backup = None
    if backend == "sqlite":
        db = os.environ.get("UL_DB", str(D.resolve_app_dir() / "data" / "utility.db"))
        if Path(db).exists():
            backup = db + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S")
            shutil.copy2(db, backup)
            print(f"[backup] {backup}")

    conn = D.get_conn()
    try:
        # 1) 建表
        conn.execute(DDL_MYSQL if backend == "mysql" else DDL_SQLITE)
        print("[ddl] family_members 就绪")

        # 2) 回填 owner
        # 孤儿家庭（user_id 指向已被删除的用户，如 e2e 清理残留）无法建 member
        # 记录（外键约束）—— 跳过并告警，不让脏数据阻塞整个部署
        user_ids = {r["id"] for r in
                    conn.execute("SELECT id FROM users").fetchall()}
        fams = conn.execute(
            "SELECT id, name, user_id FROM families WHERE user_id IS NOT NULL").fetchall()
        print(f"[scan] 待处理家庭 {len(fams)} 个")

        added = skipped = 0
        for f in fams:
            if f["user_id"] not in user_ids:
                skipped += 1
                print(f"[warn] 跳过孤儿家庭 id={f['id']} name={f['name']!r}"
                      f"（user_id={f['user_id']} 已不存在，属历史测试残留）")
                continue
            exists = conn.execute(
                "SELECT 1 FROM family_members WHERE family_id=? AND user_id=?",
                (f["id"], f["user_id"])).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO family_members(family_id, user_id, role) VALUES (?,?,?)",
                (f["id"], f["user_id"], "owner"))
            added += 1
        conn.commit()
        print(f"[backfill] 新增 owner 记录 {added} 条"
              + (f"，跳过孤儿家庭 {skipped} 个" if skipped else ""))

        # 3) 校验（孤儿家庭不参与：它们本就无有效拥有者）
        # 注意：MySQL 后端用 DictCursor（返回 dict，只能用键访问），
        # SQLite 用 Row（键/索引皆可）—— 统一用「别名 + 键」保证双后端兼容。
        orphans = conn.execute(
            "SELECT f.id, f.name FROM families f "
            "LEFT JOIN family_members m ON m.family_id=f.id AND m.role='owner' "
            "WHERE f.user_id IS NOT NULL AND m.user_id IS NULL "
            "  AND EXISTS (SELECT 1 FROM users u WHERE u.id = f.user_id)").fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM family_members").fetchone()["c"]
        owners = conn.execute(
            "SELECT COUNT(*) AS c FROM family_members WHERE role='owner'").fetchone()["c"]
        members = conn.execute(
            "SELECT COUNT(*) AS c FROM family_members WHERE role='member'").fetchone()["c"]

        print("--- verification ---")
        print(f"family_members 总数: {total}（owner={owners}, member={members}）")
        if orphans:
            print(f"ERROR: {len(orphans)} 个家庭缺少 owner 记录：")
            for o in orphans:
                print(f"  family id={o['id']} name={o['name']!r}")
            sys.exit(1)
        print("[check] 每个家庭均有 owner 记录 ✅")
        print("migration done.")
    except SystemExit:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if backup:
            print(f"ERROR: 迁移失败，已回滚。可从备份恢复：{backup}")
        else:
            print("ERROR: 迁移失败")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

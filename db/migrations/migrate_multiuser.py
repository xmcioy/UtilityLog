#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UtilityLog 0.2 多用户迁移脚本
- 创建 users / api_tokens / user_settings 表（若不存在）
- 为 families / bills_* 增加 user_id 列
- 将现有全部历史数据（families + 三表账单）归属到配置凭据用户名下（默认 hh）
- 用户密码以 PBKDF2-SHA256 哈希写入 users 表，仓库内不出现明文

用法: python3 db/migrations/migrate_multiuser.py
凭据来源（同 auth_server.py 优先级）：
  1. 环境变量 UL_USER / UL_PASS
  2. 项目根 auth_config.json（{"user": "...", "pass": "..."}）
"""
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("UL_ROOT", Path(__file__).resolve().parent.parent.parent))
DB_PATH = os.environ.get("UL_DB", str(PROJECT_ROOT / "data" / "utility.db"))
CONFIG_FILE = PROJECT_ROOT / "auth_config.json"

PBKDF2_ITERATIONS = 120000


def load_credentials():
    user = os.environ.get("UL_USER")
    passwd = os.environ.get("UL_PASS")
    if user and passwd:
        return user, passwd
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            user = cfg.get("user")
            passwd = cfg.get("pass")
            if user and passwd:
                return user, passwd
        except Exception:
            pass
    return None, None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                     bytes.fromhex(salt_hex), int(iters))
        return secrets.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


def main():
    user, passwd = load_credentials()
    if not user or not passwd:
        raise SystemExit("ERROR: credentials not configured (set UL_USER/UL_PASS or auth_config.json)")
    if not Path(DB_PATH).exists():
        raise SystemExit(f"ERROR: database not found: {DB_PATH}")

    # 备份
    backup = str(DB_PATH) + ".bak-" + datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(DB_PATH, backup)
    print(f"[backup] {backup}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 1) 建多用户表
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        username      TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name  TEXT,
        created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        is_active     INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS api_tokens (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL REFERENCES users(id),
        token      TEXT NOT NULL UNIQUE,
        scope      TEXT NOT NULL DEFAULT 'bill:write',
        expires_at TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        last_used  TEXT
    );
    CREATE TABLE IF NOT EXISTS user_settings (
        user_id         INTEGER PRIMARY KEY REFERENCES users(id),
        model_api_base  TEXT,
        model_api_key   TEXT,
        model_name      TEXT,
        theme           TEXT DEFAULT 'light',
        updated_at      TEXT
    );
    """)
    print("[tables] users / api_tokens / user_settings ready")

    # 2) 创建/校验配置用户
    row = cur.execute("SELECT id, username, password_hash FROM users WHERE username=?", (user,)).fetchone()
    if row is None:
        cur.execute("INSERT INTO users(username, password_hash, display_name) VALUES (?,?,?)",
                    (user, hash_password(passwd), user))
        uid = cur.lastrowid
        print(f"[user] created '{user}' (id={uid}) with PBKDF2 hash")
    else:
        uid = row["id"]
        if not verify_password(passwd, row["password_hash"]):
            # 凭据变化时更新哈希，保持登录一致
            cur.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(passwd), uid))
            print(f"[user] '{user}' password hash refreshed (id={uid})")
        else:
            print(f"[user] '{user}' exists (id={uid}), hash verified")

    # 3) 增加 user_id 列
    altered = []
    for t in ("families", "bills_water", "bills_electric", "bills_gas"):
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})").fetchall()]
        if "user_id" not in cols:
            cur.execute(f"ALTER TABLE {t} ADD COLUMN user_id INTEGER REFERENCES users(id)")
            altered.append(t)
    conn.commit()
    print(f"[alter] user_id added to: {altered or 'none (already present)'}")

    # 4) 历史数据迁移到配置用户
    for t in ("families", "bills_water", "bills_electric", "bills_gas"):
        cur.execute(f"UPDATE {t} SET user_id=? WHERE user_id IS NULL", (uid,))
    conn.commit()
    print(f"[migrate] all existing rows assigned to user '{user}' (id={uid})")

    # 5) 校验
    fam_cnt = cur.execute("SELECT COUNT(*) FROM families WHERE user_id=?", (uid,)).fetchone()[0]
    water = cur.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM bills_water WHERE user_id=?", (uid,)).fetchone()
    elec = cur.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM bills_electric WHERE user_id=?", (uid,)).fetchone()
    gas = cur.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM bills_gas WHERE user_id=?", (uid,)).fetchone()
    orphan_fam = cur.execute("SELECT COUNT(*) FROM families WHERE user_id IS NULL").fetchone()[0]
    conn.commit()
    conn.close()

    print("--- verification ---")
    print(f"families: {fam_cnt} (orphan={orphan_fam})")
    print(f"bills_water: {water[0]} rows, total ¥{water[1]}")
    print(f"bills_electric: {elec[0]} rows, total ¥{elec[1]}")
    print(f"bills_gas: {gas[0]} rows, total ¥{gas[1]}")
    print("migration done.")


if __name__ == "__main__":
    main()

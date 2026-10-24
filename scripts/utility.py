#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 水电气账单数据管理脚本（0.3 双后端版）
- 多用户隔离（users + families.user_id + bills_*.user_id）
- 后端：SQLite 默认（<APP_DIR>/data/utility.db），MySQL 可选（UL_BACKEND=mysql + db_config.json）
- 运行目录：UL_APP_DIR（优先）→ UL_ROOT → 仓库根；配置凭据 auth_config.json 位于运行目录
- 支持 add / list / update / delete / add-family / list-users / init
- 所有数据操作按用户隔离，命令行 --user 指定操作者（默认取配置凭据用户）
"""
import argparse
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

import db_backend

APP_DIR = db_backend.resolve_app_dir()
DB_PATH = os.environ.get("UL_DB", str(APP_DIR / "data" / "utility.db"))
CONFIG_FILE = APP_DIR / "auth_config.json"
VALID_TYPES = ("water", "electric", "gas")
TYPE_NAMES = {"water": "水费", "electric": "电费", "gas": "燃气费"}


def load_credentials():
    """按 auth_server.py 同优先级读取配置凭据；未配置返回 (None, None)"""
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


# 默认操作用户：配置凭据中的用户名（未配置时为 None，各命令强制要求 --user）
DEFAULT_USER, _ = load_credentials()


def get_conn():
    return db_backend.get_conn()


def user_id_by_name(username):
    if not username:
        return None
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def require_user(username, cmd):
    """校验操作者存在；不存在则报错退出"""
    uid = user_id_by_name(username)
    if uid is None:
        print(f"error: user '{username}' not found (run: utility.py register --user {username} --password ...)")
        sys.exit(1)
    return uid


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120000)
    return f"pbkdf2_sha256$120000${salt.hex()}${digest.hex()}"


def _schema_file(name):
    # schema 文件位于仓库 db/ 下（源码随仓库走，与运行目录解耦）
    repo = Path(__file__).resolve().parent.parent
    return repo / "db" / name


def init_db():
    conn = get_conn()
    schema = _schema_file("schema.mysql.sql" if db_backend.get_backend() == "mysql" else "schema.sql")
    if not schema.exists():
        print(f"error: schema file not found: {schema}")
        sys.exit(1)
    conn.executescript(schema.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()
    print(f"db initialized ({db_backend.get_backend()}: users / families / bills_water / bills_electric / bills_gas)")


def register_user(username, password, display_name=None):
    if not username or not password:
        print("error: --user and --password required")
        sys.exit(1)
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO users(username, password_hash, display_name) VALUES (?,?,?)",
                           (username, hash_password(password), display_name or username))
        conn.commit()
        print(f"user registered: {username} (id={cur.lastrowid})")
    except Exception:
        print(f"user already exists: {username}")
    finally:
        conn.close()


def add_family(name, user):
    uid = require_user(user, "add-family")
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO families(name, user_id) VALUES (?,?)", (name, uid))
        conn.commit()
        print(f"family added: {name} (id={cur.lastrowid}, user={user})")
    except Exception:
        print(f"family already exists: {name}")
    finally:
        conn.close()


def list_families(user):
    uid = require_user(user, "list-families")
    conn = get_conn()
    rows = conn.execute("SELECT id, name, user_id FROM families WHERE user_id=? ORDER BY id", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def family_id_by_name(name, user):
    uid = require_user(user, "family lookup")
    conn = get_conn()
    row = conn.execute("SELECT id FROM families WHERE name=? AND user_id=?", (name, uid)).fetchone()
    conn.close()
    return row["id"] if row else None


def list_users():
    conn = get_conn()
    rows = conn.execute("SELECT id, username, display_name, is_active FROM users ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


TABLE_BY_TYPE = {
    "water": "bills_water",
    "electric": "bills_electric",
    "gas": "bills_gas",
}

# 各表可写字段集合（不含 id / family_id / user_id / bill_month / created_at）
TABLE_FIELDS = {
    "water": ["usage", "usage_unit", "prev_reading", "cur_reading", "water_unit_price",
              "sewage_unit_price", "water_fee", "sewage_fee", "amount", "bill_date",
              "image", "note", "current_tier", "tier_remaining", "year_usage", "tier_detail"],
    "electric": ["usage", "usage_unit", "prev_reading", "cur_reading", "unit_price",
                 "peak_prev_reading", "peak_cur_reading", "valley_prev_reading",
                 "valley_cur_reading", "peak_usage", "peak_price", "valley_usage",
                 "valley_price", "amount", "bill_date", "image", "note", "current_tier",
                 "tier_remaining", "year_usage", "tier_detail"],
    "gas": ["usage", "usage_unit", "prev_reading", "cur_reading", "unit_price",
            "amount", "bill_date", "image", "note", "current_tier", "tier_remaining",
            "year_usage", "tier_detail"],
}


def find_bill_table(bid, user=None, btype=None):
    """按 id 定位账单所属表，返回 (table, row) 或 (None, None)

    user 传入时强制校验归属（跨用户不可见/不可操作）。
    btype 传入时只在该表查找（用于 id 跨表冲突时消歧）。

    ⚠️ 三张 bills 表各自 AUTOINCREMENT，id 空间互不重叠 —— 同一个 id 可能
    同时存在于多张表（如三表都有 id=1）。此时必须由调用方传 btype 消歧，
    否则会命中错误的表（曾导致 delete/update 误伤其他费种的账单）。
    多表命中且未指定 btype 时返回 (None, None) 并由调用方报错提示。
    """
    conn = get_conn()
    try:
        uid = user_id_by_name(user) if user else None
        types = (btype,) if btype else VALID_TYPES
        hits = []
        for t in types:
            if t not in TABLE_BY_TYPE:
                continue
            table = TABLE_BY_TYPE[t]
            if user:
                row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?",
                                   (bid, uid)).fetchone()
            else:
                row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (bid,)).fetchone()
            if row is not None:
                hits.append((table, row))
        if not hits:
            return None, None
        if len(hits) > 1:
            # id 跨表冲突：必须消歧，避免误伤
            return None, None
        return hits[0]
    finally:
        conn.close()


def _norm_tier_detail(v):
    """tier_detail 统一序列化：dict/list → JSON 字符串；str → 合法 JSON 原样存，纯文本包一层。

    add 与 update 两条路径共用，保证落库内容始终是合法 JSON
    （前端 JSON.parse 无 try/catch，非法 JSON 会导致整张明细表渲染中断）。
    """
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            json.loads(s)
            return s
        except Exception:
            return json.dumps(s, ensure_ascii=False)
    return json.dumps(v, ensure_ascii=False)


def add_bill(family, month, btype, usage, amount, user=None, bill_date=None, image=None, note=None,
             prev_reading=None, cur_reading=None, unit_price=None,
             water_unit_price=None, sewage_unit_price=None,
             peak_usage=None, peak_price=None, valley_usage=None, valley_price=None,
             sewage_price=None,
             peak_prev_reading=None, peak_cur_reading=None,
             valley_prev_reading=None, valley_cur_reading=None,
             current_tier=None, tier_remaining=None, year_usage=None, tier_detail=None,
             water_fee=None, sewage_fee=None):
    uid = require_user(user, "add")
    fid = family_id_by_name(family, user)
    if fid is None:
        add_family(family, user)
        fid = family_id_by_name(family, user)
    if btype not in VALID_TYPES:
        print(f"invalid type {btype}, must be one of {VALID_TYPES}")
        sys.exit(1)
    table = TABLE_BY_TYPE[btype]
    # 兼容旧参数：sewage_price -> sewage_unit_price
    if sewage_unit_price is None and sewage_price is not None:
        sewage_unit_price = sewage_price
    fields = {
        "usage": usage,
        "usage_unit": "m³" if btype in ("water", "gas") else "kWh",
        "prev_reading": prev_reading,
        "cur_reading": cur_reading,
        "amount": amount,
        "bill_date": bill_date,
        "image": image,
        "note": note,
        "current_tier": current_tier,
        "tier_remaining": tier_remaining,
        "year_usage": year_usage,
        "tier_detail": _norm_tier_detail(tier_detail),
    }
    if btype == "water":
        fields.update(water_unit_price=water_unit_price, sewage_unit_price=sewage_unit_price,
                      water_fee=water_fee, sewage_fee=sewage_fee)
    else:
        fields.update(unit_price=unit_price)
        if btype == "electric":
            fields.update(peak_usage=peak_usage, peak_price=peak_price,
                          valley_usage=valley_usage, valley_price=valley_price,
                          peak_prev_reading=peak_prev_reading, peak_cur_reading=peak_cur_reading,
                          valley_prev_reading=valley_prev_reading, valley_cur_reading=valley_cur_reading)
    cols = list(dict.fromkeys(["usage", "amount"] + [k for k in TABLE_FIELDS[btype] if fields.get(k) is not None]))
    # upsert 字段（排除 NULL；为空时全列兜底）
    upd_cols = cols if cols else TABLE_FIELDS[btype]
    vals = [fields[c] for c in cols]
    sql = db_backend.upsert_sql(
        table,
        ["family_id", "user_id", "bill_month"] + cols,
        len(cols) + 3,
        ["family_id", "bill_month"],
        upd_cols,
    )
    conn = get_conn()
    try:
        conn.execute(sql, [fid, uid, month] + vals)
        conn.commit()
        row = conn.execute(
            f"SELECT id FROM {table} WHERE family_id=? AND bill_month=? AND user_id=?",
            (fid, month, uid)).fetchone()
        print(f"bill saved: user={user} family={family} month={month} type={btype} usage={usage} amount={amount} id={row['id']} (upsert)")
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)
    finally:
        conn.close()


def update_bill(bid, user=None, btype=None, **fields):
    # 兼容旧参数名
    if "sewage_price" in fields and fields.get("sewage_unit_price") is None:
        fields["sewage_unit_price"] = fields.pop("sewage_price")
    fields.pop("sewage_price", None)
    if "month" in fields and fields.get("bill_month") is None:
        fields["bill_month"] = fields.pop("month")
    fields.pop("month", None)
    if "type" in fields:
        print("type cannot be changed (bill routed by table); ignoring")
        fields.pop("type", None)
    # 账期字段改名后需纳入可写白名单
    allowed = set(TABLE_FIELDS.get(btype, [])) | {"bill_month"}
    # 校验操作者存在，避免 user_id=NULL 导致静默无操作
    uid = require_user(user, "update")
    table, row = find_bill_table(bid, user, btype)
    if table is None:
        hits = _bill_type_candidates(bid, user)
        if len(hits) > 1:
            print(f"error: id {bid} 在多个费种表中存在（{', '.join(hits)}），"
                  f"请用 --type 指定：--type {hits[0]}")
        else:
            print(f"bill {bid} not found (or not owned by user '{user}')")
        return
    btype = "water" if table == "bills_water" else ("electric" if table == "bills_electric" else "gas")
    allowed = set(TABLE_FIELDS[btype]) | {"bill_month"}
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            if k == 'tier_detail':
                v = _norm_tier_detail(v)
                if v is None:
                    continue
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        print("no fields to update")
        return
    conn = get_conn()
    cur = conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=? AND user_id=?",
                       vals + [bid, uid])
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        print(f"bill {bid} not found or not owned by user '{user}'")
        return
    print(f"bill {bid} updated ({btype}) by {user}")


def delete_bill(bid, user=None, btype=None):
    # 校验操作者存在，避免 user_id=NULL 导致静默无操作
    uid = require_user(user, "delete")
    table, row = find_bill_table(bid, user, btype)
    if table is None:
        hits = _bill_type_candidates(bid, user)
        if len(hits) > 1:
            print(f"error: id {bid} 在多个费种表中存在（{', '.join(hits)}），"
                  f"请用 --type 指定：--type {hits[0]}")
        else:
            print(f"bill {bid} not found (or not owned by user '{user}')")
        return
    conn = get_conn()
    cur = conn.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (bid, uid))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        print(f"bill {bid} not found or not owned by user '{user}'")
        return
    print(f"bill {bid} deleted ({table}) by {user}")


def _bill_type_candidates(bid, user=None):
    """返回该 id 命中的所有费种表名（用于 id 跨表冲突时提示消歧）"""
    conn = get_conn()
    try:
        uid = user_id_by_name(user) if user else None
        hits = []
        for t in VALID_TYPES:
            table = TABLE_BY_TYPE[t]
            if user:
                row = conn.execute(f"SELECT 1 FROM {table} WHERE id=? AND user_id=?",
                                   (bid, uid)).fetchone()
            else:
                row = conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (bid,)).fetchone()
            if row is not None:
                hits.append(t)
        return hits
    finally:
        conn.close()


# 三表 UNION 的统一列投影（含 sewage_price 兼容别名；非本表字段一律 NULL）
UNION_COLS = """
    SELECT n.id, n.family_id, f.name AS family, n.user_id, n.bill_month AS month,
           'water' AS type, n.usage, n.usage_unit, n.amount,
           NULL AS unit_price, n.water_unit_price, n.sewage_unit_price,
           n.water_fee, n.sewage_fee,
           n.prev_reading, n.cur_reading,
           NULL AS peak_usage, NULL AS peak_price, NULL AS valley_usage, NULL AS valley_price,
           NULL AS peak_prev_reading, NULL AS peak_cur_reading,
           NULL AS valley_prev_reading, NULL AS valley_cur_reading,
           n.current_tier, n.tier_remaining, n.year_usage, n.tier_detail,
           n.bill_date, n.image, n.note, n.created_at,
           n.sewage_unit_price AS sewage_price
    FROM bills_water n JOIN families f ON n.family_id=f.id
    UNION ALL
    SELECT n.id, n.family_id, f.name AS family, n.user_id, n.bill_month AS month,
           'electric' AS type, n.usage, n.usage_unit, n.amount,
           n.unit_price, NULL, NULL, NULL, NULL,
           n.prev_reading, n.cur_reading,
           n.peak_usage, n.peak_price, n.valley_usage, n.valley_price,
           n.peak_prev_reading, n.peak_cur_reading,
           n.valley_prev_reading, n.valley_cur_reading,
           n.current_tier, n.tier_remaining, n.year_usage, n.tier_detail,
           n.bill_date, n.image, n.note, n.created_at,
           NULL AS sewage_price
    FROM bills_electric n JOIN families f ON n.family_id=f.id
    UNION ALL
    SELECT n.id, n.family_id, f.name AS family, n.user_id, n.bill_month AS month,
           'gas' AS type, n.usage, n.usage_unit, n.amount,
           n.unit_price, NULL, NULL, NULL, NULL,
           n.prev_reading, n.cur_reading,
           NULL AS peak_usage, NULL AS peak_price, NULL AS valley_usage, NULL AS valley_price,
           NULL AS peak_prev_reading, NULL AS peak_cur_reading,
           NULL AS valley_prev_reading, NULL AS valley_cur_reading,
           n.current_tier, n.tier_remaining, n.year_usage, n.tier_detail,
           n.bill_date, n.image, n.note, n.created_at,
           NULL AS sewage_price
    FROM bills_gas n JOIN families f ON n.family_id=f.id
"""


def query_bills(user, where="", args=(), order="month DESC, type, id DESC"):
    uid = user_id_by_name(user)
    if uid is None:
        return []
    conn = get_conn()
    # 外层只能引用 UNION 输出列（user_id），不能引用内层表别名
    sql = (f"SELECT * FROM ({UNION_COLS}) AS u WHERE user_id=? {where} "
           f"ORDER BY {order}")
    rows = conn.execute(sql, [uid] + list(args)).fetchall()
    conn.close()
    # MySQL DATETIME 返回 datetime 对象，统一转 ISO 字符串保证 JSON 可序列化
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, datetime):
                d[k] = v.isoformat(sep=" ", timespec="seconds")
        out.append(d)
    return out


def list_bills(user, family=None, month=None, btype=None):
    where, args = "", []
    if family:
        where += " AND family=?"
        args.append(family)
    if month:
        where += " AND month=?"
        args.append(month)
    if btype:
        where += " AND type=?"
        args.append(btype)
    return query_bills(user, where, args, "month DESC, type, id DESC")


def dump_json(user):
    """输出指定用户的完整数据（供 sync_site.py / auth_server.py 使用）"""
    uid = user_id_by_name(user)
    if uid is None:
        return {"families": [], "bills": []}
    conn = get_conn()
    families = [dict(r) for r in conn.execute(
        "SELECT id, name FROM families WHERE user_id=? ORDER BY id", (uid,)).fetchall()]
    bills = query_bills(user, order="month, type, id")
    conn.close()
    return {"user": {"id": uid, "username": user}, "families": families, "bills": bills}


def main():
    parser = argparse.ArgumentParser(description="UtilityLog 水电气账单管理（多用户，SQLite/MySQL 双后端）")
    parser.add_argument("--user", default=DEFAULT_USER, help="操作用户名（默认取配置凭据用户）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.set_defaults(func=lambda a: init_db())

    p_reg = sub.add_parser("register")
    p_reg.add_argument("--password", required=True, help="密码（仅本地写入 users 表哈希）")
    p_reg.add_argument("--display-name", dest="display_name", default=None)
    p_reg.set_defaults(func=lambda a: register_user(a.user, a.password, a.display_name))

    p_lu = sub.add_parser("list-users")
    p_lu.set_defaults(func=lambda a: print(json.dumps(list_users(), ensure_ascii=False, indent=2)))

    p_fa = sub.add_parser("add-family")
    p_fa.add_argument("name")
    p_fa.set_defaults(func=lambda a: add_family(a.name, a.user))

    p_add = sub.add_parser("add")
    p_add.add_argument("--family", required=True, help="家庭名")
    p_add.add_argument("--month", required=True, help="月份 YYYY-MM")
    p_add.add_argument("--type", required=True, choices=VALID_TYPES)
    p_add.add_argument("--usage", type=float, required=True, help="用量")
    p_add.add_argument("--prev-reading", dest="prev_reading", type=float, default=None, help="上次抄表数")
    p_add.add_argument("--cur-reading", dest="cur_reading", type=float, default=None, help="本次抄表数")
    p_add.add_argument("--unit-price", dest="unit_price", type=float, default=None, help="单价（元，electric/gas）")
    p_add.add_argument("--water-unit-price", dest="water_unit_price", type=float, default=None, help="水费单价（元/m³，water）")
    p_add.add_argument("--sewage-unit-price", dest="sewage_unit_price", type=float, default=None, help="污水单价（元/m³，water）")
    p_add.add_argument("--sewage-price", dest="sewage_price", type=float, default=None, help="污水单价别名（兼容旧参数）")
    p_add.add_argument("--amount", type=float, required=True, help="费用（元）")
    p_add.add_argument("--bill-date", dest="bill_date", default=None)
    p_add.add_argument("--image", default=None)
    p_add.add_argument("--note", default=None)
    p_add.add_argument("--water-fee", dest="water_fee", type=float, default=None, help="水费金额（元）")
    p_add.add_argument("--sewage-fee", dest="sewage_fee", type=float, default=None, help="污水费金额（元）")
    p_add.add_argument("--peak-usage", dest="peak_usage", type=float, default=None, help="峰电量（electric）")
    p_add.add_argument("--peak-price", dest="peak_price", type=float, default=None, help="峰单价（electric）")
    p_add.add_argument("--valley-usage", dest="valley_usage", type=float, default=None, help="谷电量（electric）")
    p_add.add_argument("--valley-price", dest="valley_price", type=float, default=None, help="谷单价（electric）")
    p_add.add_argument("--peak-prev-reading", dest="peak_prev_reading", type=float, default=None,
                       help="峰上期示数（electric）")
    p_add.add_argument("--peak-cur-reading", dest="peak_cur_reading", type=float, default=None,
                       help="峰本期示数（electric）")
    p_add.add_argument("--valley-prev-reading", dest="valley_prev_reading", type=float, default=None,
                       help="谷上期示数（electric）")
    p_add.add_argument("--valley-cur-reading", dest="valley_cur_reading", type=float, default=None,
                       help="谷本期示数（electric）")
    p_add.add_argument("--current-tier", dest="current_tier", default=None, help="当前档位（如 第一档）")
    p_add.add_argument("--tier-remaining", dest="tier_remaining", type=float, default=None, help="本档剩余量")
    p_add.add_argument("--year-usage", dest="year_usage", type=float, default=None, help="年累计用量")
    p_add.add_argument("--tier-detail", dest="tier_detail", default=None,
                       help="档位明细（JSON 字符串或纯文本）")
    p_add.set_defaults(func=lambda a: add_bill(a.family, a.month, a.type, a.usage, a.amount,
                                               user=a.user,
                                               bill_date=a.bill_date, image=a.image, note=a.note,
                                               prev_reading=a.prev_reading, cur_reading=a.cur_reading,
                                               unit_price=a.unit_price,
                                               water_unit_price=a.water_unit_price,
                                               sewage_unit_price=a.sewage_unit_price,
                                               peak_usage=a.peak_usage, peak_price=a.peak_price,
                                               valley_usage=a.valley_usage, valley_price=a.valley_price,
                                               sewage_price=a.sewage_price,
                                               peak_prev_reading=a.peak_prev_reading,
                                               peak_cur_reading=a.peak_cur_reading,
                                               valley_prev_reading=a.valley_prev_reading,
                                               valley_cur_reading=a.valley_cur_reading,
                                               current_tier=a.current_tier,
                                               tier_remaining=a.tier_remaining,
                                               year_usage=a.year_usage,
                                               tier_detail=a.tier_detail,
                                               water_fee=a.water_fee, sewage_fee=a.sewage_fee))

    p_up = sub.add_parser("update")
    p_up.add_argument("id", type=int)
    p_up.add_argument("--month", default=None, help="账期 YYYY-MM（可改）")
    p_up.add_argument("--type", default=None, choices=VALID_TYPES,
                      help="费种（id 跨表冲突时用于消歧定位）")
    p_up.add_argument("--usage", type=float, default=None)
    p_up.add_argument("--usage-unit", dest="usage_unit", default=None)
    p_up.add_argument("--prev-reading", dest="prev_reading", type=float, default=None)
    p_up.add_argument("--cur-reading", dest="cur_reading", type=float, default=None)
    p_up.add_argument("--unit-price", dest="unit_price", type=float, default=None)
    p_up.add_argument("--water-unit-price", dest="water_unit_price", type=float, default=None)
    p_up.add_argument("--sewage-unit-price", dest="sewage_unit_price", type=float, default=None)
    p_up.add_argument("--peak-usage", dest="peak_usage", type=float, default=None)
    p_up.add_argument("--peak-price", dest="peak_price", type=float, default=None)
    p_up.add_argument("--valley-usage", dest="valley_usage", type=float, default=None)
    p_up.add_argument("--valley-price", dest="valley_price", type=float, default=None)
    p_up.add_argument("--peak-prev-reading", dest="peak_prev_reading", type=float, default=None)
    p_up.add_argument("--peak-cur-reading", dest="peak_cur_reading", type=float, default=None)
    p_up.add_argument("--valley-prev-reading", dest="valley_prev_reading", type=float, default=None)
    p_up.add_argument("--valley-cur-reading", dest="valley_cur_reading", type=float, default=None)
    p_up.add_argument("--sewage-price", dest="sewage_price", type=float, default=None)
    p_up.add_argument("--amount", type=float, default=None)
    p_up.add_argument("--bill-date", dest="bill_date", default=None)
    p_up.add_argument("--image", default=None)
    p_up.add_argument("--note", default=None)
    p_up.add_argument("--water-fee", dest="water_fee", type=float, default=None)
    p_up.add_argument("--sewage-fee", dest="sewage_fee", type=float, default=None)
    p_up.add_argument("--current-tier", dest="current_tier", default=None, help="当前档位")
    p_up.add_argument("--tier-remaining", dest="tier_remaining", type=float, default=None, help="本档剩余量")
    p_up.add_argument("--year-usage", dest="year_usage", type=float, default=None, help="年累计用量")
    p_up.add_argument("--tier-detail", dest="tier_detail", default=None, help="档位明细（JSON 字符串或纯文本）")
    p_up.set_defaults(func=lambda a: update_bill(
        a.id, user=a.user, btype=a.type, month=a.month, usage=a.usage, usage_unit=a.usage_unit,
        prev_reading=a.prev_reading, cur_reading=a.cur_reading, unit_price=a.unit_price,
        water_unit_price=a.water_unit_price, sewage_unit_price=a.sewage_unit_price,
        peak_usage=a.peak_usage, peak_price=a.peak_price, valley_usage=a.valley_usage,
        valley_price=a.valley_price, sewage_price=a.sewage_price,
        peak_prev_reading=a.peak_prev_reading, peak_cur_reading=a.peak_cur_reading,
        valley_prev_reading=a.valley_prev_reading, valley_cur_reading=a.valley_cur_reading,
        amount=a.amount, bill_date=a.bill_date, image=a.image, note=a.note,
        current_tier=a.current_tier, tier_remaining=a.tier_remaining,
        year_usage=a.year_usage, tier_detail=a.tier_detail,
        water_fee=a.water_fee, sewage_fee=a.sewage_fee))

    p_del = sub.add_parser("delete")
    p_del.add_argument("id", type=int)
    p_del.add_argument("--type", default=None, choices=VALID_TYPES,
                       help="费种（id 跨表冲突时用于消歧定位）")
    p_del.set_defaults(func=lambda a: delete_bill(a.id, a.user, a.type))

    p_ls = sub.add_parser("list")
    p_ls.add_argument("--family", default=None)
    p_ls.add_argument("--month", default=None)
    p_ls.add_argument("--type", default=None)
    p_ls.set_defaults(func=lambda a: print(json.dumps(list_bills(a.user, a.family, a.month, a.type),
                                                     ensure_ascii=False, indent=2)))

    p_dump = sub.add_parser("dump")
    p_dump.set_defaults(func=lambda a: print(json.dumps(dump_json(a.user), ensure_ascii=False, indent=2)))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

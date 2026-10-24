#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UtilityLog 水电气账单数据管理脚本
- 多家庭独立数据（families + bills）
- 支持 add / list / update / delete / add-family / init
- 数据文件: <项目根>/data/utility.db（项目根由 UL_ROOT 环境变量或脚本位置推导）
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("UL_ROOT", Path(__file__).resolve().parent.parent))
DB_PATH = os.environ.get("UL_DB", str(PROJECT_ROOT / "data" / "utility.db"))
VALID_TYPES = ("water", "electric", "gas")
TYPE_NAMES = {"water": "水费", "electric": "电费", "gas": "燃气费"}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS families (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bills_water (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL REFERENCES families(id),
            bill_month TEXT NOT NULL,          -- YYYY-MM
            usage REAL,                        -- 用量
            usage_unit TEXT DEFAULT 'm³',
            prev_reading REAL,
            cur_reading REAL,
            water_unit_price REAL,             -- 水费单价（元/m³）
            sewage_unit_price REAL,            -- 污水单价（元/m³）
            water_fee REAL,                    -- 水费金额
            sewage_fee REAL,                   -- 污水费金额
            amount REAL,                       -- 费用合计（元）
            bill_date TEXT,                    -- 账单日期 YYYY-MM-DD
            image TEXT,                        -- 截图路径（相对 site/images）
            note TEXT,
            current_tier TEXT,
            tier_remaining REAL,
            year_usage REAL,
            tier_detail TEXT,                  -- JSON 字符串
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(family_id, bill_month)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bills_electric (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL REFERENCES families(id),
            bill_month TEXT NOT NULL,          -- YYYY-MM
            usage REAL,                        -- 总用量（kWh）
            usage_unit TEXT DEFAULT 'kWh',
            prev_reading REAL,
            cur_reading REAL,
            unit_price REAL,                   -- 综合单价（元/kWh）
            peak_prev_reading REAL,
            peak_cur_reading REAL,
            valley_prev_reading REAL,
            valley_cur_reading REAL,
            peak_usage REAL,
            peak_price REAL,
            valley_usage REAL,
            valley_price REAL,
            amount REAL,                       -- 费用合计（元）
            bill_date TEXT,
            image TEXT,
            note TEXT,
            current_tier TEXT,
            tier_remaining REAL,
            year_usage REAL,
            tier_detail TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(family_id, bill_month)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bills_gas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_id INTEGER NOT NULL REFERENCES families(id),
            bill_month TEXT NOT NULL,          -- YYYY-MM
            usage REAL,                        -- 用量
            usage_unit TEXT DEFAULT 'm³',
            prev_reading REAL,
            cur_reading REAL,
            unit_price REAL,                   -- 单价（元/m³）
            amount REAL,                       -- 费用（元）
            bill_date TEXT,
            image TEXT,
            note TEXT,
            current_tier TEXT,
            tier_remaining REAL,
            year_usage REAL,
            tier_detail TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(family_id, bill_month)
        )
    """)
    conn.commit()
    conn.close()
    print("db initialized (bills_water / bills_electric / bills_gas)")


def add_family(name):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO families(name) VALUES (?)", (name,))
        conn.commit()
        print(f"family added: {name} (id={cur.lastrowid})")
    except sqlite3.IntegrityError:
        print(f"family already exists: {name}")
    finally:
        conn.close()


def list_families():
    conn = get_conn()
    rows = conn.execute("SELECT id, name FROM families ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def family_id_by_name(name):
    conn = get_conn()
    row = conn.execute("SELECT id FROM families WHERE name=?", (name,)).fetchone()
    conn.close()
    return row["id"] if row else None


TABLE_BY_TYPE = {
    "water": "bills_water",
    "electric": "bills_electric",
    "gas": "bills_gas",
}

# 各表可写字段集合（不含 id / family_id / bill_month / created_at）
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


def find_bill_table(bid):
    """按 id 定位账单所属表，返回 (table, row) 或 (None, None)"""
    conn = get_conn()
    try:
        for t in VALID_TYPES:
            row = conn.execute(f"SELECT * FROM {TABLE_BY_TYPE[t]} WHERE id=?", (bid,)).fetchone()
            if row is not None:
                return TABLE_BY_TYPE[t], row
        return None, None
    finally:
        conn.close()


def add_bill(family, month, btype, usage, amount, bill_date=None, image=None, note=None,
             prev_reading=None, cur_reading=None, unit_price=None,
             water_unit_price=None, sewage_unit_price=None,
             peak_usage=None, peak_price=None, valley_usage=None, valley_price=None,
             sewage_price=None,
             peak_prev_reading=None, peak_cur_reading=None,
             valley_prev_reading=None, valley_cur_reading=None,
             current_tier=None, tier_remaining=None, year_usage=None, tier_detail=None,
             water_fee=None, sewage_fee=None):
    fid = family_id_by_name(family)
    if fid is None:
        add_family(family)
        fid = family_id_by_name(family)
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
        "tier_detail": json.dumps(tier_detail, ensure_ascii=False) if tier_detail else None,
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
    placeholders = ",".join("?" for _ in cols)
    upserts = ",".join(f"{c}=excluded.{c}" for c in cols)
    vals = [fields[c] for c in cols]
    conn = get_conn()
    try:
        conn.execute(
            f"INSERT INTO {table}(family_id, bill_month, {', '.join(cols)}) "
            f"VALUES (?,?,{placeholders}) "
            f"ON CONFLICT(family_id, bill_month) DO UPDATE SET {upserts}",
            [fid, month] + vals,
        )
        conn.commit()
        row = conn.execute(
            f"SELECT id FROM {table} WHERE family_id=? AND bill_month=?", (fid, month)).fetchone()
        print(f"bill saved: family={family} month={month} type={btype} usage={usage} amount={amount} id={row['id']} (upsert)")
    except Exception as e:
        print(f"error: {e}")
        sys.exit(1)
    finally:
        conn.close()


def update_bill(bid, **fields):
    # 兼容旧参数名
    if "sewage_price" in fields and "sewage_unit_price" not in fields:
        fields["sewage_unit_price"] = fields.pop("sewage_price")
    if "month" in fields and "bill_month" not in fields:
        fields["bill_month"] = fields.pop("month")
    if "type" in fields:
        print("type cannot be changed (bill routed by table); ignoring")
        fields.pop("type", None)
    table, row = find_bill_table(bid)
    if table is None:
        print(f"bill {bid} not found")
        return
    btype = "water" if table == "bills_water" else ("electric" if table == "bills_electric" else "gas")
    allowed = set(TABLE_FIELDS[btype])
    sets = []
    vals = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            if k == 'tier_detail' and isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        print("no fields to update")
        return
    conn = get_conn()
    conn.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id=?", vals + [bid])
    conn.commit()
    conn.close()
    print(f"bill {bid} updated ({btype})")


def delete_bill(bid):
    table, row = find_bill_table(bid)
    if table is None:
        print(f"bill {bid} not found")
        return
    conn = get_conn()
    conn.execute(f"DELETE FROM {table} WHERE id=?", (bid,))
    conn.commit()
    conn.close()
    print(f"bill {bid} deleted ({table})")


# 三表 UNION 的统一列投影（含 sewage_price 兼容别名；非本表字段一律 NULL）
UNION_COLS = """
    SELECT n.id, n.family_id, f.name AS family, n.bill_month AS month,
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
    SELECT n.id, n.family_id, f.name AS family, n.bill_month AS month,
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
    SELECT n.id, n.family_id, f.name AS family, n.bill_month AS month,
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


def query_bills(where="", args=(), order="month DESC, type, id DESC"):
    conn = get_conn()
    sql = f"SELECT * FROM ({UNION_COLS}) WHERE 1=1 {where} ORDER BY {order}"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_bills(family=None, month=None, btype=None):
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
    return query_bills(where, args, "month DESC, type, id DESC")


def dump_json():
    """输出完整数据（供 sync_site.py 使用）"""
    conn = get_conn()
    families = [dict(r) for r in conn.execute("SELECT id, name FROM families ORDER BY id").fetchall()]
    bills = query_bills(order="month, type, id")
    conn.close()
    return {"families": families, "bills": bills}


def main():
    parser = argparse.ArgumentParser(description="UtilityLog 水电气账单管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init")
    p_init.set_defaults(func=lambda a: init_db())

    p_fa = sub.add_parser("add-family")
    p_fa.add_argument("name")
    p_fa.set_defaults(func=lambda a: add_family(a.name))

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
    p_add.set_defaults(func=lambda a: add_bill(a.family, a.month, a.type, a.usage, a.amount,
                                               a.bill_date, a.image, a.note,
                                               a.prev_reading, a.cur_reading, a.unit_price,
                                               a.water_unit_price, a.sewage_unit_price,
                                               a.peak_usage, a.peak_price, a.valley_usage,
                                               a.valley_price, a.sewage_price,
                                               water_fee=a.water_fee, sewage_fee=a.sewage_fee))

    p_up = sub.add_parser("update")
    p_up.add_argument("id", type=int)
    p_up.add_argument("--month", default=None)
    p_up.add_argument("--type", default=None)
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
    p_up.add_argument("--sewage-price", dest="sewage_price", type=float, default=None)
    p_up.add_argument("--amount", type=float, default=None)
    p_up.add_argument("--bill-date", dest="bill_date", default=None)
    p_up.add_argument("--image", default=None)
    p_up.add_argument("--note", default=None)
    p_up.add_argument("--water-fee", dest="water_fee", type=float, default=None)
    p_up.add_argument("--sewage-fee", dest="sewage_fee", type=float, default=None)
    p_up.set_defaults(func=lambda a: update_bill(
        a.id, month=a.month, usage=a.usage, usage_unit=a.usage_unit,
        prev_reading=a.prev_reading, cur_reading=a.cur_reading, unit_price=a.unit_price,
        water_unit_price=a.water_unit_price, sewage_unit_price=a.sewage_unit_price,
        peak_usage=a.peak_usage, peak_price=a.peak_price, valley_usage=a.valley_usage,
        valley_price=a.valley_price, sewage_price=a.sewage_price,
        amount=a.amount, bill_date=a.bill_date, image=a.image, note=a.note,
        water_fee=a.water_fee, sewage_fee=a.sewage_fee))

    p_del = sub.add_parser("delete")
    p_del.add_argument("id", type=int)
    p_del.set_defaults(func=lambda a: delete_bill(a.id))

    p_ls = sub.add_parser("list")
    p_ls.add_argument("--family", default=None)
    p_ls.add_argument("--month", default=None)
    p_ls.add_argument("--type", default=None)
    p_ls.set_defaults(func=lambda a: print(json.dumps(list_bills(a.family, a.month, a.type),
                                                     ensure_ascii=False, indent=2)))

    p_dump = sub.add_parser("dump")
    p_dump.set_defaults(func=lambda a: print(json.dumps(dump_json(), ensure_ascii=False, indent=2)))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

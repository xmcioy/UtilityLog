#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bill_parser 单元测试：python3 scripts/test_bill_parser.py（直接运行，零依赖）"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bill_parser as P

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(("  ✅ " if ok else "  ❌ ") + name + (f"  [{detail}]" if detail else ""))


# ---- 电费：国网上海分时（脱敏样例文本，保留版式特征含换行） ----
ELEC_TEXT = """第1页/共1页
国 网 上 海 市 电 力 公 司
电 费 账 单
本期电费：7.70元 缴费截止日期：2025-05-31账单周期 账单年月 202504
2025-04-01 户号 0000000000000 用电类别 城镇居民生活用电
本期电量 14千瓦时 本期电费 7.70元 交费截止日期 2025-05-31
正向有功（平） 0 11 1 11
正向有功（谷） 0 3 1 3
居民分时,电压220V(平)电度电费 11 0.6170 6.79
居民分时,电压220V(谷)电度电费 3 0.3070 0.92
小计 ￥7.71
本月应付电费 7.71
本月转结零头 0.01
本月实付电费 7.70
5.为确保您的资金及时到户，截止至2025年04月底，贵户今年累计已用阶梯电量14千瓦时。第一档电量可用2600千瓦时，还剩2586千瓦时。
"""
b = P._parse_electric(ELEC_TEXT)
check("电：月份 2025-04", b.get("month") == "2025-04", str(b.get("month")))
check("电：峰电量/示数", b.get("peak_usage") == 11.0 and
      b.get("peak_prev_reading") == 0.0 and b.get("peak_cur_reading") == 11.0,
      str(b.get("peak_usage")))
check("电：谷电量/示数", b.get("valley_usage") == 3.0 and
      b.get("valley_cur_reading") == 3.0, str(b.get("valley_usage")))
check("电：峰谷单价", b.get("peak_price") == 0.617 and b.get("valley_price") == 0.307,
      f"{b.get('peak_price')}/{b.get('valley_price')}")
check("电：金额取应付 7.71（不变式 11×0.617+3×0.307）",
      abs(b.get("amount", 0) - (11 * 0.617 + 3 * 0.307)) < 0.01, str(b.get("amount")))
check("电：档位/剩余/年累计", b.get("current_tier") == "第一档" and
      b.get("tier_remaining") == 2586.0 and b.get("year_usage") == 14.0,
      str(b.get("tier_remaining")))
check("电：实付差异写入 note", "实付" in (b.get("note") or ""), str(b.get("note")))

# ---- 电费：非分时兜底 ----
SIMPLE_ELEC = """账单年月 202608
本期电量 120千瓦时 本期电费 60.00元
总电度电费 120 0.5000 60.00
"""
b2 = P._parse_electric(SIMPLE_ELEC)
check("电：非分时兜底 unit_price", b2.get("month") == "2026-08" and
      abs((b2.get("unit_price") or 0) - 0.5) < 0.001, str(b2.get("unit_price")))

# ---- 燃气：上海燃气（含「立方米」被拆行的真实版式） ----
GAS_TEXT = """2026 10
天然气6G10 00000000
测试用户
第一阶梯 7 3.00 21.00
21.00元 预付款余额  338.50
截止本次账单，贵户用气年度累计气量已达217立方米。第一档可用气量310立
方米，还剩余93立方米。
结算周期：2026年08月03日-2026年10月02日
"""
b3 = P._parse_gas(GAS_TEXT)
check("气：月份取结算周期结束月 2026-10", b3.get("month") == "2026-10", str(b3.get("month")))
check("气：档位/用量/单价/金额", b3.get("current_tier") == "第一档" and
      b3.get("usage") == 7.0 and b3.get("unit_price") == 3.0 and
      b3.get("amount") == 21.0, str(b3))
check("气：年累计 217", b3.get("year_usage") == 217.0, str(b3.get("year_usage")))
check("气：跨行「立方米」仍能取到剩余 93", b3.get("tier_remaining") == 93.0,
      str(b3.get("tier_remaining")))

# ---- 水费：供水账单（水费+污水费分项） ----
WATER_TEXT = """2026年10月14日
本期账单用量10吨
水费 10吨 40.50
上期表读数 80
本期表读数 90
水费 2.25 10 22.50
污水费 2.00 10 18.00
（水资源税相关成本费用0.1元/m³）
最后付款日期 2026-11-06
"""
b4 = P._parse_water(WATER_TEXT)
check("水：用量/示数", b4.get("usage") == 10.0 and b4.get("prev_reading") == 80.0
      and b4.get("cur_reading") == 90.0, str(b4.get("usage")))
check("水：水费分项单价", b4.get("water_unit_price") == 2.25 and
      b4.get("sewage_unit_price") == 2.00, str(b4.get("water_unit_price")))
check("水：金额=水费+污水费=40.50（不变式）",
      abs((b4.get("amount") or 0) - 40.50) < 0.001, str(b4.get("amount")))

# ---- 类型判别与文件入口 ----
d = P.parse_bill_file("/nonexistent.pdf", "x.pdf")
check("PDF 缺失/损坏 → 优雅返回错误", d["parse_ok"] is False and d["message"] != "",
      d["message"][:40])

d = P.parse_bill_file("/tmp/x.txt", "x.txt")
check("不支持的类型 → 明确提示", "不支持的文件类型" in d["message"], d["message"][:40])

# pypdf 未安装时给出可执行的安装提示
_real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__


def _no_pypdf(name, *a, **k):
    if name == "pypdf":
        raise ImportError("blocked for test")
    return _real_import(name, *a, **k)


builtins_mod = sys.modules["builtins"]
_orig = builtins_mod.__import__
builtins_mod.__import__ = _no_pypdf
try:
    d = P.parse_bill_file("/tmp/fake.pdf", "x.pdf")
finally:
    builtins_mod.__import__ = _orig
check("pypdf 缺失 → 返回安装提示", "pip install --user pypdf" in d.get("message", ""),
      d.get("message", "")[:60])

# ---- 真实样例回归（本机存在时） ----
for path, btype, expects in (
    ("/tmp/ul_bills/bill_202504.pdf", "electric", {"month": "2025-04", "amount": 7.71,
                                                   "peak_usage": 11.0, "valley_usage": 3.0,
                                                   "tier_remaining": 2586.0}),
    ("/tmp/ul_bills/bill_202610.pdf", "gas", {"month": "2026-10", "amount": 21.0,
                                              "usage": 7.0, "tier_remaining": 93.0}),
):
    if not os.path.exists(path):
        continue
    d = P.parse_bill_file(path, os.path.basename(path))
    ok = d["parse_ok"] and d["bill_type"] == btype and all(
        d["bill"].get(k) == v for k, v in expects.items())
    check(f"真实样例 {os.path.basename(path)} → {btype}", ok, json.dumps(
        {k: d["bill"].get(k) for k in expects}, ensure_ascii=False))

print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
sys.exit(1 if FAIL else 0)

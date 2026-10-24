#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账单自动解析（0.5.0 新增，供网页上传识别使用）

输入：账单文件（PDF / 图片）→ 输出：add_bill 兼容的字段草稿。

设计约束：
  - 纯标准库；PDF 文本抽取用 pypdf（可选依赖，deploy.sh 会 best-effort 安装），
    未安装时优雅降级返回明确提示，绝不抛异常打断服务
  - 只做「文本层」解析，不做 OCR：图片类走可选的视觉模型 API
    （设置页配置的 model_api_base/model_api_key，OpenAI 兼容接口）
  - 识别失败不编造：只输出匹配到的字段，缺失留空，由前端草稿表单人工补全
  - 金额不变式：电 amount 优先取「本月应付电费」（= 平×峰价 + 谷×谷价），
    实付与应付的零头差异写入 note

当前支持的模板（按文本特征自动判别）：
  1. 国网上海电费账单（分时平/谷 + 阶梯）  —— bill_type="electric"
  2. 上海燃气账单（第一/二/三阶梯 + 年度累计）—— bill_type="gas"
  3. 供水账单（水费 + 污水费分项）          —— bill_type="water"
其他电力/燃气公司版式可能也能匹配到部分字段（confidence=low）。
"""
import json
import re

# ---------------------------------------------------------------------------
# PDF 文本抽取
# ---------------------------------------------------------------------------

def _pdf_text(path):
    """抽取 PDF 全部文本；pypdf 未安装或解析失败返回 None"""
    try:
        import pypdf
    except ImportError:
        return None
    try:
        reader = pypdf.PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        print(f"[bill_parser] PDF 解析失败: {e}", flush=True)
        return None


PYPDF_HINT = ("服务器未安装 pypdf，无法解析 PDF 文本层。"
              "请在服务器执行：python3 -m pip install --user pypdf")


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

_NUM = r"([0-9]+(?:\.[0-9]+)?)"


def _f(s):
    """安全转 float；失败返回 None"""
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _month_from_yyyymm(s):
    m = re.search(r"(20\d{2})\s*[-/年]?\s*(0[1-9]|1[0-2])", s or "")
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# 电费：国网上海（分时平/谷）
# ---------------------------------------------------------------------------

def _parse_electric(text):
    bill, note_bits = {}, []

    # 账单年月：优先「账单年月 202504」
    m = re.search(r"账单年月\s*(20\d{2})(0[1-9]|1[0-2])", text)
    bill["month"] = f"{m.group(1)}-{m.group(2)}" if m else _month_from_yyyymm(text)

    # 峰/谷示数行：正向有功（平） 上期 本期 倍率 计费电量
    # 上海分时把「平」当峰段记录；个别账单直接印「峰」
    for tag, key in (("平", "peak"), ("谷", "valley"), ("峰", "peak")):
        m = re.search(rf"正向有功（{tag}）\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", text)
        if m and not bill.get(f"{key}_usage"):
            bill[f"{key}_prev_reading"] = _f(m.group(1))
            bill[f"{key}_cur_reading"] = _f(m.group(2))
            bill[f"{key}_usage"] = _f(m.group(4))

    # 电价：居民分时,电压220V(平)电度电费 11 0.6170 6.79
    for tag, key in (("平", "peak"), ("谷", "valley"), ("峰", "peak")):
        m = re.search(rf"{tag}\)电度电费\s*{_NUM}\s*{_NUM}\s*{_NUM}", text)
        if m and not bill.get(f"{key}_price"):
            bill[f"{key}_price"] = _f(m.group(2))
            if not bill.get(f"{key}_usage"):
                bill[f"{key}_usage"] = _f(m.group(1))

    # 总电量 / 总费用
    m = re.search(rf"本期电量\s*{_NUM}\s*千瓦时", text)
    if m:
        bill["usage"] = _f(m.group(1))
    # 金额优先级：本月应付电费（=分项之和）> 本期电费（实付）
    m = re.search(rf"本月应付电费\s*{_NUM}", text)
    if m:
        bill["amount"] = _f(m.group(1))
    m = re.search(rf"本期电费[：:\s]*{_NUM}\s*元", text)
    if m:
        paid = _f(m.group(1))
        bill.setdefault("amount", paid)
        if paid is not None and bill.get("amount") is not None \
                and abs(paid - bill["amount"]) > 0.001:
            note_bits.append(f"实付{paid}元（含转结零头），入库金额取应付{bill['amount']}元")

    # 阶梯：贵户今年累计已用阶梯电量14千瓦时。第一档电量可用2600千瓦时，还剩2586千瓦时
    # （PDF 常把单位词拆行，如「千瓦\n时」，故单位词内允许 \s*）
    m = re.search(rf"今年累计已用\s*阶\s*梯\s*电量\s*{_NUM}\s*千\s*瓦\s*时", text)
    if m:
        bill["year_usage"] = _f(m.group(1))
    m = re.search(rf"第一档电量可用\s*{_NUM}\s*千\s*瓦\s*时[，,]\s*还剩\s*{_NUM}\s*千\s*瓦\s*时", text)
    if m:
        bill["current_tier"] = "第一档"
        bill["tier_remaining"] = _f(m.group(2))

    # 非分时账单兜底：只有总电量与单一电费
    if not bill.get("peak_usage") and bill.get("usage") and bill.get("amount"):
        bill.setdefault("unit_price", round(bill["amount"] / bill["usage"], 4))

    # 档位明细（供 tier_detail 参考，帮助人工核对）
    if bill.get("current_tier") and bill.get("tier_remaining") is not None:
        bill["tier_detail"] = json.dumps(
            {bill["current_tier"]: {"剩余": bill["tier_remaining"]}},
            ensure_ascii=False)

    if note_bits:
        bill["note"] = "；".join(note_bits)
    return bill


# ---------------------------------------------------------------------------
# 燃气：上海燃气（阶梯 + 年度累计）
# ---------------------------------------------------------------------------

def _parse_gas(text):
    bill = {}

    # 账单年月：头部独立的「2026 10」或结算周期结束月
    bill["month"] = _month_from_yyyymm(text[:80]) or None
    m = re.search(r"结算周期[：:]\s*(20\d{2})年(\d{2})月\d{2}日\s*[-–—]\s*(20\d{2})年(\d{2})月(\d{2})日", text)
    if m and not bill["month"]:
        bill["month"] = f"{m.group(3)}-{m.group(4)}"

    # 阶梯行：第一阶梯 7 3.00 21.00（用量 单价 金额）
    m = re.search(rf"(第[一二三]阶梯)\s*{_NUM}\s*{_NUM}\s*{_NUM}", text)
    if m:
        bill["current_tier"] = m.group(1).replace("阶梯", "档")
        bill["usage"] = _f(m.group(2))
        bill["unit_price"] = _f(m.group(3))
        bill["amount"] = _f(m.group(4))

    # 年度累计：贵户用气年度累计气量已达217立方米。第一档可用气量310立方米，还剩余93立方米
    # （PDF 可能拆行：「310立\n方米」，单位词内允许 \s*）
    m = re.search(rf"年度累计气量已达\s*{_NUM}\s*立\s*方\s*米", text)
    if m:
        bill["year_usage"] = _f(m.group(1))
    m = re.search(rf"第[一二三]档可用气量\s*{_NUM}\s*立\s*方\s*米[，,]?\s*还剩余\s*{_NUM}\s*立\s*方\s*米", text)
    if m:
        bill["tier_remaining"] = _f(m.group(2))

    if bill.get("current_tier") and bill.get("tier_remaining") is not None:
        bill["tier_detail"] = json.dumps(
            {bill["current_tier"]: {"剩余": bill["tier_remaining"]}},
            ensure_ascii=False)
    return bill


# ---------------------------------------------------------------------------
# 供水：水费 + 污水费分项
# ---------------------------------------------------------------------------

def _parse_water(text):
    bill = {}
    m = re.search(rf"(?:本期(?:账单)?用量|售水量)\s*{_NUM}\s*吨", text)
    if m:
        bill["usage"] = _f(m.group(1))
    m = re.search(rf"上期(?:表)?读数\s*{_NUM}", text)
    if m:
        bill["prev_reading"] = _f(m.group(1))
    m = re.search(rf"本期(?:表)?读数\s*{_NUM}", text)
    if m:
        bill["cur_reading"] = _f(m.group(1))

    # 分项行：类型 单价 用量 金额（水费 / 污水费）
    water_fee = sewage_fee = None
    m = re.search(rf"(?<!污)水费\s*{_NUM}\s*{_NUM}\s*{_NUM}", text)
    if m:
        bill["water_unit_price"] = _f(m.group(1))
        water_fee = _f(m.group(3))
    m = re.search(rf"污水费\s*{_NUM}\s*{_NUM}\s*{_NUM}", text)
    if m:
        bill["sewage_unit_price"] = _f(m.group(1))
        sewage_fee = _f(m.group(3))
    if water_fee is not None or sewage_fee is not None:
        bill["water_fee"] = water_fee
        bill["sewage_fee"] = sewage_fee
        if water_fee is not None and sewage_fee is not None:
            bill["amount"] = round(water_fee + sewage_fee, 2)
    if not bill.get("amount"):
        m = re.search(rf"(?:应付|实付)?[费款][用额：:\s]*[¥￥]?\s*{_NUM}\s*元", text)
        if m:
            bill["amount"] = _f(m.group(1))
    return bill


# ---------------------------------------------------------------------------
# 图片：可选视觉模型识别（设置页配置的 OpenAI 兼容接口）
# ---------------------------------------------------------------------------

VISION_PROMPT = (
    "这是水电燃气账单。请只输出 JSON（不要其他文字），字段："
    'type("water"|"electric"|"gas")、month("YYYY-MM")、usage(数字)、amount(数字)、'
    "water_fee、sewage_fee、water_unit_price、sewage_unit_price、"
    "prev_reading、cur_reading、unit_price、"
    "peak_usage、peak_price、valley_usage、valley_price、"
    "peak_prev_reading、peak_cur_reading、valley_prev_reading、valley_cur_reading、"
    "current_tier、tier_remaining、year_usage、note。"
    "没有的字段用 null。金额必须满足：水 amount=water_fee+sewage_fee；"
    "电 amount=峰电量×峰价+谷电量×谷价；气 amount=usage×unit_price。"
)


def parse_image_via_model(path, api_base, api_key, model, mime="image/png"):
    """把图片发给 OpenAI 兼容视觉接口解析。成功返回字段 dict，失败返回 None"""
    try:
        import base64
        import urllib.request

        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        url = api_base.rstrip("/") + "/chat/completions"
        payload = {
            "model": model or "gpt-4o-mini",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            "temperature": 0,
        }
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + api_key})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
        content = data["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        out = json.loads(m.group())
        out.pop("type", None)  # 类型由外层判别，不信任模型
        return {k: v for k, v in out.items() if v not in (None, "", "null")}
    except Exception as e:
        print(f"[bill_parser] 视觉模型识别失败: {e}", flush=True)
        return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def parse_bill_file(path, filename=""):
    """解析账单文件，返回 draft dict（绝不抛异常）。

    返回：{parse_ok, bill_type, bill{add_bill 兼容字段}, confidence, message, raw_text}
    """
    suffix = (filename or path).rsplit(".", 1)[-1].lower() if "." in (filename or path) else ""
    draft = {"parse_ok": False, "bill_type": None, "bill": {},
             "confidence": "low", "message": "", "raw_text": ""}

    text = None
    if suffix == "pdf" or (path or "").lower().endswith(".pdf"):
        text = _pdf_text(path)
        if text is None:
            try:
                import pypdf  # noqa: F401
            except ImportError:
                draft["message"] = PYPDF_HINT
                return draft
            draft["message"] = "PDF 无法解析（可能为扫描件，无文本层）"
            return draft
        draft["raw_text"] = text[:4000]
    elif suffix in ("png", "jpg", "jpeg", "webp", "gif"):
        # 图片不在本地做 OCR；返回提示，auth_server 层会尝试视觉模型
        draft["message"] = "__IMAGE__"
        return draft
    else:
        draft["message"] = f"不支持的文件类型 .{suffix}（支持 pdf / png / jpg / webp）"
        return draft

    if not text or not text.strip():
        draft["message"] = "PDF 无文本层（可能为扫描件），暂不支持自动识别"
        return draft

    # 按文本特征判别费种
    if ("电费账单" in text or "国" in text and "电力公司" in text
            or "正向有功" in text or "千瓦时" in text):
        bill, parser = _parse_electric(text), _parse_electric
        btype = "electric"
    elif ("天然气" in text or "燃气" in text or "立方米" in text):
        bill, parser = _parse_gas(text), _parse_gas
        btype = "gas"
    elif ("水费" in text or "污水费" in text or "吨" in text):
        bill, parser = _parse_water(text), _parse_water
        btype = "water"
    else:
        draft["message"] = "未能识别账单类型（需要水/电/气账单）"
        draft["raw_text"] = text[:2000]
        return draft

    draft["bill_type"] = btype
    draft["bill"] = bill
    core = ("month" in bill and bill.get("usage") is not None
            and bill.get("amount") is not None)
    draft["parse_ok"] = bool(core)
    draft["confidence"] = "high" if core and (bill.get("peak_usage") or bill.get("water_fee")
                                              or bill.get("unit_price")) else (
        "medium" if core else "low")
    if not core:
        draft["message"] = ("已识别为%s账单，但关键字段不全，请补全后保存" %
                            {"water": "水费", "electric": "电费", "gas": "燃气"}[btype])
    else:
        draft["message"] = "识别成功，请核对后保存"
    return draft


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print("=" * 20, p)
        print(json.dumps(parse_bill_file(p), ensure_ascii=False, indent=2))

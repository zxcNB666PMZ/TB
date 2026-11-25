# -*- coding: utf-8 -*-
"""发票文本处理的纯函数（无副作用、无 IO，方便单元测试）"""

import re

# 常见地域前缀（归一化供应商名称时剥离）
REGION_PREFIXES = (
    "北京市", "上海市", "天津市", "重庆市",
    "北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "成都",
    "武汉", "南京", "西安", "苏州", "长沙", "郑州", "青岛", "中国",
)

# 常见企业后缀
COMPANY_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团", "公司",
)

_NULL_LIKE = {"", "-", "--", "null", "none", "nan", "n/a", "无"}


def clean_json_block(text):
    """去掉模型返回里的 ```json 围栏和首尾空白"""
    if not text:
        return ""
    cleaned = re.sub(r"```[a-zA-Z]*", "", str(text))
    cleaned = cleaned.replace("```", "")
    return cleaned.strip()


def parse_amount(value):
    """
    把各种写法的金额转成 float（保留 2 位）；无法识别返回 None。

    能处理："1,234.56"、"¥1234.56"、"1234.56元"、"￥ 88"、1234.56、None
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)

    text = str(value).strip()
    if text.lower() in _NULL_LIKE:
        return None

    text = (
        text.replace("¥", "")
        .replace("￥", "")
        .replace("元", "")
        .replace(",", "")
        .replace("，", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return round(float(match.group()), 2)


def normalize_supplier(name):
    """
    供应商名称归一化，用于判断"是不是同一家公司"。

    例：
      "北京滴滴出行科技有限公司" -> "滴滴出行科技"
      "滴滴出行科技有限公司"     -> "滴滴出行科技"
      （两者归一化后相同，可视为同一供应商）
    """
    if not name:
        return ""

    text = str(name).strip()
    # 全角/半角括号、空白统一
    text = (
        text.replace("（", "(")
        .replace("）", ")")
        .replace("　", "")
        .replace(" ", "")
        .replace("\u00a0", "")
    )
    if not text:
        return ""

    for suffix in COMPANY_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break

    for prefix in sorted(REGION_PREFIXES, key=len, reverse=True):
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix):]
            break

    return text


def same_supplier(a, b):
    """判断两个供应商名称是否指向同一家公司（归一化后比较）"""
    na, nb = normalize_supplier(a), normalize_supplier(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def clean_invoice_record(data):
    """
    规范化一条发票记录：
    - 金额转 float（识别不了返回 None）
    - 字符串字段去空白，空值转 None
    - 补齐字段名
    """
    fields = ["发票号码", "开票日期", "购买方名称", "销售方名称", "发票类型", "文件名"]
    record = {}
    for field in fields:
        value = data.get(field)
        text = str(value).strip() if value is not None else ""
        record[field] = text or None

    amount = parse_amount(data.get("价税合计"))
    record["价税合计"] = amount

    return record


def validate_invoice_record(record):
    """
    返回问题列表（空列表 = 通过）。
    规则：发票号码必填；金额必须 > 0；销售方/购买方至少有一个。
    """
    problems = []
    if not record.get("发票号码"):
        problems.append("缺少发票号码")
    amount = record.get("价税合计")
    if amount is None:
        problems.append("金额无法识别")
    elif amount <= 0:
        problems.append(f"金额异常（{amount}）")
    if not record.get("销售方名称") and not record.get("购买方名称"):
        problems.append("买卖双方名称都缺失")
    if not record.get("销售方名称"):
        problems.append("缺少销售方名称")
    return problems

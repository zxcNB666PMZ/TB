# -*- coding: utf-8 -*-
"""
生成并写入 200 条虚拟发票 + 120 条虚拟流水，用于功能测试。

特点：
- 发票号码以 FAKE 开头，方便随时一键清理（clean_fake_data.py）
- 故意混入"脏数据"：千分位金额、斜杠日期、多余空格、缺失销售方，
  用来验证数据清洗是否真的生效
- 用固定随机种子，结果可复现
"""

import random
import sys
from datetime import date, timedelta

import db

random.seed(20261125)

SUPPLIERS = [
    ["滴滴出行科技有限公司", "北京滴滴出行科技有限公司", "滴滴出行科技（北京）有限公司"],
    ["北京京东世纪贸易有限公司", "京东世纪贸易有限公司"],
    ["北京三快在线科技有限公司", "三快在线科技有限公司"],
    ["顺丰速运有限公司", "深圳顺丰速运有限公司"],
    ["中国移动通信集团有限公司", "中国移动通信集团北京有限公司"],
    ["国网北京市电力公司", "国家电网有限公司"],
    ["星巴克咖啡（北京）有限公司"],
    ["中国铁路北京局集团有限公司", "中国铁路12306"],
    ["上海携程商务有限公司", "携程旅行网"],
    ["阿里巴巴（中国）有限公司"],
    ["腾讯科技（深圳）有限公司"],
    ["北京字节跳动科技有限公司"],
    ["中国东方航空股份有限公司"],
    ["北京华联综合超市股份有限公司"],
    ["中国石油天然气股份有限公司"],
]

BUYER = "测试用科技有限公司"
TYPES = [
    "增值税电子普通发票",
    "增值税专用发票",
    "火车票",
    "航空运输电子客票行程单",
    "出租车票",
]

START = date(2026, 1, 1)


def build_records(count=200):
    records = []
    for i in range(count):
        number = f"FAKE{i:06d}"
        seller = random.choice(random.choice(SUPPLIERS))
        day = START + timedelta(days=random.randint(0, 320))
        amount = round(random.choice(
            [random.uniform(3.9, 99), random.uniform(100, 800), random.uniform(800, 5000)]
        ), 2)

        # ---- 故意注入脏数据（约 30%）----
        if i % 7 == 0:
            amount_value = f"¥{amount:,.2f}"        # 千分位 + 货币符号
        elif i % 13 == 0:
            amount_value = f"{amount}元"            # 带单位
        else:
            amount_value = amount

        if i % 11 == 0:
            date_value = day.strftime("%Y/%-m/%-d") if sys.platform != "win32" else day.strftime("%Y/%m/%d")
        elif i % 23 == 0:
            date_value = f"{day.year}年{day.month}月{day.day}日"
        else:
            date_value = day.isoformat()

        if i % 17 == 0:
            seller_value = seller.replace("有限公司", " 有限公司")   # 多余空格
        else:
            seller_value = seller

        if i % 19 == 0:
            seller_value = None                                     # 缺销售方

        records.append(
            {
                "发票号码": number,
                "开票日期": date_value,
                "购买方名称": BUYER,
                "销售方名称": seller_value,
                "价税合计": amount_value,
                "发票类型": random.choice(TYPES),
                "文件名": f"{number}.pdf",
            }
        )
    return records


def build_transactions(count=120):
    remarks = [
        ("午餐 公司食堂", 15, 40),
        ("晚餐 美团外卖", 20, 80),
        ("打车 滴滴出行", 8, 60),
        ("地铁公交充值", 20, 100),
        ("京东购物 办公用品", 50, 600),
        ("星巴克咖啡", 25, 60),
        ("高铁票 北京南-天津", 55, 200),
        ("酒店住宿 如家", 200, 600),
        ("话费充值 中国移动", 50, 200),
        ("电费 国网", 80, 400),
        ("顺丰快递", 12, 60),
        ("超市采购 华联", 60, 300),
    ]
    rows = []
    for i in range(count):
        note, low, high = random.choice(remarks)
        rows.append(
            {
                "交易备注": f"虚拟流水{note}",
                "金额": round(random.uniform(low, high), 2),
                "AI分类": None,
            }
        )
    return rows


def main():
    print("=== 1. 写入 200 条虚拟发票 ===")
    records = build_records(200)

    before = db.quality_summary()
    n = db.upsert_invoices(records)
    print(f"  第一次写入: {n} 条")

    # 再写一遍，验证幂等（发票号码相同应更新而不是重复插入）
    n2 = db.upsert_invoices(build_records(200))
    print(f"  重复写入:   {n2} 条（数字相同说明走的是更新）")

    print("\n=== 2. 写入 120 条虚拟流水 ===")
    tn = db.insert_transactions(build_transactions(120))
    print(f"  流水写入: {tn} 条")

    print("\n=== 3. 入库结果 ===")
    q = db.quality_summary()
    print(f"  发票总数: {q['total']} 张（写入前 {before['total']} 张）")
    print(f"  金额合计: {q['total_amount']} 元")
    print(f"  缺销售方: {q['no_seller']} 张 / {q['no_seller_amount']} 元")
    print(f"  金额异常: {q['bad_amount']} 张")

    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM transactions")
        print(f"  流水总数: {cur.fetchone()[0]} 条")
        cur.execute(
            """SELECT count(*) FROM invoices
               WHERE "发票号码" LIKE 'FAKE%%' AND "开票日期" IS NULL"""
        )
        print(f"  虚拟发票日期解析失败: {cur.fetchone()[0]} 张（应为 0）")
        cur.execute(
            """SELECT count(*) FROM invoices
               WHERE "发票号码" LIKE 'FAKE%%' AND "价税合计" IS NULL"""
        )
        print(f"  虚拟发票金额解析失败: {cur.fetchone()[0]} 张（应为 0）")


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
"""一键清除虚拟测试数据（发票号码以 FAKE 开头 + 备注含"虚拟流水"）"""

import db


def main():
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM invoices WHERE \"发票号码\" LIKE 'FAKE%%'")
        inv = cur.rowcount
        cur.execute("DELETE FROM transactions WHERE \"交易备注\" LIKE '虚拟流水%%'")
        tx = cur.rowcount

    q = db.quality_summary()
    print(f"已删除虚拟发票 {inv} 张，虚拟流水 {tx} 条")
    print(f"剩余发票 {q['total']} 张 / {q['total_amount']} 元")


if __name__ == "__main__":
    main()
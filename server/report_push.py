# -*- coding: utf-8 -*-
"""
定时汇总报表：由 systemd timer 调用，把发票台账汇总推到飞书。

用法：
    python report_push.py            # 日报
    python report_push.py --weekly   # 周报
"""

import sys
from datetime import date, timedelta

import push


def weekly_title():
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return f"📊 财务台账周报 · {monday.isoformat()} ~ {today.isoformat()}"


def main():
    weekly = "--weekly" in sys.argv
    title = weekly_title() if weekly else None
    ok, msg = push.send_summary(title)
    print(("✅ " if ok else "❌ ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
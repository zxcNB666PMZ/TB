# -*- coding: utf-8 -*-
"""供应商别名匹配 + 数据质量统计测试"""

import db


def _make(number, seller, amount=10.0, buyer="测试科技有限公司"):
    return {
        "发票号码": number,
        "开票日期": "2026-11-01",
        "购买方名称": buyer,
        "销售方名称": seller,
        "价税合计": amount,
        "发票类型": "增值税电子普通发票",
        "文件名": f"{number}.pdf",
    }


class TestSupplierAliasMatching:
    def test_different_spellings_all_matched(self, clean_invoices):
        """搜"滴滴"应同时命中三种不同写法的滴滴公司"""
        db.upsert_invoices(
            [
                _make("TEST1001", "北京滴滴出行科技有限公司", 10.0),
                _make("TEST1002", "滴滴出行科技有限公司", 20.0),
                _make("TEST1003", "北京易行出行旅游有限公司", 5.0),
            ]
        )
        rows, _ = db.query_invoices("滴滴出行科技")
        sellers = {r["销售方名称"] for r in rows if str(r.get("销售方名称") or "").find("滴滴") >= 0}
        assert "北京滴滴出行科技有限公司" in sellers
        assert "滴滴出行科技有限公司" in sellers

    def test_query_with_region_prefix(self, clean_invoices):
        """用带地域前缀的名称查，也能命中不带前缀的"""
        db.upsert_invoices([_make("TEST1001", "滴滴出行科技有限公司", 10.0)])
        rows, _ = db.query_invoices("北京滴滴出行科技有限公司")
        assert any(r["销售方名称"] == "滴滴出行科技有限公司" for r in rows)

    def test_no_duplicate_rows(self, clean_invoices):
        db.upsert_invoices(
            [
                _make("TEST1001", "北京滴滴出行科技有限公司", 10.0),
                _make("TEST1002", "滴滴出行科技有限公司", 20.0),
            ]
        )
        rows, _ = db.query_invoices("滴滴")
        keys = [(r.get("销售方名称"), str(r.get("价税合计"))) for r in rows]
        assert len(keys) == len(set(keys)), "查询结果不应有重复行"

    def test_no_match_still_empty(self, clean_invoices):
        db.upsert_invoices([_make("TEST1001", "滴滴出行科技有限公司")])
        rows, _ = db.query_invoices("完全无关的公司XYZ")
        assert rows == []


class TestUpsertSkipsInvalid:
    def test_record_without_number_skipped(self, clean_invoices):
        n = db.upsert_invoices(
            [
                _make("TEST2001", "滴滴出行科技有限公司"),
                {"发票号码": None, "销售方名称": "无号码公司", "价税合计": 99},
                {"发票号码": "   ", "销售方名称": "空号码公司", "价税合计": 88},
            ]
        )
        assert n == 1
        numbers = {r["发票号码"] for r in db.all_invoices() if str(r["发票号码"]).startswith("TEST")}
        assert numbers == {"TEST2001"}

    def test_amount_with_thousands_separator(self, clean_invoices):
        n = db.upsert_invoices(
            [
                {
                    "发票号码": "TEST2002",
                    "开票日期": "2026/11/02",
                    "购买方名称": "测试科技有限公司",
                    "销售方名称": "滴滴出行科技有限公司",
                    "价税合计": "¥1,234.56",
                }
            ]
        )
        assert n == 1
        row = [r for r in db.all_invoices() if r["发票号码"] == "TEST2002"][0]
        assert float(row["价税合计"]) == 1234.56
        assert str(row["开票日期"]) == "2026-11-02"


class TestQualitySummary:
    def test_counts_missing_seller(self, clean_invoices):
        db.upsert_invoices(
            [
                _make("TEST3001", "滴滴出行科技有限公司", 10.0),
                _make("TEST3002", None, 90.0),
            ]
        )
        q = db.quality_summary()
        assert q["total"] >= 2
        assert q["no_seller"] >= 1
        assert float(q["no_seller_amount"]) >= 90.0

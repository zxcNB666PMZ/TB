# -*- coding: utf-8 -*-
"""发票读写测试（跑在独立测试库 finance_test 上）"""

import db


def _make(number, seller="滴滴出行科技有限公司", amount=100.0, buyer="测试科技有限公司"):
    return {
        "发票号码": number,
        "开票日期": "2026-11-01",
        "购买方名称": buyer,
        "销售方名称": seller,
        "价税合计": amount,
        "发票类型": "增值税电子普通发票",
        "文件名": f"{number}.pdf",
    }


class TestUpsertInvoices:
    def test_insert_new(self, clean_invoices):
        n = db.upsert_invoices([_make("TEST0001"), _make("TEST0002", amount=50.5)])
        assert n == 2
        rows = db.all_invoices()
        assert len([r for r in rows if str(r["发票号码"]).startswith("TEST")]) == 2

    def test_duplicate_number_is_idempotent(self, clean_invoices):
        db.upsert_invoices([_make("TEST0001", amount=100.0)])
        db.upsert_invoices([_make("TEST0001", amount=100.0)])
        rows = [r for r in db.all_invoices() if r["发票号码"] == "TEST0001"]
        assert len(rows) == 1

    def test_duplicate_updates_amount(self, clean_invoices):
        db.upsert_invoices([_make("TEST0001", amount=100.0)])
        db.upsert_invoices([_make("TEST0001", amount=250.75)])
        rows = [r for r in db.all_invoices() if r["发票号码"] == "TEST0001"]
        assert len(rows) == 1
        assert float(rows[0]["价税合计"]) == 250.75

    def test_batch_mixed_new_and_existing(self, clean_invoices):
        db.upsert_invoices([_make("TEST0001")])
        n = db.upsert_invoices([_make("TEST0001"), _make("TEST0003")])
        assert n == 2
        numbers = {r["发票号码"] for r in db.all_invoices() if str(r["发票号码"]).startswith("TEST")}
        assert numbers == {"TEST0001", "TEST0003"}

    def test_empty_list(self, clean_invoices):
        assert db.upsert_invoices([]) == 0


class TestQueryInvoices:
    def test_query_by_seller(self, clean_invoices):
        db.upsert_invoices([_make("TEST0001", seller="北京滴滴出行科技有限公司", amount=10.0)])
        rows, samples = db.query_invoices("滴滴")
        assert len([r for r in rows if str(r["销售方名称"]).startswith("北京滴滴")]) >= 1
        assert samples is not None

    def test_query_no_match(self, clean_invoices):
        rows, _ = db.query_invoices("完全不存在的公司名XYZ")
        assert rows == []

    def test_query_escapes_like_wildcards(self, clean_invoices):
        db.upsert_invoices([_make("TEST0001"), _make("TEST0002")])
        rows, _ = db.query_invoices("%")
        assert rows == []


class TestTransactions:
    def test_insert_transactions(self, clean_invoices):
        n = db.insert_transactions(
            [
                {"交易备注": "午餐 美团", "金额": 35.5, "AI分类": "餐饮"},
                {"交易备注": "打车 滴滴", "金额": 12.0, "AI分类": "交通"},
            ]
        )
        assert n == 2
        with db.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM transactions WHERE \"交易备注\" LIKE '%美团%'")
            assert cur.fetchone()[0] >= 1
            cur.execute("DELETE FROM transactions WHERE \"交易备注\" LIKE '%美团%' OR \"交易备注\" LIKE '%打车 滴滴%'")

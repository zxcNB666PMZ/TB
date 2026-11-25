# -*- coding: utf-8 -*-
"""发票文本处理纯函数测试（不碰数据库）"""

import invoice_parser as ip


class TestParseAmount:
    def test_plain_number(self):
        assert ip.parse_amount(1234.56) == 1234.56
        assert ip.parse_amount(100) == 100.0

    def test_string_forms(self):
        assert ip.parse_amount("1234.56") == 1234.56
        assert ip.parse_amount("¥1,234.56") == 1234.56
        assert ip.parse_amount("￥ 88") == 88.0
        assert ip.parse_amount("1234.56元") == 1234.56
        assert ip.parse_amount("1，234.56") == 1234.56

    def test_invalid(self):
        for value in [None, "", "-", "null", "abc", "无"]:
            assert ip.parse_amount(value) is None

    def test_rounding(self):
        assert ip.parse_amount("1.005") == 1.0
        assert ip.parse_amount("99.999") == 100.0


class TestCleanJsonBlock:
    def test_strip_fence(self):
        assert ip.clean_json_block('```json\n{"a":1}\n```') == '{"a":1}'
        assert ip.clean_json_block("```\n{}\n```") == "{}"

    def test_plain_passthrough(self):
        assert ip.clean_json_block(' {"a": 1} ') == '{"a": 1}'
        assert ip.clean_json_block(None) == ""


class TestNormalizeSupplier:
    def test_region_and_suffix_removed(self):
        assert ip.normalize_supplier("北京滴滴出行科技有限公司") == "滴滴出行科技"
        assert ip.normalize_supplier("滴滴出行科技有限公司") == "滴滴出行科技"

    def test_same_supplier_detection(self):
        assert ip.same_supplier("北京滴滴出行科技有限公司", "滴滴出行科技有限公司")
        assert ip.same_supplier("北京滴滴出行科技有限公司", " 滴滴出行科技 ")

    def test_different_supplier(self):
        assert not ip.same_supplier("北京滴滴出行科技有限公司", "北京易行出行旅游有限公司")

    def test_empty(self):
        assert ip.normalize_supplier("") == ""
        assert ip.normalize_supplier(None) == ""
        assert not ip.same_supplier("", "滴滴")


class TestCleanInvoiceRecord:
    def test_amount_and_blank_normalized(self):
        record = ip.clean_invoice_record(
            {
                "发票号码": " TEST1 ",
                "开票日期": "2026-11-01",
                "购买方名称": "  ",
                "销售方名称": "滴滴出行科技有限公司",
                "价税合计": "¥ 88.80",
            }
        )
        assert record["发票号码"] == "TEST1"
        assert record["购买方名称"] is None
        assert record["价税合计"] == 88.8

    def test_missing_keys(self):
        record = ip.clean_invoice_record({})
        assert record["发票号码"] is None
        assert record["价税合计"] is None


class TestValidateInvoiceRecord:
    def test_valid_record(self):
        record = ip.clean_invoice_record(
            {
                "发票号码": "TEST1",
                "销售方名称": "滴滴出行科技有限公司",
                "价税合计": 100,
            }
        )
        assert ip.validate_invoice_record(record) == []

    def test_missing_number_and_amount(self):
        problems = ip.validate_invoice_record({"价税合计": None, "销售方名称": None})
        assert "缺少发票号码" in problems
        assert "金额无法识别" in problems
        assert any("销售方" in p for p in problems)

    def test_zero_amount(self):
        problems = ip.validate_invoice_record(
            {"发票号码": "TEST1", "价税合计": 0, "销售方名称": "x"}
        )
        assert any("金额异常" in p for p in problems)

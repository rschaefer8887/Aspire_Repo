"""HD Fowler inbound freight allocation into material unit costs."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_costs import LineOutput, apply_tax, line_total_cost  # noqa: E402
from idp_excel import extraction_to_lines  # noqa: E402
from idp_fowler_freight import (  # noqa: E402
    allocate_fowler_freight_per_unit,
    is_fowler_inbound_freight_line,
    taxed_freight_extended,
)
from idp_match_log import append_hd_fowler_match_log_from_extraction  # noqa: E402
from idp_openai import ExtractionResult, LineMatch  # noqa: E402
from idp_openai import collect_review_flags  # noqa: E402
from idp_vendor_profiles import HD_FOWLER_PROFILE  # noqa: E402

_FREIGHT_DESC = "INBOUND FRT / BILLABLE"


class TestFowlerFreightDetector(unittest.TestCase):
    def test_inbound_frt_billable(self) -> None:
        self.assertTrue(is_fowler_inbound_freight_line(_FREIGHT_DESC))
        self.assertTrue(is_fowler_inbound_freight_line("INBOUND FRT/BILLABLE"))

    def test_material_not_freight(self) -> None:
        self.assertFalse(is_fowler_inbound_freight_line('1" PVC INSERT TEE'))


class TestFowlerFreightAllocation(unittest.TestCase):
    def test_twenty_dollars_freight_twenty_units(self) -> None:
        """$20 pre-tax freight, 6% tax, 20 material units → +$1.06/unit."""
        material = [
            LineOutput("A", "Item A", 10, apply_tax(5.0, profile=HD_FOWLER_PROFILE)),
            LineOutput("B", "Item B", 10, apply_tax(3.0, profile=HD_FOWLER_PROFILE)),
        ]
        freight_taxed = taxed_freight_extended(1, 20.0, profile=HD_FOWLER_PROFILE)
        self.assertAlmostEqual(freight_taxed, 21.20, places=2)

        alloc = allocate_fowler_freight_per_unit(
            material, [(1.0, 20.0)], profile=HD_FOWLER_PROFILE
        )
        self.assertIsNotNone(alloc)
        assert alloc is not None
        self.assertAlmostEqual(alloc.freight_per_unit, 1.06, places=3)
        self.assertAlmostEqual(material[0].unit_cost, 6.36, places=3)
        self.assertAlmostEqual(material[1].unit_cost, 4.24, places=3)

    def test_multiple_freight_lines_summed(self) -> None:
        material = [LineOutput("A", "Item A", 4, 1.0)]
        allocate_fowler_freight_per_unit(
            material,
            [(1.0, 10.0), (1.0, 5.0)],
            profile=HD_FOWLER_PROFILE,
        )
        expected_per_unit = round(
            (
                taxed_freight_extended(1, 10.0, profile=HD_FOWLER_PROFILE)
                + taxed_freight_extended(1, 5.0, profile=HD_FOWLER_PROFILE)
            )
            / 4,
            3,
        )
        self.assertAlmostEqual(material[0].unit_cost, 1.0 + expected_per_unit, places=3)

    def test_freight_only_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            allocate_fowler_freight_per_unit([], [(1.0, 20.0)], profile=HD_FOWLER_PROFILE)
        self.assertIn("no material lines", str(ctx.exception))


class TestFowlerFreightExtraction(unittest.TestCase):
    def test_extraction_to_lines_omits_freight_row(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2026, 6, 4),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="I7000000",
            invoice_total=100.0,
            lines=[
                LineMatch(
                    description_raw='1" PVC INSERT TEE',
                    quantity=10,
                    unit_price=5.0,
                    item_code="TEE1",
                    item_name='1" PVC Insert Tee',
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw=_FREIGHT_DESC,
                    quantity=1,
                    unit_price=20.0,
                    confidence=0.99,
                ),
            ],
        )
        lines = extraction_to_lines(result, profile=HD_FOWLER_PROFILE)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].item_code, "TEE1")
        # 5.00 pre-tax → 5.30 after tax; + 21.20 freight / 10 units = +2.12
        self.assertAlmostEqual(lines[0].unit_cost, 7.42, places=3)

    def test_freight_skipped_in_review_flags(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2026, 6, 4),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="I7000000",
            invoice_total=100.0,
            lines=[
                LineMatch(
                    description_raw='1" PVC INSERT TEE',
                    quantity=10,
                    unit_price=5.0,
                    item_code="TEE1",
                    item_name='1" PVC Insert Tee',
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw=_FREIGHT_DESC,
                    quantity=1,
                    unit_price=20.0,
                    confidence=0.0,
                ),
            ],
        )
        flags = collect_review_flags(result)
        self.assertFalse(any(_FREIGHT_DESC in f for f in flags))

    def test_freight_skipped_in_match_log(self) -> None:
        import idp_match_log as ml
        from unittest.mock import patch

        result = ExtractionResult(
            invoice_date=date(2026, 6, 4),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="I7000000",
            lines=[
                LineMatch(
                    description_raw="TEE",
                    quantity=1,
                    unit_price=1.0,
                    item_code="TEE1",
                    item_name="Tee",
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw=_FREIGHT_DESC,
                    quantity=1,
                    unit_price=20.0,
                    confidence=0.99,
                ),
            ],
        )
        appended: list[list[list[str]]] = []

        def fake_append(_path, values, *, sheet_name: str) -> None:
            appended.append(values)

        with patch.object(ml, "_append_values_with_xlwings", side_effect=fake_append):
            n = append_hd_fowler_match_log_from_extraction(result, pdf_name="t.pdf")
        self.assertEqual(n, 1)
        self.assertEqual(len(appended[0]), 1)


if __name__ == "__main__":
    unittest.main()

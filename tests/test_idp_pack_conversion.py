"""Unit tests for canister → each quantity conversion."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_costs import apply_tax, line_total_cost  # noqa: E402
from idp_excel import extraction_to_lines  # noqa: E402
from idp_openai import ExtractionResult, LineMatch  # noqa: E402
from idp_pack_conversion import (  # noqa: E402
    maybe_convert_box_line,
    maybe_convert_canister_line,
    units_per_box_from_description,
    units_per_canister_from_description,
)
from idp_vendor_profiles import HD_FOWLER_PROFILE  # noqa: E402

_KING_INVOICE_DESC = (
    "BLUE KING CONNECTOR MIN#22/MAX#12 100 PER CANISTER "
    "#10241 KING INNOVATION"
)

_JUTE_BOX_INVOICE_DESC = (
    '6" Staples 11 GA Jute Matting Sold by the Box (1000 per box)'
)


class TestCanisterConversion(unittest.TestCase):
    def test_parse_units_per_canister_from_description(self) -> None:
        self.assertEqual(
            units_per_canister_from_description(_KING_INVOICE_DESC),
            100,
        )

    def test_exact_invoice_line_two_canisters(self) -> None:
        qty, price, note = maybe_convert_canister_line(
            2,
            45.0,
            description_raw=_KING_INVOICE_DESC,
            item_code=None,
        )
        self.assertEqual(qty, 200)
        self.assertAlmostEqual(price, 0.45)
        self.assertIn("canister→ea", note or "")
        self.assertAlmostEqual(qty * price, 90.0)

    def test_matches_by_item_code_only(self) -> None:
        qty, price, note = maybe_convert_canister_line(
            1,
            30.0,
            description_raw="KING CONNECTOR",
            item_code="10241",
        )
        self.assertEqual(qty, 100)
        self.assertAlmostEqual(price, 0.3)
        self.assertIn("catalog", note or "")

    def test_unrelated_line_not_converted(self) -> None:
        qty, price, note = maybe_convert_canister_line(
            2,
            10.0,
            description_raw="PVC INSERT TEE 1 INCH",
            item_code=None,
        )
        self.assertEqual(qty, 2)
        self.assertEqual(price, 10.0)
        self.assertIsNone(note)

    def test_extraction_to_lines_preserves_extended_with_tax(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2025, 1, 1),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            lines=[
                LineMatch(
                    description_raw=_KING_INVOICE_DESC,
                    quantity=2,
                    unit_price=45.0,
                    uom_raw="EA",
                    item_code="10241",
                    item_name="King Blue Connector",
                    confidence=1.0,
                )
            ],
        )
        lines = extraction_to_lines(result, profile=HD_FOWLER_PROFILE)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].quantity, 200)
        expected_unit = apply_tax(0.45, profile=HD_FOWLER_PROFILE)
        self.assertEqual(lines[0].unit_cost, expected_unit)
        self.assertAlmostEqual(
            line_total_cost(lines[0].quantity, lines[0].unit_cost),
            round(2 * apply_tax(45.0, profile=HD_FOWLER_PROFILE), 2),
        )


class TestBoxConversion(unittest.TestCase):
    def test_parse_units_per_box_from_description(self) -> None:
        self.assertEqual(
            units_per_box_from_description(_JUTE_BOX_INVOICE_DESC),
            1000,
        )

    def test_exact_jute_matting_invoice_two_boxes(self) -> None:
        qty, price, note = maybe_convert_box_line(
            2,
            50.0,
            description_raw=_JUTE_BOX_INVOICE_DESC,
            item_code=None,
        )
        self.assertEqual(qty, 2000)
        self.assertAlmostEqual(price, 0.05)
        self.assertIn("box→ea", note or "")
        self.assertAlmostEqual(qty * price, 100.0)

    def test_jute_box_by_catalog_name(self) -> None:
        qty, price, note = maybe_convert_box_line(
            1,
            80.0,
            description_raw="JUTE MATTING BOX",
            item_name="Irrigation Staples",
        )
        self.assertEqual(qty, 1000)
        self.assertAlmostEqual(price, 0.08)
        self.assertIsNotNone(note)

    def test_unrelated_line_not_converted(self) -> None:
        qty, price, note = maybe_convert_box_line(
            2,
            10.0,
            description_raw='1" PVC INSERT TEE',
            item_code=None,
        )
        self.assertEqual(qty, 2)
        self.assertEqual(price, 10.0)
        self.assertIsNone(note)

    def test_extraction_to_lines_preserves_extended_with_tax(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2025, 1, 1),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            lines=[
                LineMatch(
                    description_raw=_JUTE_BOX_INVOICE_DESC,
                    quantity=2,
                    unit_price=50.0,
                    uom_raw="BX",
                    item_code="",
                    item_name="Irrigation Staples",
                    confidence=1.0,
                )
            ],
        )
        lines = extraction_to_lines(result, profile=HD_FOWLER_PROFILE)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].quantity, 2000)
        expected_unit = apply_tax(0.05, profile=HD_FOWLER_PROFILE)
        self.assertEqual(lines[0].unit_cost, expected_unit)
        self.assertAlmostEqual(
            line_total_cost(lines[0].quantity, lines[0].unit_cost),
            round(2 * apply_tax(50.0, profile=HD_FOWLER_PROFILE), 2),
        )


if __name__ == "__main__":
    unittest.main()

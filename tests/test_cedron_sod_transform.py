"""Cedron Sod extraction transform → single catalog line + split note."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_openai import ExtractionResult, LineMatch  # noqa: E402
from idp_reference import ReferenceData  # noqa: E402
from idp_sod import (  # noqa: E402
    SodSplitResult,
    is_sod_charge_line,
    transform_cedron_sod_extraction,
)

CEDRON_TOTAL = 5432.17
CEDRON_QTY = 3450


class TestCedronSodTransform(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        cls.refs.load()

    def test_charge_lines_include_tax_and_pallet(self) -> None:
        self.assertTrue(is_sod_charge_line("Pallet Charge"))
        self.assertTrue(is_sod_charge_line("Pallet Credit"))
        self.assertTrue(is_sod_charge_line("Sales Tax"))

    def test_collapses_charges_to_single_sod_line(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2026, 6, 23),
            vendor_raw="Cedron Sod",
            vendor_name="Cedron Sod",
            vendor_id=999,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="1314-INV",
            invoice_total=CEDRON_TOTAL,
            lines=[
                LineMatch(
                    description_raw="3450 Kentucky Bluegrass",
                    quantity=CEDRON_QTY,
                    unit_price=1.45,
                    uom_raw="SF",
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw="Pallet Charge",
                    quantity=1,
                    unit_price=50.0,
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw="Pallet Credit",
                    quantity=1,
                    unit_price=-25.0,
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw="Sales Tax",
                    quantity=1,
                    unit_price=32.17,
                    confidence=0.95,
                ),
            ],
        )
        out = transform_cedron_sod_extraction(result, self.refs)
        self.assertEqual(len(out.lines), 1)
        ln = out.lines[0]
        self.assertIn("Bluegrass", ln.item_name or "")
        self.assertEqual(ln.item_code, "BSOD")
        self.assertAlmostEqual(ln.quantity, CEDRON_QTY, places=0)
        self.assertAlmostEqual(ln.unit_price, round(CEDRON_TOTAL / CEDRON_QTY, 3), places=3)
        self.assertIsInstance(out.sod_split, SodSplitResult)

    def test_multiple_grass_types_left_unchanged(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2026, 6, 23),
            vendor_raw="Cedron Sod",
            vendor_name="Cedron Sod",
            vendor_id=999,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="MULTI-INV",
            invoice_total=5000.0,
            lines=[
                LineMatch(
                    description_raw="2000 Kentucky Bluegrass",
                    quantity=2000,
                    unit_price=1.0,
                    uom_raw="SF",
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw="1500 RTF",
                    quantity=1500,
                    unit_price=1.2,
                    uom_raw="SF",
                    confidence=0.95,
                ),
            ],
        )
        out = transform_cedron_sod_extraction(result, self.refs)
        self.assertEqual(len(out.lines), 2)


if __name__ == "__main__":
    unittest.main()

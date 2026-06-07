"""Idaho Sod extraction transform → single catalog line + split note."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_openai import ExtractionResult, LineMatch  # noqa: E402
from idp_reference import ReferenceData  # noqa: E402
from idp_sod import SodSplitResult, transform_idaho_sod_extraction  # noqa: E402


class TestIdahoSodTransform(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        cls.refs.load()

    def test_collapses_charges_to_single_sod_line(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2026, 5, 1),
            vendor_raw="Idaho Sod",
            vendor_name="Idaho Sod",
            vendor_id=136,
            vendor_confidence=0.99,
            vendor_rationale="",
            invoice_number_raw="35JNVB",
            invoice_total=5432.17,
            lines=[
                LineMatch(
                    description_raw="3450 Kentucky Bluegrass",
                    quantity=3450,
                    unit_price=1.45,
                    uom_raw="SF",
                    confidence=0.95,
                ),
                LineMatch(
                    description_raw="Delivery Charge",
                    quantity=1,
                    unit_price=150.0,
                    confidence=0.95,
                ),
            ],
        )
        out = transform_idaho_sod_extraction(result, self.refs)
        self.assertEqual(len(out.lines), 1)
        ln = out.lines[0]
        self.assertIn("Bluegrass", ln.item_name or "")
        self.assertEqual(ln.item_code, "BSOD")
        self.assertAlmostEqual(ln.quantity, 3450, places=0)
        self.assertIsInstance(out.sod_split, SodSplitResult)


if __name__ == "__main__":
    unittest.main()

"""HD Fowler invoice line match log (CSV)."""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_match_log import (  # noqa: E402
    FIELDNAMES,
    append_hd_fowler_match_log_from_extraction,
    invoice_numbers_in_log,
    pdf_name_is_hd_fowler,
    should_log_hd_fowler,
)
from idp_openai import ExtractionResult, LineMatch  # noqa: E402


class TestMatchLogHelpers(unittest.TestCase):
    def test_should_log_fowler_only(self) -> None:
        self.assertTrue(should_log_hd_fowler("H.D. Fowler Company {Turf}", None))
        self.assertFalse(should_log_hd_fowler("Idaho Sod", None))

    def test_pdf_name_is_hd_fowler(self) -> None:
        self.assertTrue(
            pdf_name_is_hd_fowler(Path("Aspire-HD Fowler-I7331698-INV__06042026.pdf"))
        )
        self.assertFalse(
            pdf_name_is_hd_fowler(Path("Aspire-Idaho Sod-35JNVB.pdf"))
        )


class TestMatchLogAppend(unittest.TestCase):
    def test_append_fowler_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "HD Fowler Item Match Log.csv"
            import idp_match_log as ml

            original = ml.hd_fowler_match_log_path
            ml.hd_fowler_match_log_path = lambda: log_path  # type: ignore[method-assign]
            try:
                result = ExtractionResult(
                    invoice_date=date(2026, 6, 4),
                    vendor_raw="H.D. Fowler",
                    vendor_name="H.D. Fowler Company {Turf}",
                    vendor_id=1,
                    vendor_confidence=0.99,
                    vendor_rationale="",
                    invoice_number_raw="I7331698",
                    invoice_total=100.0,
                    lines=[
                        LineMatch(
                            description_raw='1" PVC INSERT TEE',
                            quantity=2,
                            unit_price=1.5,
                            uom_raw="EA",
                            item_code="TEE1",
                            item_name='1" PVC Insert Tee',
                            supplier_item_code="ABC123",
                            confidence=0.95,
                            rationale="One-off: test",
                        )
                    ],
                )
                n = append_hd_fowler_match_log_from_extraction(
                    result,
                    pdf_name="test.pdf",
                    source="auto",
                )
                self.assertEqual(n, 1)
                self.assertTrue(log_path.is_file())
                with log_path.open(encoding="utf-8") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["source"], "auto")
                self.assertEqual(rows[0]["invoice_number"], "I7331698-INV")
                self.assertEqual(rows[0]["supplier_item_code"], "ABC123")
                self.assertEqual(set(rows[0].keys()), set(FIELDNAMES))
                self.assertEqual(invoice_numbers_in_log(log_path), {"I7331698-INV"})
            finally:
                ml.hd_fowler_match_log_path = original  # type: ignore[method-assign]

    def test_skip_non_fowler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "HD Fowler Item Match Log.csv"
            import idp_match_log as ml

            original = ml.hd_fowler_match_log_path
            ml.hd_fowler_match_log_path = lambda: log_path  # type: ignore[method-assign]
            try:
                result = ExtractionResult(
                    invoice_date=None,
                    vendor_raw="Idaho Sod",
                    vendor_name="Idaho Sod",
                    vendor_id=1,
                    vendor_confidence=0.99,
                    vendor_rationale="",
                    invoice_number_raw="35JNVB",
                    lines=[
                        LineMatch(
                            description_raw="Sod",
                            quantity=1,
                            unit_price=1.0,
                        )
                    ],
                )
                n = append_hd_fowler_match_log_from_extraction(
                    result, pdf_name="sod.pdf", source="auto"
                )
                self.assertEqual(n, 0)
                self.assertFalse(log_path.exists())
            finally:
                ml.hd_fowler_match_log_path = original  # type: ignore[method-assign]


if __name__ == "__main__":
    unittest.main()

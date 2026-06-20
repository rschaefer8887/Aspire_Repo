"""Tests for extraction audit JSON (OpenAI + match troubleshooting)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_extraction_json import (  # noqa: E402
    build_extraction_audit,
    save_extraction_json,
)
from idp_openai import ExtractionResult, LineMatch  # noqa: E402


class TestExtractionJson(unittest.TestCase):
    def test_build_audit_includes_openai_raw_and_aspire_lines(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2025, 6, 1),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=0.95,
            vendor_rationale="",
            invoice_number_raw="12345",
            invoice_total=100.0,
            lines=[
                LineMatch(
                    description_raw='1" PVC INSERT COUPLING IXI',
                    quantity=2,
                    unit_price=10.0,
                    uom_raw="EA",
                    supplier_item_code="ABC",
                    item_code="X1",
                    item_name='PVC Insert Coupling - 1"',
                    confidence=0.92,
                    rationale="Exact catalog name from description",
                )
            ],
            openai_raw={
                "lines": [
                    {
                        "description_raw": '1" PVC INSERT COUPLING IXI',
                        "quantity": 2,
                        "unit_price": 10.0,
                        "uom_raw": "EA",
                        "supplier_item_code": "ABC",
                    }
                ]
            },
            openai_model="gpt-4o",
        )
        audit = build_extraction_audit(
            result,
            pdf_name="test.pdf",
            openai_model="gpt-4o",
            flags=[],
        )
        self.assertEqual(audit["openai_model"], "gpt-4o")
        self.assertEqual(audit["pdf_name"], "test.pdf")
        self.assertIsNotNone(audit["openai_raw"])
        self.assertEqual(len(audit["lines"]), 1)
        self.assertEqual(audit["lines"][0]["supplier_item_code"], "ABC")
        self.assertEqual(len(audit["aspire_import_lines"]), 1)
        self.assertEqual(audit["aspire_import_lines"][0]["quantity"], 2)

    def test_save_writes_valid_json(self) -> None:
        result = ExtractionResult(
            invoice_date=None,
            vendor_raw="Test Vendor",
            vendor_name="Test Vendor",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="999",
            lines=[],
            openai_raw={"lines": []},
            openai_model="gpt-4.1-mini",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            path = save_extraction_json(
                result,
                pdf_name="inv.pdf",
                openai_model="gpt-4.1-mini",
                flags=["LOW CONFIDENCE LINE"],
                output_dir=out_dir,
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["review_flags"], ["LOW CONFIDENCE LINE"])
            self.assertEqual(data["openai_model"], "gpt-4.1-mini")


if __name__ == "__main__":
    unittest.main()

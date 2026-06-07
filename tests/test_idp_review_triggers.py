"""Tests for one-off Streamlit review triggers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_openai import (  # noqa: E402
    ExtractionResult,
    LineMatch,
    collect_review_flags,
)
from idp_review import extraction_to_session  # noqa: E402
from idp_review_triggers import is_pinch_clamp_tool_ct108_line  # noqa: E402


_CT108_DESC = "PINCH CLAMP TOOL CT108"


class TestPinchClampCt108ReviewTrigger(unittest.TestCase):
    def test_detector_matches_exact_invoice_text(self) -> None:
        self.assertTrue(is_pinch_clamp_tool_ct108_line(_CT108_DESC))
        self.assertTrue(
            is_pinch_clamp_tool_ct108_line("CT108 PINCH CLAMP TOOL RENTAL")
        )

    def test_detector_rejects_unrelated_lines(self) -> None:
        self.assertFalse(is_pinch_clamp_tool_ct108_line('1" PVC INSERT TEE'))
        self.assertFalse(is_pinch_clamp_tool_ct108_line("CT100 COUPLING"))

    def test_collect_review_flags_queues_invoice(self) -> None:
        result = ExtractionResult(
            invoice_date=None,
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            invoice_total=100.0,
            lines=[
                LineMatch(
                    description_raw=_CT108_DESC,
                    quantity=1,
                    unit_price=25.0,
                    item_code="CT108",
                    item_name="Some Tool",
                    confidence=0.99,
                ),
                LineMatch(
                    description_raw='1" PVC INSERT TEE',
                    quantity=1,
                    unit_price=5.0,
                    item_code="TEE1",
                    item_name='1" PVC Insert Tee',
                    confidence=0.99,
                ),
            ],
        )
        flags = collect_review_flags(result)
        self.assertTrue(any("PINCH CLAMP TOOL CT108" in flag for flag in flags))
        self.assertFalse(any("LOW CONFIDENCE LINE" in flag for flag in flags))

    def test_extraction_to_session_marks_line_needs_review(self) -> None:
        result = ExtractionResult(
            invoice_date=None,
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            invoice_total=100.0,
            lines=[
                LineMatch(
                    description_raw=_CT108_DESC,
                    quantity=1,
                    unit_price=25.0,
                    item_code="CT108",
                    item_name="Some Tool",
                    confidence=0.99,
                )
            ],
        )
        flags = collect_review_flags(result)
        session = extraction_to_session(
            result,
            Path("invoice.pdf"),
            flags=flags,
        )
        self.assertTrue(session.lines[0].needs_review)
        self.assertFalse(session.lines[0].excluded)


if __name__ == "__main__":
    unittest.main()

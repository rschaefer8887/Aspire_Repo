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
from idp_review_triggers import (  # noqa: E402
    is_pinch_clamp_tool_ct108_line,
    is_review_tool_line,
)


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


class TestReviewToolTriggers(unittest.TestCase):
    def test_detector_matches_rotortool_by_code(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code="ROTORTOOL",
                item_name="Rain Bird Universal Rotor Tool Green",
            )
        )

    def test_detector_matches_ss200_by_code(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code="SS200",
                item_name="Dawn SS200 Large PVC Cutter",
            )
        )

    def test_detector_matches_ct112_by_code(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code="CT112",
                item_name="PINCH CLAMP TOOL LARGE CT112",
            )
        )

    def test_detector_matches_ct112_in_description(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code=None,
                description_raw="PINCH CLAMP TOOL LARGE CT112",
            )
        )

    def test_detector_matches_nh7020_by_code(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code="7020",
                item_name="NO HUB TORQUE WRENCH #NH7020 CHRISTYS",
            )
        )

    def test_detector_matches_nh7020_in_description(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code=None,
                description_raw="NO HUB TORQUE WRENCH #NH7020 CHRISTYS",
            )
        )

    def test_detector_matches_rotortool_in_description(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code=None,
                description_raw="ROTORTOOL UNIVERSAL ROTOR TOOL GREEN RAIN BIRD",
            )
        )

    def test_detector_matches_six_in_one_screwdriver_without_catalog(self) -> None:
        self.assertTrue(
            is_review_tool_line(
                item_code=None,
                item_name=None,
                description_raw="6 IN 1 SCREWDRIVER",
            )
        )

    def test_detector_rejects_unrelated_lines(self) -> None:
        self.assertFalse(
            is_review_tool_line(
                item_code="TEE1",
                item_name='1" PVC Insert Tee',
                description_raw='1" PVC INSERT TEE',
            )
        )

    def test_collect_review_flags_queues_invoice_for_tool(self) -> None:
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
                    description_raw="ROTORTOOL UNIVERSAL ROTOR TOOL GREEN RAIN BIRD",
                    quantity=2.0,
                    unit_price=2.21,
                    item_code="ROTORTOOL",
                    item_name="Rain Bird Universal Rotor Tool Green",
                    confidence=0.98,
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
        self.assertTrue(any("TOOL row" in flag and "ROTORTOOL" in flag for flag in flags))
        self.assertFalse(any("LOW CONFIDENCE LINE" in flag for flag in flags))

    def test_collect_review_flags_queues_invoice_for_ct112(self) -> None:
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
                    description_raw="PINCH CLAMP TOOL LARGE CT112",
                    quantity=1.0,
                    unit_price=15.0,
                    item_code="CT112",
                    item_name="PINCH CLAMP TOOL LARGE CT112",
                    confidence=0.98,
                ),
            ],
        )
        flags = collect_review_flags(result)
        self.assertTrue(any("TOOL row" in flag and "CT112" in flag for flag in flags))

    def test_collect_review_flags_queues_invoice_for_nh7020(self) -> None:
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
                    description_raw="NO HUB TORQUE WRENCH #NH7020 CHRISTYS",
                    quantity=1.0,
                    unit_price=42.0,
                    item_code="7020",
                    item_name="NO HUB TORQUE WRENCH #NH7020 CHRISTYS",
                    confidence=0.98,
                ),
            ],
        )
        flags = collect_review_flags(result)
        self.assertTrue(any("TOOL row" in flag and "NH7020" in flag for flag in flags))

    def test_collect_review_flags_queues_screwdriver_without_catalog(self) -> None:
        result = ExtractionResult(
            invoice_date=None,
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            invoice_total=50.0,
            lines=[
                LineMatch(
                    description_raw="6 IN 1 SCREWDRIVER",
                    quantity=1.0,
                    unit_price=12.0,
                    item_code=None,
                    item_name=None,
                    confidence=0.0,
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
        self.assertTrue(
            any("TOOL row" in flag and "6 IN 1 Screwdriver" in flag for flag in flags)
        )

    def test_extraction_to_session_marks_only_tool_line(self) -> None:
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
                    description_raw="ROTORTOOL UNIVERSAL ROTOR TOOL GREEN RAIN BIRD",
                    quantity=2.0,
                    unit_price=2.21,
                    item_code="ROTORTOOL",
                    item_name="Rain Bird Universal Rotor Tool Green",
                    confidence=0.98,
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
        session = extraction_to_session(
            result,
            Path("invoice.pdf"),
            flags=flags,
        )
        self.assertTrue(session.lines[0].needs_review)
        self.assertFalse(session.lines[1].needs_review)

    def test_extraction_to_session_marks_ct112_line(self) -> None:
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
                    description_raw="PINCH CLAMP TOOL LARGE CT112",
                    quantity=1.0,
                    unit_price=15.0,
                    item_code="CT112",
                    item_name="PINCH CLAMP TOOL LARGE CT112",
                    confidence=0.98,
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

"""Tests for hyphenated fraction OCR prompt helpers and post-correction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_openai import (  # noqa: E402
    maybe_correct_hyphenated_fraction_size,
    pdf_render_scale,
    _hyphenated_fraction_present,
)
from idp_reference import InventoryRecord, ReferenceData  # noqa: E402


def _refs_plug_sizes() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", 'PVC Insert Plug - 1-1/2"', "", "Material"),
        InventoryRecord("", 'PVC Insert Plug - 1/2" (IxI)', "", "Material"),
        InventoryRecord("", 'PVC Insert Elbow (90) - 1/2" (IxI)', "", "Material"),
    ]
    return refs


class TestHyphenatedFractionHelpers(unittest.TestCase):
    def test_hyphenated_fraction_present(self) -> None:
        self.assertTrue(_hyphenated_fraction_present('1-1/2" PVC PLUG', "1-1/2"))
        self.assertTrue(_hyphenated_fraction_present('1 1/2" PVC PLUG', "1-1/2"))
        self.assertFalse(_hyphenated_fraction_present('1/2" PVC PLUG', "1-1/2"))

    def test_pdf_render_scale_default(self) -> None:
        self.assertGreaterEqual(pdf_render_scale(), 1.0)


class TestMaybeCorrectHyphenatedFraction(unittest.TestCase):
    def test_corrects_half_inch_plug_ocr_to_one_and_half(self) -> None:
        refs = _refs_plug_sizes()
        desc = '1/2" PVC INSERT PLUG I'
        fixed, note = maybe_correct_hyphenated_fraction_size(desc, refs)
        self.assertEqual(fixed, '1-1/2" PVC INSERT PLUG I')
        self.assertIn("1-1/2", note)
        rec, conf, _ = refs.match_line(fixed, None)
        self.assertIsNotNone(rec)
        self.assertIn("1-1/2", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.85)

    def test_leaves_correct_one_and_half_unchanged(self) -> None:
        refs = _refs_plug_sizes()
        desc = '1-1/2" PVC INSERT PLUG I'
        fixed, note = maybe_correct_hyphenated_fraction_size(desc, refs)
        self.assertEqual(fixed, desc)
        self.assertEqual(note, "")

    def test_keeps_true_half_inch_when_catalog_matches(self) -> None:
        refs = _refs_plug_sizes()
        desc = '1/2" PVC INSERT PLUG I'
        # Only 1/2 plug in catalog — do not invent 1-1/2
        refs.inventory = [InventoryRecord("", 'PVC Insert Plug - 1/2" (IxI)', "", "Material")]
        fixed, note = maybe_correct_hyphenated_fraction_size(desc, refs)
        self.assertEqual(fixed, desc)
        self.assertEqual(note, "")


if __name__ == "__main__":
    unittest.main()

"""One-off: Fowler 721 Blue Cement weld-on → ItemCode 721 (not P70 pipe dope)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_721_blue_cement_weld_on_invoice_line,
    _norm,
)

_INVOICE = '721 Blue Cement 1/2 Pint Weld On'
_OCR_DESC = 'Blue Cement 1/2 Pint Weld On'
_TARGET_CODE = "721"
_TARGET_NAME = '721 Blue Cement - 1/2 Pint (Weld On)'
_WRONG_CODE = "P70"
_WRONG_NAME = "Weld On - White Seal Plus (pipe dope)"


def _refs_fixture(*, alternate: str | None = None) -> ReferenceData:
    refs = ReferenceData()
    alt = alternate if alternate is not None else _INVOICE
    refs.inventory = [
        InventoryRecord(_TARGET_CODE, _TARGET_NAME, alt, "Material"),
        InventoryRecord(_WRONG_CODE, _WRONG_NAME, _WRONG_NAME, "Material"),
    ]
    refs._build_inventory_indexes()
    return refs


class Test721BlueCementHelpers(unittest.TestCase):
    def test_invoice_line_detector_full_description(self) -> None:
        self.assertTrue(is_721_blue_cement_weld_on_invoice_line(_INVOICE))

    def test_invoice_line_detector_ocr_without_721(self) -> None:
        self.assertTrue(is_721_blue_cement_weld_on_invoice_line(_OCR_DESC))

    def test_invoice_line_detector_supplier_721(self) -> None:
        self.assertTrue(
            is_721_blue_cement_weld_on_invoice_line(_OCR_DESC, "721")
        )

    def test_invoice_line_detector_false_for_white_seal(self) -> None:
        self.assertFalse(
            is_721_blue_cement_weld_on_invoice_line(
                "WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON"
            )
        )


class Test721BlueCementMatch(unittest.TestCase):
    def test_one_off_matches_721_not_p70(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, _TARGET_CODE)
        self.assertGreaterEqual(conf, 0.90)
        self.assertNotEqual(rec.item_code, _WRONG_CODE)

    def test_exact_alternate_match(self) -> None:
        refs = _refs_fixture(alternate=_INVOICE)
        rec, conf, note = refs.match_line(_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, _TARGET_CODE)
        self.assertIn("Exact catalog name", note)

    def test_ocr_description_without_721_and_supplier_p70(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_OCR_DESC, "P70")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, _TARGET_CODE)
        self.assertNotEqual(rec.item_code, _WRONG_CODE)
        self.assertIn("721 Blue Cement", note)

    def test_alternate_suffix_when_ocr_drops_leading_721(self) -> None:
        refs = _refs_fixture(alternate=_INVOICE)
        rec, _, note = refs.match_line(_OCR_DESC, "P70")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, _TARGET_CODE)
        self.assertIn("721 Blue Cement", note)

    def test_find_by_code_when_alternate_empty(self) -> None:
        refs = _refs_fixture(alternate="")
        rec, _, _ = refs.match_line(_OCR_DESC, "P70")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, _TARGET_CODE)


if __name__ == "__main__":
    unittest.main()

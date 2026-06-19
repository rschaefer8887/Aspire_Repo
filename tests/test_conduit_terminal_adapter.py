"""Conduit Terminal Adapter family gate + size one-off (Fowler PVC TA lines)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_conduit_terminal_adapter_invoice_line,
    _norm,
)

_FOWLER_1 = '1" SCH 40 Conduit Terminal Adapter PVC TA1'
_FOWLER_1_NO_CODE = '1" SCH 40 Conduit Terminal Adapter PVC'
_FOWLER_34 = '3/4" SCH 40 Conduit Terminal Adapter PVC E943E'
_TARGET_1 = 'Conduit Terminal Adapter - 1" (Male Threads)'
_TARGET_34 = 'Conduit Terminal Adapter - 3/4" (Male Threads)'
_WRONG = 'PVC Male Adapter - 1" (SxT) - needs PVC cement'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("TA1", _TARGET_1, _TARGET_1, "Material"),
        InventoryRecord("E943E", _TARGET_34, _TARGET_34, "Material"),
        InventoryRecord("", _WRONG, "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_code:
            refs._by_code[_norm(rec.item_code)] = rec
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestConduitTerminalAdapterHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_conduit_terminal_adapter_invoice_line(_FOWLER_1))
        self.assertTrue(is_conduit_terminal_adapter_invoice_line(_FOWLER_34))
        self.assertFalse(is_conduit_terminal_adapter_invoice_line(_WRONG))


class TestConduitTerminalAdapterMatch(unittest.TestCase):
    def test_fowler_one_inch_with_ta1_code(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_FOWLER_1, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_1)
        self.assertGreaterEqual(conf, 0.90)
        self.assertNotEqual(rec.item_name, _WRONG)

    def test_fowler_one_inch_without_code_uses_one_off(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_FOWLER_1_NO_CODE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_1)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _WRONG)

    def test_fowler_three_quarter(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_FOWLER_34, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_34)
        self.assertNotEqual(rec.item_name, _WRONG)


class TestConduitTerminalAdapterCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_fowler_one_inch(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, note = self.refs.match_line(_FOWLER_1, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_1)
        self.assertGreaterEqual(conf, 0.90)
        self.assertNotIn("Male Adapter", rec.item_name or "")


if __name__ == "__main__":
    unittest.main()

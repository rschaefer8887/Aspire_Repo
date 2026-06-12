"""One-off: steel lock nut → Lock Nut, Steel - {size}."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_steel_lock_nut_invoice_line,
    _norm,
)

_THREE_QUARTER = '3/4" Steel Lock Nut'
_ONE_INCH = '1" Steel Lock Nut'
_TARGET_34 = 'Lock Nut, Steel - 3/4"'
_TARGET_1 = 'Lock Nut, Steel - 1"'
_WRONG = 'Brass Ball Valve - 3/4"'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", _TARGET_34, "", "Material"),
        InventoryRecord("", _TARGET_1, "", "Material"),
        InventoryRecord("", _WRONG, "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestSteelLockNutHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_steel_lock_nut_invoice_line(_THREE_QUARTER))
        self.assertTrue(is_steel_lock_nut_invoice_line(_ONE_INCH))
        self.assertFalse(is_steel_lock_nut_invoice_line('1" BRASS BALL VALVE THREADED'))


class TestSteelLockNutMatch(unittest.TestCase):
    def test_three_quarter_not_brass_ball_valve(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_THREE_QUARTER, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_34)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _WRONG)

    def test_one_inch_steel_lock_nut(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_ONE_INCH, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_1)
        self.assertIn("One-off", note)


class TestSteelLockNutCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_three_quarter_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, note = self.refs.match_line(_THREE_QUARTER, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET_34)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _WRONG)


if __name__ == "__main__":
    unittest.main()

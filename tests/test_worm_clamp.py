"""One-off: worm drive hose clamp → Worm Clamp (size ignored)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_worm_clamp_invoice_line,
    _norm,
)

_INVOICE_DESC = '1-9/16" - 2-1/2" SS WORM DRIVE HOSE CLAMP'
_TARGET = "Worm Clamp"
_WRONG = 'Galv. Nipple - 2" x 2-1/2"'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", _TARGET, "", "Material"),
        InventoryRecord("", _WRONG, "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestWormClampHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_worm_clamp_invoice_line(_INVOICE_DESC))
        self.assertFalse(is_worm_clamp_invoice_line('2" GALV NIPPLE'))


class TestWormClampMatch(unittest.TestCase):
    def test_one_off_matches_worm_clamp_not_nipple(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _WRONG)


class TestWormClampCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_worm_drive_hose_clamp(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == _TARGET for r in self.refs.inventory):
            self.skipTest(f"{_TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)


if __name__ == "__main__":
    unittest.main()

"""One-off match: Fowler jute matting box line → Irrigation Staples."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_irrigation_staples_invoice_line,
)

_JUTE_INVOICE_DESC = (
    '6" Staples 11 GA Jute Matting Sold by the Box (1000 per box)'
)


def _refs_staples_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", "Irrigation Staples", "", "Material"),
        InventoryRecord("", '6" Staples - 11 GA Jute Matting', "", "Material"),
        InventoryRecord("", "Landscape Staples", "", "Material"),
        InventoryRecord("", 'PVC Close Nipple - 2" (SCH 80)', "", "Material"),
    ]
    refs._by_name = {
        "irrigation staples": refs.inventory[0],
        '6" staples - 11 ga jute matting': refs.inventory[1],
        "landscape staples": refs.inventory[2],
        'pvc close nipple - 2" (sch 80)': refs.inventory[3],
    }
    return refs


class TestIrrigationStaplesMatch(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_irrigation_staples_invoice_line(_JUTE_INVOICE_DESC))
        self.assertFalse(is_irrigation_staples_invoice_line('1" PVC INSERT TEE'))

    def test_one_off_matches_irrigation_staples(self) -> None:
        refs = _refs_staples_fixture()
        rec, conf, note = refs.match_line(_JUTE_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, "Irrigation Staples")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)

    def test_one_off_not_landscape_staples_or_nipple(self) -> None:
        refs = _refs_staples_fixture()
        rec, _, _ = refs.match_line(_JUTE_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertNotEqual(rec.item_name, "Landscape Staples")
        self.assertNotIn("Nipple", rec.item_name or "")


class TestIrrigationStaplesCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_irrigation_staples(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, note = self.refs.match_line(_JUTE_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, "Irrigation Staples")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)


if __name__ == "__main__":
    unittest.main()

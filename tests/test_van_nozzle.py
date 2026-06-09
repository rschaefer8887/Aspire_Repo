"""One-off: Rain Bird VAN / Hunter adjustable arc nozzles → catch-all catalog row."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_van_nozzle_invoice_line,
    _norm,
)

_RAIN_BIRD_INVOICE = (
    "12' VAN VARIABLE ARC BROWN NOZZLE W/ SCREEN "
    "(25-BAG) SOLD BY THE EACH RAIN BIRD"
)
_HUNTER_INVOICE = (
    "15-A ADJUSTABLE ARC NOZZLE (25-BAG) SOLD BY THE EACH HUNTER"
)
_TARGET = "Rain Bird (VAN) Nozzle - All (or Hunter)"
_SIZE_SPECIFIC = "Rain Bird (VAN) Nozzle 12' - Brown"
_WRONG = 'PGV-101G 1" GLOBE VALVE W/FLOW CONTROL HUNTER'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("VAN", _TARGET, "", "Material"),
        InventoryRecord("12VAN", _SIZE_SPECIFIC, "", "Material"),
        InventoryRecord("", _WRONG, "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_code:
            refs._by_code[_norm(rec.item_code)] = rec
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestVanNozzleHelpers(unittest.TestCase):
    def test_rain_bird_van_invoice_detector(self) -> None:
        self.assertTrue(is_van_nozzle_invoice_line(_RAIN_BIRD_INVOICE))

    def test_hunter_adjustable_arc_invoice_detector(self) -> None:
        self.assertTrue(is_van_nozzle_invoice_line(_HUNTER_INVOICE))
        self.assertTrue(
            is_van_nozzle_invoice_line(
                "8-A ADJUSTABLE ARC NOZZLE (25-BAG) SOLD BY THE EACH HUNTER"
            )
        )

    def test_non_nozzle_hunter_not_detected(self) -> None:
        self.assertFalse(is_van_nozzle_invoice_line(_WRONG))


class TestVanNozzleMatch(unittest.TestCase):
    def test_rain_bird_one_off_matches_catch_all_not_size_sku(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_RAIN_BIRD_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertEqual(rec.item_code, "VAN")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _SIZE_SPECIFIC)

    def test_hunter_one_off_matches_catch_all(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_HUNTER_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)

    def test_hunter_valve_not_triggered(self) -> None:
        refs = _refs_fixture()
        rec, _, note = refs.match_line(_WRONG, None)
        if note:
            self.assertNotIn("One-off: VAN / Hunter adjustable arc nozzle", note)


class TestVanNozzleCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_rain_bird_van_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == _TARGET for r in self.refs.inventory):
            self.skipTest(f"{_TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(_RAIN_BIRD_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)

    def test_real_catalog_hunter_adjustable_arc_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == _TARGET for r in self.refs.inventory):
            self.skipTest(f"{_TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(_HUNTER_INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)


if __name__ == "__main__":
    unittest.main()

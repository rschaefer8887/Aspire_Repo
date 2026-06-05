"""Tests for PVC insert plug matching (I7323239-style Fowler lines)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    _catalog_matches_product_hint,
    _fitting_sizes_compatible,
    _product_hint,
    _pvc_insert_baseline,
)


def _refs_i7323239() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", "PVC Insert Plug - 1-1/4\"", "", "Material"),
        InventoryRecord("", "PVC Insert Plug - 1-1/2\"", "", "Material"),
        InventoryRecord("", 'PVC Insert Elbow (90) - 1/2" (IxI)', "", "Material"),
        InventoryRecord("", "PVC Insert Coupling - 1-1/2\"", "", "Material"),
        InventoryRecord("", 'PVC Insert Tee - 1-1/2"', "", "Material"),
    ]
    return refs


class TestPvcInsertPlug(unittest.TestCase):
    def test_product_hint_plug_word_boundary(self) -> None:
        self.assertEqual(_product_hint('1-1/2" PVC INSERT PLUG I'), "plug")
        self.assertIsNone(_product_hint("MISC SUPPLY ITEM 123"))

    def test_catalog_plug_hint_requires_word_boundary(self) -> None:
        self.assertTrue(_catalog_matches_product_hint("plug", "pvc insert plug - 1-1/2"))
        self.assertFalse(_catalog_matches_product_hint("plug", "pvc insert elbow (90)"))

    def test_plug_strict_size_rejects_half_inch_elbow(self) -> None:
        self.assertFalse(_fitting_sizes_compatible({"1-1/2"}, {"1/2"}))

    def test_pvc_insert_baseline_is_single_bonus(self) -> None:
        self.assertEqual(
            _pvc_insert_baseline(
                "1-1/2 pvc insert plug",
                "pvc insert elbow (90) - 1/2",
            ),
            0.08,
        )

    def test_one_and_quarter_plug(self) -> None:
        refs = _refs_i7323239()
        rec, conf, _ = refs.match_line('1-1/4" PVC INSERT PLUG I', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'PVC Insert Plug - 1-1/4"')
        self.assertGreaterEqual(conf, 0.85)

    def test_one_and_half_plug_not_elbow(self) -> None:
        refs = _refs_i7323239()
        rec, conf, _ = refs.match_line('1-1/2" PVC INSERT PLUG I', None)
        self.assertIsNotNone(rec)
        self.assertIn("Plug", rec.item_name or "")
        self.assertNotIn("Elbow", rec.item_name or "")
        self.assertEqual(rec.item_name, 'PVC Insert Plug - 1-1/2"')
        self.assertGreaterEqual(conf, 0.85)

    def test_half_inch_on_invoice_does_not_match_one_and_half_plug(self) -> None:
        refs = _refs_i7323239()
        rec, conf, _ = refs.match_line('1/2" PVC INSERT PLUG I', None)
        if rec is not None:
            self.assertIn("1/2", rec.item_name or "")
            self.assertNotIn("1-1/2", rec.item_name or "")


class TestPvcInsertPlugCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_plug_one_and_half(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, _ = self.refs.match_line('1-1/2" PVC INSERT PLUG I', None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertIn("plug", name)
        self.assertNotIn("elbow", name)
        self.assertIn("1-1/2", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.85)


if __name__ == "__main__":
    unittest.main()

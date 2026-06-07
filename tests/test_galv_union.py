"""Tests for galvanized union matching (strict size, family gate)."""

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
    _product_hint,
)


def _refs_galv_union_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", 'Galv. Union - 1"', "", "Material"),
        InventoryRecord("", 'Galv. Union - 1-1/2"', "", "Material"),
        InventoryRecord("", 'Galv. Coupling - 1"', "", "Material"),
        InventoryRecord("", 'Galv. Tee - 1"', "", "Material"),
    ]
    return refs


class TestGalvUnionHelpers(unittest.TestCase):
    def test_product_hint_union_word_boundary(self) -> None:
        self.assertEqual(_product_hint('1" GALV UNION'), "union")
        self.assertEqual(_product_hint("GALVANIZED UNION 1-1/2 IN"), "union")
        self.assertIsNone(_product_hint("COMMUNION FITTING"))

    def test_catalog_union_hint_requires_word_boundary(self) -> None:
        self.assertTrue(_catalog_matches_product_hint("union", "galv. union - 1"))
        self.assertFalse(_catalog_matches_product_hint("union", "galv. coupling - 1"))


class TestGalvUnionMatch(unittest.TestCase):
    def test_one_inch_galv_union(self) -> None:
        refs = _refs_galv_union_fixture()
        rec, conf, _ = refs.match_line('1" GALV UNION', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'Galv. Union - 1"')
        self.assertGreaterEqual(conf, 0.85)

    def test_galvanized_union_not_coupling_or_tee(self) -> None:
        refs = _refs_galv_union_fixture()
        rec, _, _ = refs.match_line('1" GALVANIZED UNION FITTING', None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertIn("union", name)
        self.assertNotIn("coupling", name)
        self.assertNotIn("tee", name)

    def test_strict_size_rejects_wrong_union(self) -> None:
        refs = _refs_galv_union_fixture()
        rec, _, _ = refs.match_line('1-1/2" GALV UNION', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'Galv. Union - 1-1/2"')
        self.assertNotEqual(rec.item_name, 'Galv. Union - 1"')

    def test_union_invoice_does_not_match_galv_tee_same_size(self) -> None:
        refs = _refs_galv_union_fixture()
        rec, _, _ = refs.match_line('1" GALV UNION', None)
        self.assertIsNotNone(rec)
        self.assertNotIn("Tee", rec.item_name or "")


class TestGalvUnionCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_galv_union(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        unions = [
            r
            for r in self.refs.inventory
            if r.item_name and "union" in r.item_name.lower()
        ]
        if not unions:
            self.skipTest("no union items in catalog export")
        rec, conf, _ = self.refs.match_line('1" GALV UNION', None)
        self.assertIsNotNone(rec)
        self.assertIn("union", (rec.item_name or "").lower())
        self.assertGreaterEqual(conf, 0.85)


if __name__ == "__main__":
    unittest.main()

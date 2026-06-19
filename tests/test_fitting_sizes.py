"""Tests for strict size matching on irrigation fittings (tee, elbow, etc.)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    _fitting_sizes_compatible,
    _norm,
    _size_match_score,
    _sizes_from_text,
)


def _refs_with_pvc_insert_tees() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", '1" PVC Insert Tee', "", "Material"),
        InventoryRecord("", '1-1/2" PVC Insert Tee', "", "Material"),
        InventoryRecord("", '1-1/2" x 1" PVC Insert Tee', "", "Material"),
        InventoryRecord("", '1" x 3/4" PVC Insert Tee', "", "Material"),
        InventoryRecord("", '2" PVC Insert Tee', "", "Material"),
    ]
    return refs


class TestFittingSizeHelpers(unittest.TestCase):
    def test_sizes_from_text_equal_tee(self) -> None:
        sizes = _sizes_from_text('1-1/2" PVC INSERT TEE')
        self.assertIn("1-1/2", sizes)
        self.assertEqual(len(sizes), 1)

    def test_sizes_from_text_reducing_tee(self) -> None:
        sizes = _sizes_from_text('1-1/2" x 1" PVC INSERT TEE')
        self.assertEqual(sizes, {"1-1/2", "1"})

    def test_sizes_from_text_compact_fraction_x_inch(self) -> None:
        sizes = _sizes_from_text(
            'PVC Insert Elbow (90) Reducing - 1-1/2"x1" (IxF)'
        )
        self.assertEqual(sizes, {"1-1/2", "1"})

    def test_sizes_from_text_compact_inch_x_fraction(self) -> None:
        sizes = _sizes_from_text('Reducing - 2"x1-1/2" (IxF)')
        self.assertEqual(sizes, {"2", "1-1/2"})

    def test_sizes_from_text_compact_fraction_x_fraction(self) -> None:
        sizes = _sizes_from_text('Reducing - 1-1/4"x3/4" (IxF)')
        self.assertEqual(sizes, {"1-1/4", "3/4", "3-4/4"})

    def test_sizes_from_text_compact_inch_x_inch(self) -> None:
        sizes = _sizes_from_text('PVC Insert Tee x Female Adapter - 2"x1"')
        self.assertEqual(sizes, {"2", "1"})

    def test_sizes_from_text_hyphenated_fraction_x_fraction(self) -> None:
        sizes = _sizes_from_text('1-1/2" X 1-1/4" PVC INSERT COUPLING IXI')
        self.assertEqual(sizes, {"1-1/2", "1-1/4"})

    def test_sizes_from_text_catalog_hyphenated_fraction_x_fraction(self) -> None:
        sizes = _sizes_from_text(
            'PVC Insert Coupler (reducing) - 1-1/2" x 1-1/4"'
        )
        self.assertEqual(sizes, {"1-1/2", "1-1/4"})

    def test_fitting_strict_rejects_partial_overlap(self) -> None:
        desc = {"1-1/2", "1"}
        equal_tee = {"1-1/2"}
        self.assertFalse(_fitting_sizes_compatible(desc, equal_tee))
        self.assertTrue(_fitting_sizes_compatible(desc, desc))

    def test_fitting_strict_single_size_rejects_reducing_catalog(self) -> None:
        self.assertTrue(_fitting_sizes_compatible({"1-1/2"}, {"1-1/2"}))
        self.assertFalse(_fitting_sizes_compatible({"1-1/2"}, {"1-1/2", "1"}))

    def test_size_match_score_exact_beats_partial(self) -> None:
        exact_score, exact_tie = _size_match_score({"1-1/2", "1"}, {"1-1/2", "1"})
        partial_score, partial_tie = _size_match_score({"1-1/2", "1"}, {"1-1/2"})
        self.assertGreater(exact_score, partial_score)
        self.assertGreater(exact_tie, partial_tie)


class TestCompactReducingElbowMatch(unittest.TestCase):
    def test_ixfipt_elbow_matches_compact_catalog_name(self) -> None:
        refs = ReferenceData()
        refs.inventory = [
            InventoryRecord(
                "1406-015",
                'PVC Insert Elbow (90) - 1-1/2" (IxI)',
                "",
                "Material",
            ),
            InventoryRecord(
                "1407-211",
                'PVC Insert Elbow (90) Reducing - 1-1/2"x1" (IxF)',
                "",
                "Material",
            ),
        ]
        for rec in refs.inventory:
            if rec.item_code:
                refs._by_code[rec.item_code] = rec
        desc = '1-1/2" X 1" PVC Insert 90 Elbow IXFIPT'
        rec, conf, note = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "1407-211")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note or "")


class TestFittingCatalogMatch(unittest.TestCase):
    def test_equal_tee_picks_same_size_not_reducing(self) -> None:
        refs = _refs_with_pvc_insert_tees()
        rec, conf, _ = refs.match_line('1-1/2" PVC INSERT TEE IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, '1-1/2" PVC Insert Tee')
        self.assertGreaterEqual(conf, 0.85)

    def test_reducing_tee_requires_both_sizes(self) -> None:
        refs = _refs_with_pvc_insert_tees()
        rec, _, _ = refs.match_line('1-1/2" x 1" PVC INSERT TEE IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, '1-1/2" x 1" PVC Insert Tee')

    def test_one_inch_tee_not_matched_to_reducing(self) -> None:
        refs = _refs_with_pvc_insert_tees()
        rec, _, _ = refs.match_line('1" PVC INSERT TEE IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, '1" PVC Insert Tee')
        self.assertNotIn(" x ", rec.item_name or "")


class TestReducingCouplerMatch(unittest.TestCase):
    _INVOICE = '1-1/2" X 1-1/4" PVC INSERT COUPLING IXI'
    _TARGET = 'PVC Insert Coupler (reducing) - 1-1/2" x 1-1/4"'
    _WRONG = 'PVC Insert Coupler (reducing) - 2" x 1-1/4"'

    def _refs_fixture(self) -> ReferenceData:
        refs = ReferenceData()
        refs.inventory = [
            InventoryRecord("", self._TARGET, self._TARGET, "Material"),
            InventoryRecord("", self._WRONG, self._WRONG, "Material"),
        ]
        for rec in refs.inventory:
            if rec.item_name:
                refs._by_name[_norm(rec.item_name)] = rec
        return refs

    def test_reducing_coupler_not_two_inch(self) -> None:
        refs = self._refs_fixture()
        rec, conf, _ = refs.match_line(self._INVOICE, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, self._TARGET)
        self.assertGreaterEqual(conf, 0.85)
        self.assertNotEqual(rec.item_name, self._WRONG)


class TestFittingSizeCatalogIntegration(unittest.TestCase):
    """Match against real catalog when export is present."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()
        cls.tees = [
            r
            for r in cls.refs.inventory
            if r.item_name and "pvc insert tee" in r.item_name.lower()
        ]

    def test_catalog_has_pvc_insert_tees(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        self.assertGreater(len(self.tees), 3)

    def test_equal_tee_from_real_catalog(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, _ = self.refs.match_line('1-1/2" PVC INSERT TEE', None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertIn("1-1/2", rec.item_name or "")
        self.assertIn("tee", name)
        self.assertNotIn(" x ", name)


if __name__ == "__main__":
    unittest.main()

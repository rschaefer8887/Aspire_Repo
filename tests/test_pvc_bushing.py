"""Tests for PVC bushing matching (reducing bushing vs insert male adapter)."""

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
    _sizes_from_text,
)


def _refs_bushing_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord(
            "",
            'PVC Bushing - 1-1/2" x 1" (MxF)',
            'PVC Bushing - 1-1/2" x 1" (TxT) - SCH40',
            "Material",
        ),
        InventoryRecord(
            "",
            'PVC Insert x Male Adapter - 1-1/2" x 1"',
            "",
            "Material",
        ),
        InventoryRecord(
            "",
            '1-1/4" X 1" PVC INSERT MALE ADAPTER IXMIPT',
            "",
            "Material",
        ),
    ]
    return refs


class TestPvcBushingHelpers(unittest.TestCase):
    def test_product_hint_bushing_word_boundary(self) -> None:
        self.assertEqual(
            _product_hint('1-1/2" x 1" SCH 40 PVC BUSHING TXT'),
            "bushing",
        )
        self.assertIsNone(_product_hint("DEBRISHING NET"))

    def test_catalog_bushing_hint_requires_word_boundary(self) -> None:
        self.assertTrue(
            _catalog_matches_product_hint(
                "bushing",
                'pvc bushing - 1-1/2" x 1" (mxf)',
            )
        )
        self.assertFalse(
            _catalog_matches_product_hint(
                "bushing",
                'pvc insert x male adapter - 1-1/2" x 1"',
            )
        )

    def test_reducing_bushing_sizes(self) -> None:
        sizes = _sizes_from_text('1-1/2" x 1" SCH 40 PVC BUSHING TXT')
        self.assertEqual(sizes, {"1-1/2", "1"})
        self.assertTrue(_fitting_sizes_compatible({"1-1/2", "1"}, {"1-1/2", "1"}))
        self.assertFalse(_fitting_sizes_compatible({"1-1/2", "1"}, {"1-1/2"}))


class TestPvcBushingMatch(unittest.TestCase):
    def test_fowler_bushing_txt_not_male_adapter(self) -> None:
        refs = _refs_bushing_fixture()
        desc = '1-1/2" x 1" SCH 40 PVC BUSHING TXT'
        rec, conf, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(conf, 0.85)
        name = (rec.item_name or "").lower()
        self.assertIn("bushing", name)
        self.assertNotIn("adapter", name)
        self.assertEqual(rec.item_name, 'PVC Bushing - 1-1/2" x 1" (MxF)')
        alt = (rec.item_alternate_name or "").lower()
        self.assertIn("txt", alt)
        self.assertIn("sch40", alt.replace(" ", ""))

    def test_male_adapter_line_unchanged(self) -> None:
        refs = _refs_bushing_fixture()
        rec, conf, _ = refs.match_line(
            '1-1/4" X 1" PVC INSERT MALE ADAPTER IXMIPT',
            None,
        )
        self.assertIsNotNone(rec)
        self.assertIn("adapter", (rec.item_name or "").lower())
        self.assertNotIn("bushing", (rec.item_name or "").lower())
        self.assertGreaterEqual(conf, 0.85)


class TestPvcBushingCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_bushing_reducing(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        desc = '1-1/2" x 1" SCH 40 PVC BUSHING TXT'
        rec, conf, _ = self.refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(conf, 0.85)
        blob = " ".join(
            p
            for p in (
                rec.item_name,
                rec.item_alternate_name,
            )
            if p
        ).lower()
        self.assertIn("bushing", blob)
        self.assertNotIn("male adapter", blob)


if __name__ == "__main__":
    unittest.main()

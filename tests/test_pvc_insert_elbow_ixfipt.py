"""One-off: PVC insert 90° elbow IxFIPT → Insert Elbow (IxF)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_pvc_insert_elbow_ixfipt_line,
    _norm,
)

_REDUCING_INVOICE_DESC = '1-1/2" X 1" PVC Insert 90 Elbow IXFIPT'
_TARGET = 'PVC Insert Elbow (90) Reducing - 1-1/2" x 1" (IxF)'
_PLAIN_IXI = 'PVC Insert Elbow (90) - 1-1/2" (IxI)'
_COMPACT_TARGET = 'PVC Insert Elbow (90) Reducing - 1-1/2"x1" (IxF)'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("1406-015", _PLAIN_IXI, "", "Material"),
        InventoryRecord("1407-211", _TARGET, "", "Material"),
        InventoryRecord("", _COMPACT_TARGET, "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_code:
            refs._by_code[_norm(rec.item_code)] = rec
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestPvcInsertElbowIxfiptHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_pvc_insert_elbow_ixfipt_line(_REDUCING_INVOICE_DESC))
        self.assertFalse(
            is_pvc_insert_elbow_ixfipt_line('1-1/2" PVC INSERT 90 ELBOW IXI')
        )
        self.assertFalse(
            is_pvc_insert_elbow_ixfipt_line(
                '1-1/2" x 1" PVC INSERT TEE IXIXFIPT'
            )
        )


class TestPvcInsertElbowIxfiptMatch(unittest.TestCase):
    def test_one_off_matches_ixf_not_plain_ixi(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_REDUCING_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertEqual(rec.item_code, "1407-211")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _PLAIN_IXI)

    def test_compact_catalog_name_via_one_off(self) -> None:
        refs = ReferenceData()
        refs.inventory = [
            InventoryRecord("1406-015", _PLAIN_IXI, "", "Material"),
            InventoryRecord("1407-211", _COMPACT_TARGET, "", "Material"),
        ]
        for rec in refs.inventory:
            if rec.item_code:
                refs._by_code[_norm(rec.item_code)] = rec
            if rec.item_name:
                refs._by_name[_norm(rec.item_name)] = rec
        rec, conf, note = refs.match_line(_REDUCING_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _COMPACT_TARGET)
        self.assertIn("One-off", note)

    def test_plain_ixi_elbow_not_triggered(self) -> None:
        refs = _refs_fixture()
        rec, _, note = refs.match_line('1-1/2" PVC INSERT 90 ELBOW IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _PLAIN_IXI)
        if note:
            self.assertNotIn("One-off: PVC insert elbow IxFIPT", note)


class TestPvcInsertElbowIxfiptCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_ixfipt_reducing_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == _TARGET for r in self.refs.inventory):
            self.skipTest(f"{_TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(_REDUCING_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, _TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, _PLAIN_IXI)


if __name__ == "__main__":
    unittest.main()

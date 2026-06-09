"""One-off: PVC insert tee IxIxFIPT → PVC Insert Tee x Female adapter (IxIxF)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_pvc_insert_tee_fipt_branch_invoice_line,
    _norm,
)

_INVOICE_DESC = '1-1/2" PVC Insert Tee IXIXFIPT'
_REDUCING_INVOICE_DESC = '1-1/2" x 1" PVC INSERT TEE IXIXFIPT'
TARGET = 'PVC Insert Tee x Female adapter- 1-1/2" (IxIxF)'
PLAIN = 'PVC Insert Tee - 1-1/2" x 1"'
PLAIN_EQUAL = 'PVC Insert Tee - 1-1/2"'
REDUCING = 'PVC Insert Tee x Female Adapter - 1-1/2"x1"'


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("1401-211", PLAIN, "", "Material"),
        InventoryRecord("1402-015", TARGET, "", "Material"),
        InventoryRecord("", REDUCING, "", "Material"),
        InventoryRecord("", PLAIN_EQUAL, "", "Material"),
        InventoryRecord("", 'PVC Insert Tee - 1"', "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_code:
            refs._by_code[_norm(rec.item_code)] = rec
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestPvcInsertTeeFiptBranchHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(is_pvc_insert_tee_fipt_branch_invoice_line(_INVOICE_DESC))
        self.assertFalse(
            is_pvc_insert_tee_fipt_branch_invoice_line('1-1/2" PVC INSERT TEE IXI')
        )
        self.assertTrue(
            is_pvc_insert_tee_fipt_branch_invoice_line(
                '1-1/2" x 1" PVC INSERT TEE IXIXFIPT'
            )
        )


class TestPvcInsertTeeFiptBranchMatch(unittest.TestCase):
    def test_one_off_matches_female_ixixf_not_plain_tee(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, TARGET)
        self.assertEqual(rec.item_code, "1402-015")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, PLAIN)
        self.assertNotEqual(rec.item_name, REDUCING)

    def test_reducing_ixixfipt_matches_female_adapter_not_plain_tee(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(_REDUCING_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, REDUCING)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, PLAIN)

    def test_plain_ixi_still_matches_reducing_tee(self) -> None:
        refs = _refs_fixture()
        rec, _, note = refs.match_line('1-1/2" x 1" PVC INSERT TEE IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, PLAIN)
        if note:
            self.assertNotIn("One-off: PVC insert tee IxIxFIPT", note)

    def test_plain_ixi_still_matches_equal_tee(self) -> None:
        refs = _refs_fixture()
        rec, _, note = refs.match_line('1-1/2" PVC INSERT TEE IXI', None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, PLAIN_EQUAL)
        if note:
            self.assertNotIn("One-off: PVC insert tee IxIxFIPT", note)


class TestPvcInsertTeeFiptBranchCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_ixixfipt_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == TARGET for r in self.refs.inventory):
            self.skipTest(f"{TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, PLAIN_EQUAL)

    def test_real_catalog_reducing_ixixfipt_line(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == REDUCING for r in self.refs.inventory):
            self.skipTest(f"{REDUCING} not in catalog export")
        rec, conf, note = self.refs.match_line(_REDUCING_INVOICE_DESC, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, REDUCING)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, PLAIN)


if __name__ == "__main__":
    unittest.main()

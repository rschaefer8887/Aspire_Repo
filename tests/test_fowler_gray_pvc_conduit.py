"""One-off match: Fowler gray SCH 40 PVC conduit → Conduit Gray - {size}."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_fowler_gray_pvc_conduit_invoice_line,
)
from idp_vendor_prefs import hd_fowler_preferred_vendor_name  # noqa: E402

_CONDUIT_INVOICE_DESC = (
    '3/4" GRAY SCH 40 PVC CONDUIT BE, 10\' LENGTH'
)
TURF = hd_fowler_preferred_vendor_name()


def _refs_conduit_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", "Conduit Gray - 3/4", "", "Material"),
        InventoryRecord("", 'Conduit Gray - 1" (SCH 40)', "", "Material"),
        InventoryRecord("", 'PVC Coupler - 3/4" (FxF), SCH 40', "", "Material"),
        InventoryRecord("", 'PVC Coupler - 1" (FxF), SCH 40', "", "Material"),
    ]
    return refs


class TestFowlerGrayPvcConduitHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(
            is_fowler_gray_pvc_conduit_invoice_line(
                _CONDUIT_INVOICE_DESC,
                vendor_name=TURF,
            )
        )
        self.assertFalse(
            is_fowler_gray_pvc_conduit_invoice_line(
                _CONDUIT_INVOICE_DESC,
                vendor_name="Other Supply Co",
            )
        )
        self.assertFalse(
            is_fowler_gray_pvc_conduit_invoice_line('3/4" PVC COUPLER SCH 40')
        )


class TestFowlerGrayPvcConduitMatch(unittest.TestCase):
    def test_one_off_matches_conduit_gray_not_coupler(self) -> None:
        refs = _refs_conduit_fixture()
        rec, conf, note = refs.match_line(
            _CONDUIT_INVOICE_DESC,
            None,
            vendor_name=TURF,
            vendor_raw="H.D. Fowler",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, "Conduit Gray - 3/4")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotIn("Coupler", rec.item_name or "")

    def test_non_fowler_vendor_does_not_use_one_off(self) -> None:
        refs = _refs_conduit_fixture()
        rec, _, note = refs.match_line(
            _CONDUIT_INVOICE_DESC,
            None,
            vendor_name="Other Supply Co",
        )
        self.assertIsNotNone(rec)
        self.assertNotIn("One-off", note or "")
        self.assertIn("Coupler", rec.item_name or "")

    def test_one_inch_conduit_picks_correct_size(self) -> None:
        refs = _refs_conduit_fixture()
        rec, _, _ = refs.match_line(
            '1" GRAY SCH 40 PVC CONDUIT BE 10\' LENGTH',
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'Conduit Gray - 1" (SCH 40)')


class TestFowlerGrayPvcConduitCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_conduit_gray(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        conduits = [
            r
            for r in self.refs.inventory
            if r.item_name
            and "conduit gray" in r.item_name.lower()
            and "3/4" in r.item_name
        ]
        if not conduits:
            self.skipTest("Conduit Gray - 3/4 not in catalog export")
        rec, conf, note = self.refs.match_line(
            _CONDUIT_INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertIn("conduit gray", (rec.item_name or "").lower())
        self.assertIn("3/4", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotIn("coupler", (rec.item_name or "").lower())


if __name__ == "__main__":
    unittest.main()

"""One-off match: Fowler black SIDR-15 poly pipe → Poly Pipe (SIDR 15), non-green."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_fowler_black_sidr15_poly_pipe_invoice_line,
)
from idp_vendor_prefs import hd_fowler_preferred_vendor_name  # noqa: E402

_BLACK_POLY_INVOICE_DESC = (
    '1-1/2" 100 PSI SIDR-15 POLY PIPE 300\' ROLL 3608 RESIN, BLACK'
)
TURF = hd_fowler_preferred_vendor_name()


def _refs_poly_pipe_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", 'Poly Pipe - 1.5" (SIDR 15)', "", "Material"),
        InventoryRecord("", 'Poly Pipe - 1" (SIDR 15)', "", "Material"),
        InventoryRecord("", 'Green Poly Pipe - 1.5" (SIDR 15)', "", "Material"),
        InventoryRecord("", 'Poly Pipe - 1.5" (SIDR 11)', "", "Material"),
        InventoryRecord("", 'PVC Coupler - 1-1/2" (FxF), SCH 40', "", "Material"),
    ]
    return refs


class TestBlackSidr15PolyPipeHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(
            is_fowler_black_sidr15_poly_pipe_invoice_line(
                _BLACK_POLY_INVOICE_DESC,
                vendor_name=TURF,
            )
        )
        self.assertFalse(
            is_fowler_black_sidr15_poly_pipe_invoice_line(
                _BLACK_POLY_INVOICE_DESC,
                vendor_name="Other Supply Co",
            )
        )
        self.assertFalse(
            is_fowler_black_sidr15_poly_pipe_invoice_line(
                '1" PRO TURF GREEN SIDR-15 100 PSI POLY PIPE 300\' ROLL 3608 HDPE',
                vendor_name=TURF,
            )
        )
        self.assertFalse(
            is_fowler_black_sidr15_poly_pipe_invoice_line(
                '1-1/2" POLY PIPE SIDR-11 100 PSI',
                vendor_name=TURF,
            )
        )


class TestBlackSidr15PolyPipeMatch(unittest.TestCase):
    def test_one_off_matches_poly_pipe_sidr15_not_green(self) -> None:
        refs = _refs_poly_pipe_fixture()
        rec, conf, note = refs.match_line(
            _BLACK_POLY_INVOICE_DESC,
            None,
            vendor_name=TURF,
            vendor_raw="H.D. Fowler",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'Poly Pipe - 1.5" (SIDR 15)')
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotIn("green", (rec.item_name or "").lower())
        self.assertNotIn("SIDR 11", rec.item_name or "")

    def test_does_not_match_green_poly_pipe(self) -> None:
        refs = _refs_poly_pipe_fixture()
        rec, _, _ = refs.match_line(
            _BLACK_POLY_INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, 'Poly Pipe - 1.5" (SIDR 15)')
        self.assertNotEqual(rec.item_name, 'Green Poly Pipe - 1.5" (SIDR 15)')

    def test_does_not_match_one_inch_when_one_and_half_in_catalog(self) -> None:
        refs = _refs_poly_pipe_fixture()
        rec, _, _ = refs.match_line(
            _BLACK_POLY_INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertIn("1.5", rec.item_name or "")

    def test_non_fowler_does_not_use_one_off(self) -> None:
        refs = _refs_poly_pipe_fixture()
        rec, _, note = refs.match_line(
            _BLACK_POLY_INVOICE_DESC,
            None,
            vendor_name="Other Supply Co",
        )
        if rec and note:
            self.assertNotIn("One-off: Fowler black SIDR-15", note)


class TestBlackSidr15PolyPipeCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_poly_pipe_one_and_half_sidr15(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        poly_sidr15 = [
            r
            for r in self.refs.inventory
            if r.item_name
            and "poly pipe" in r.item_name.lower()
            and "green" not in r.item_name.lower()
            and "sidr 15" in r.item_name.lower()
            and "1.5" in r.item_name
        ]
        if not poly_sidr15:
            self.skipTest('Poly Pipe - 1.5" (SIDR 15) not in catalog export')
        rec, conf, note = self.refs.match_line(
            _BLACK_POLY_INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertNotIn("green", (rec.item_name or "").lower())
        self.assertIn("sidr 15", (rec.item_name or "").lower())
        self.assertIn("1.5", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)


if __name__ == "__main__":
    unittest.main()

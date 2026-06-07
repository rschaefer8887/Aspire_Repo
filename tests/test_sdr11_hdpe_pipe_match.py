"""Match test: Fowler 2\" SDR/SIDR 11 HDPE mainline coil → Poly Pipe - 2\" (SIDR 11)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    is_fowler_hdpe_sidr11_pipe_invoice_line,
    _norm,
)
from idp_vendor_prefs import hd_fowler_preferred_vendor_name  # noqa: E402

_INVOICE_DESC = '2" 200 PSI SDR 11 IPS HDPE Pipe 500\' Coils'
TARGET = 'Poly Pipe - 2" (SIDR 11)'
TURF = hd_fowler_preferred_vendor_name()


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", TARGET, "", "Material"),
        InventoryRecord("", 'Poly Pipe - 2" (SIDR 15)', "", "Material"),
        InventoryRecord(
            "",
            'Butt Reducer - 2" x 1-1/2" (SIDR 11)',
            'Molded Butt Reducer - 2" x 1-1/2" (SDR 11, IPS, HDPE)',
            "Material",
        ),
        InventoryRecord("", 'Poly Pipe - 1.5" (SIDR 11)', "", "Material"),
        InventoryRecord("", 'Poly (HDPE SIDR 11) - 4"', "", "Material"),
    ]
    for rec in refs.inventory:
        if rec.item_name:
            refs._by_name[_norm(rec.item_name)] = rec
    return refs


class TestSdr11HdpePipeHelpers(unittest.TestCase):
    def test_invoice_line_detector(self) -> None:
        self.assertTrue(
            is_fowler_hdpe_sidr11_pipe_invoice_line(
                _INVOICE_DESC,
                vendor_name=TURF,
            )
        )
        self.assertFalse(
            is_fowler_hdpe_sidr11_pipe_invoice_line(
                _INVOICE_DESC,
                vendor_name="Other Supply Co",
            )
        )
        self.assertFalse(
            is_fowler_hdpe_sidr11_pipe_invoice_line(
                'Compression Adapter - 2" (200 psi)',
                vendor_name=TURF,
            )
        )


class TestSdr11HdpePipeMatch(unittest.TestCase):
    def test_fixture_matches_two_inch_sidr11_poly_pipe(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(
            _INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)
        self.assertNotEqual(rec.item_name, 'Poly Pipe - 2" (SIDR 15)')

    def test_fixture_not_butt_reducer_despite_hdpe_ips_overlap(self) -> None:
        refs = _refs_fixture()
        rec, _, _ = refs.match_line(_INVOICE_DESC, None, vendor_name=TURF)
        self.assertIsNotNone(rec)
        self.assertNotIn("reducer", (rec.item_name or "").lower())


class TestSdr11HdpePipeCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_matches_two_inch_sidr11_poly_pipe(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        target_rows = [
            r
            for r in self.refs.inventory
            if r.item_name == TARGET
        ]
        if not target_rows:
            self.skipTest(f"{TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(
            _INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec, msg=f"no match; note={note!r}")
        self.assertEqual(rec.item_name, TARGET, msg=f"got {rec.item_name!r}")
        self.assertIn("sidr 11", (rec.item_name or "").lower())
        self.assertNotIn("sidr 15", (rec.item_name or "").lower())
        self.assertGreaterEqual(conf, 0.90)
        self.assertIn("One-off", note)


if __name__ == "__main__":
    unittest.main()

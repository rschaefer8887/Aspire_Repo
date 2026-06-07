"""Fowler 2\" SDR 11 butt fusion tee → Butt Fusion Molded Tee - 2\" (SIDR 11)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import InventoryRecord, ReferenceData  # noqa: E402
from idp_vendor_prefs import hd_fowler_preferred_vendor_name  # noqa: E402

_INVOICE_DESC = '2" SDR 11 TEE IPS HDPE MOLDED BUTT FUSION'
TARGET = 'Butt Fusion Molded Tee - 2" (SIDR 11)'
TURF = hd_fowler_preferred_vendor_name()


def _refs_fixture() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord("", TARGET, "", "Material"),
        InventoryRecord("", 'Poly Pipe - 2" (SIDR 11)', "", "Material"),
        InventoryRecord(
            "",
            'Butt Reducer - 2" x 1-1/2" (SIDR 11)',
            'Molded Butt Reducer - 2" x 1-1/2" (SDR 11, IPS, HDPE)',
            "Material",
        ),
        InventoryRecord("", 'Brass Tee - 2"x1"', "", "Material"),
        InventoryRecord("", 'Galv. Tee - 2"', "", "Material"),
    ]
    return refs


class TestButtFusionTeeSidr11Match(unittest.TestCase):
    def test_matches_butt_fusion_molded_tee_not_poly_pipe(self) -> None:
        refs = _refs_fixture()
        rec, conf, note = refs.match_line(
            _INVOICE_DESC,
            None,
            vendor_name=TURF,
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, TARGET)
        self.assertGreaterEqual(conf, 0.85)
        self.assertNotEqual(rec.item_name, 'Poly Pipe - 2" (SIDR 11)')


class TestButtFusionTeeSidr11CatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_real_catalog_butt_fusion_molded_tee(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        if not any(r.item_name == TARGET for r in self.refs.inventory):
            self.skipTest(f"{TARGET} not in catalog export")
        rec, conf, note = self.refs.match_line(
            _INVOICE_DESC,
            None,
            vendor_name=TURF,
            vendor_raw="H.D. Fowler",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_name, TARGET)
        self.assertGreaterEqual(conf, 0.90)
        self.assertNotIn("poly pipe", (rec.item_name or "").lower())


if __name__ == "__main__":
    unittest.main()

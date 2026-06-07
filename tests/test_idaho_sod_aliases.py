"""Sod catalog alias matching for Idaho Sod invoices."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import ReferenceData  # noqa: E402
from idp_sod import match_sod_catalog  # noqa: E402


class TestIdahoSodAliases(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        cls.refs.load()

    def test_kentucky_maps_bluegrass(self) -> None:
        rec, conf, _ = match_sod_catalog("3450 Kentucky Bluegrass", self.refs)
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(conf, 0.9)
        self.assertIn("Bluegrass", rec.item_name or "")

    def test_rtf_maps_rhizomatous(self) -> None:
        rec, conf, _ = match_sod_catalog("2000 RTF Sod", self.refs)
        self.assertIsNotNone(rec)
        self.assertIn("RTF", rec.item_name or "")

    def test_meadow_grass(self) -> None:
        rec, _, _ = match_sod_catalog("1500 Meadow Grass", self.refs)
        self.assertIsNotNone(rec)
        self.assertIn("Meadow", rec.item_name or "")

    def test_fescue_not_rtf(self) -> None:
        rec, _, _ = match_sod_catalog("1000 Fescue Sod", self.refs)
        self.assertIsNotNone(rec)
        name = rec.item_name or ""
        self.assertIn("Fescue", name)
        self.assertNotIn("RTF", name)


if __name__ == "__main__":
    unittest.main()

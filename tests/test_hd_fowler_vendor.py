"""Tests for HD Fowler Turf vendor preference over Waterworks."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_lookups import LookupService  # noqa: E402
from idp_reference import ReferenceData, VendorRecord  # noqa: E402
from idp_vendor_prefs import (  # noqa: E402
    exclude_vendor_from_llm_list,
    hd_fowler_preferred_vendor_name,
    is_hd_fowler_vendor,
    resolve_hd_fowler_vendor,
)

TURF = "H.D. Fowler Company {Turf}"
WATERWORKS = "H.D. Fowler Company {Waterworks}"


def _refs_with_fowler_vendors() -> ReferenceData:
    refs = ReferenceData()
    refs.vendors = [
        VendorRecord(1, TURF, ""),
        VendorRecord(2, WATERWORKS, ""),
        VendorRecord(3, "Other Supply", ""),
    ]
    return refs


class TestHdFowlerVendorPrefs(unittest.TestCase):
    def setUp(self) -> None:
        self._env = patch.dict(
            os.environ,
            {"IDP_HD_FOWLER_VENDOR_NAME": TURF},
            clear=False,
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()

    def test_is_hd_fowler_vendor(self) -> None:
        self.assertTrue(is_hd_fowler_vendor(WATERWORKS))
        self.assertFalse(is_hd_fowler_vendor("Other Supply"))

    def test_exclude_waterworks_from_llm_list(self) -> None:
        self.assertFalse(exclude_vendor_from_llm_list(TURF))
        self.assertTrue(exclude_vendor_from_llm_list(WATERWORKS))

    def test_resolve_waterworks_name_to_turf(self) -> None:
        refs = _refs_with_fowler_vendors()
        rec = resolve_hd_fowler_vendor(
            refs,
            WATERWORKS,
            vendor_raw="H.D. Fowler",
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.vendor_name, TURF)
        self.assertEqual(rec.vendor_id, 1)

    def test_resolve_fowler_raw_to_turf_when_name_null(self) -> None:
        refs = _refs_with_fowler_vendors()
        rec = resolve_hd_fowler_vendor(refs, None, vendor_raw="HD FOWLER SUPPLY")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.vendor_name, hd_fowler_preferred_vendor_name())

    def test_vendors_for_llm_omits_waterworks(self) -> None:
        refs = _refs_with_fowler_vendors()
        names = {v["vendor_name"] for v in refs.vendors_for_llm()}
        self.assertIn(TURF, names)
        self.assertNotIn(WATERWORKS, names)

    def test_import_resolve_prefers_turf_over_waterworks(self) -> None:
        client = MagicMock()
        lookups = LookupService(client)
        lookups._vendors = [
            {
                "VendorID": 1,
                "VendorName": TURF,
                "AccountingVendorID": "",
                "BranchID": 10,
                "Active": True,
            },
            {
                "VendorID": 2,
                "VendorName": WATERWORKS,
                "AccountingVendorID": "",
                "BranchID": 10,
                "Active": True,
            },
        ]
        vid, name = lookups.resolve_vendor_id(WATERWORKS, branch_id=10)
        self.assertEqual(vid, 1)
        self.assertEqual(name, TURF)

    def test_import_ambiguous_fowler_picks_turf(self) -> None:
        client = MagicMock()
        lookups = LookupService(client)
        lookups._vendors = [
            {
                "VendorID": 1,
                "VendorName": TURF,
                "AccountingVendorID": "",
                "BranchID": 10,
                "Active": True,
            },
            {
                "VendorID": 2,
                "VendorName": WATERWORKS,
                "AccountingVendorID": "",
                "BranchID": 10,
                "Active": True,
            },
        ]
        vid, name = lookups.resolve_vendor_id("H.D. Fowler Company", branch_id=10)
        self.assertEqual(vid, 1)
        self.assertIn("Turf", name)


if __name__ == "__main__":
    unittest.main()

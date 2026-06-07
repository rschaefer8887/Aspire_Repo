"""Receipt POST payload: skip consolidation for sod vendor split rows."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_excel import ReceiptLine, ReceiptWorkbook  # noqa: E402
from aspire_lookups import CatalogItem, LookupService, _should_skip_consolidation  # noqa: E402


class TestReceiptConsolidationSkip(unittest.TestCase):
    def test_should_consolidate_for_idaho_sod_duplicates(self) -> None:
        items = [
            {"CatalogItemID": 56, "ItemUnitCost": 1.574},
            {"CatalogItemID": 56, "ItemUnitCost": 1.575},
        ]
        self.assertFalse(_should_skip_consolidation("Idaho Sod", items))

    def test_should_consolidate_for_fowler_duplicates(self) -> None:
        items = [
            {"CatalogItemID": 100, "ItemUnitCost": 1.0},
            {"CatalogItemID": 100, "ItemUnitCost": 2.0},
        ]
        self.assertFalse(_should_skip_consolidation("H.D. Fowler Company {Turf}", items))

    @patch.object(LookupService, "resolve_branch_id", return_value=(2, "Main"))
    @patch.object(LookupService, "resolve_vendor_id", return_value=(136, "Idaho Sod"))
    @patch.object(LookupService, "resolve_catalog_item")
    @patch("aspire_lookups.inventory_location_id", return_value=1)
    def test_build_receipt_post_includes_receipt_note(
        self,
        _mock_loc,
        mock_catalog,
        _mock_vendor,
        _mock_branch,
    ) -> None:
        mock_catalog.return_value = CatalogItem(
            catalog_item_id=56,
            item_name="Bluegrass Sod",
            item_type="Material",
        )
        wb = ReceiptWorkbook(
            path=Path("test.xlsx"),
            invoice_date=date(2026, 5, 1),
            vendor="Idaho Sod",
            branch="Main",
            vendor_invoice_num="TEST-INV",
            lines=[
                ReceiptLine(10, "BSOD", "Bluegrass Sod", 8000.0, 0.557),
            ],
            receipt_note="Variance -0.40 (3-decimal limit).",
        )
        svc = LookupService(MagicMock())
        payload = svc.build_receipt_post(wb)
        self.assertEqual(payload["ReceiptNote"], "Variance -0.40 (3-decimal limit).")
        self.assertEqual(len(payload["ReceiptItems"]), 1)


if __name__ == "__main__":
    unittest.main()

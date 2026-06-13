"""Unit tests for receipt payload (ItemAllocations)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_excel import ReceiptLine, ReceiptWorkbook  # noqa: E402
from aspire_lookups import CatalogItem, LookupService  # noqa: E402


class TestItemAllocations(unittest.TestCase):
    @patch.object(LookupService, "resolve_branch_id", return_value=(2, "Main"))
    @patch.object(LookupService, "resolve_vendor_id", return_value=(99, "Vendor"))
    @patch.object(LookupService, "resolve_catalog_item")
    @patch("aspire_lookups.inventory_location_id", return_value=1)
    def test_build_receipt_post_includes_item_allocations(
        self,
        _mock_loc_id,
        mock_catalog,
        _mock_vendor,
        _mock_branch,
    ) -> None:
        mock_catalog.return_value = CatalogItem(
            catalog_item_id=129,
            item_name="Colorado Spruce",
            item_type="Material",
        )
        wb = ReceiptWorkbook(
            path=Path("test.xlsx"),
            invoice_date=date(2026, 5, 28),
            vendor="Vendor",
            branch="Main",
            vendor_invoice_num="INV-1",
            lines=[
                ReceiptLine(
                    row_number=10,
                    item_code="SKU",
                    item_name="Spruce",
                    quantity=3.0,
                    unit_cost=10.0,
                ),
            ],
        )
        svc = LookupService(MagicMock())
        payload = svc.build_receipt_post(wb)
        item = payload["ReceiptItems"][0]
        self.assertEqual(item["ItemQuantity"], 3.0)
        self.assertEqual(
            item["ItemAllocations"],
            [{"InventoryLocationID": 1, "ItemQuantity": 3.0}],
        )
        self.assertEqual(
            sum(a["ItemQuantity"] for a in item["ItemAllocations"]),
            item["ItemQuantity"],
        )


if __name__ == "__main__":
    unittest.main()

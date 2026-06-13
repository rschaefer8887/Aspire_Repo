"""MD Internal Vendor (347): catalog match by Item Code (column B) only."""

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
from idp_vendor_prefs import (  # noqa: E402
    is_md_internal_vendor,
    is_md_internal_vendor_id,
    md_internal_vendor_name,
)


class TestMdInternalVendorHelpers(unittest.TestCase):
    def test_vendor_name_detector(self) -> None:
        self.assertTrue(is_md_internal_vendor("MD Internal Vendor"))
        self.assertTrue(is_md_internal_vendor(md_internal_vendor_name()))
        self.assertFalse(is_md_internal_vendor("H.D. Fowler Company {Turf}"))

    def test_vendor_id_detector(self) -> None:
        self.assertTrue(is_md_internal_vendor_id(347))
        self.assertFalse(is_md_internal_vendor_id(1))


class TestMdInternalCatalogMatch(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = LookupService(MagicMock())
        self.svc._catalog_by_code = {
            "xq": CatalogItem(1, "Drip Tube", "Material"),
        }
        self.svc._catalog_by_name = {
            "drip tube": CatalogItem(1, "Drip Tube", "Material"),
        }

    def test_code_match_ignores_wrong_name(self) -> None:
        rec = self.svc.resolve_catalog_item_by_code_only(
            "XQ", 10, vendor_label="MD Internal Vendor"
        )
        self.assertEqual(rec.item_name, "Drip Tube")

    def test_missing_code_plain_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.svc.resolve_catalog_item_by_code_only(
                "", 12, vendor_label="MD Internal Vendor"
            )
        msg = str(ctx.exception)
        self.assertIn("Row 12", msg)
        self.assertIn("column B", msg)
        self.assertIn("missing an Item Code", msg)

    def test_unknown_code_plain_error(self) -> None:
        with patch.object(self.svc, "_catalog_from_api_code", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                self.svc.resolve_catalog_item_by_code_only(
                    "NOT-A-REAL-CODE", 15, vendor_label="MD Internal Vendor"
                )
        msg = str(ctx.exception)
        self.assertIn("Row 15", msg)
        self.assertIn("NOT-A-REAL-CODE", msg)
        self.assertIn("not found in Aspire", msg)
        self.assertIn("column C are not used", msg)

    def test_name_only_line_does_not_match_for_md_internal(self) -> None:
        wb = ReceiptWorkbook(
            path=Path("test.xlsx"),
            invoice_date=date(2026, 6, 3),
            vendor="MD Internal Vendor",
            branch="Main",
            vendor_invoice_num="POS-001",
            lines=[
                ReceiptLine(
                    row_number=10,
                    item_code="",
                    item_name="Drip Tube",
                    quantity=1.0,
                    unit_cost=5.0,
                ),
            ],
        )
        with patch.object(
            LookupService, "resolve_branch_id", return_value=(2, "Main")
        ):
            with patch.object(
                LookupService,
                "resolve_vendor_id",
                return_value=(347, "MD Internal Vendor"),
            ):
                with patch("aspire_lookups.inventory_location_id", return_value=1):
                    with self.assertRaises(ValueError) as ctx:
                        self.svc.build_receipt_post(wb)
        self.assertIn("missing an Item Code", str(ctx.exception))

    @patch.object(LookupService, "resolve_branch_id", return_value=(2, "Main"))
    @patch.object(
        LookupService,
        "resolve_vendor_id",
        return_value=(347, "MD Internal Vendor"),
    )
    @patch("aspire_lookups.inventory_location_id", return_value=1)
    def test_build_receipt_uses_code_only_path(
        self, _loc, _vendor, _branch
    ) -> None:
        wb = ReceiptWorkbook(
            path=Path("test.xlsx"),
            invoice_date=date(2026, 6, 3),
            vendor="MD Internal Vendor",
            branch="Main",
            vendor_invoice_num="POS-001",
            lines=[
                ReceiptLine(
                    row_number=10,
                    item_code="XQ",
                    item_name="Wrong POS Label",
                    quantity=2.0,
                    unit_cost=3.5,
                ),
            ],
        )
        payload = self.svc.build_receipt_post(wb)
        self.assertTrue(payload["_resolved"]["catalog_match_code_only"])
        self.assertEqual(payload["ReceiptItems"][0]["ItemName"], "Drip Tube")


if __name__ == "__main__":
    unittest.main()

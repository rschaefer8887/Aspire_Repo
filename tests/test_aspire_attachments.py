"""Tests for invoice PDF naming and resolution (no API)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_attachments import (  # noqa: E402
    aspire_invoice_pdf_filename,
    aspire_pdf_vendor_label,
    resolve_invoice_pdf,
)
from aspire_excel import ReceiptLine, ReceiptWorkbook  # noqa: E402


class TestAspireAttachments(unittest.TestCase):
    def test_aspire_pdf_vendor_label_hd_fowler(self) -> None:
        self.assertEqual(
            aspire_pdf_vendor_label("H.D. Fowler Company {Turf}"),
            "HD Fowler",
        )

    def test_aspire_invoice_pdf_filename(self) -> None:
        name = aspire_invoice_pdf_filename(
            "1314-INV",
            date(2026, 6, 4),
            vendor_name="Idaho Sod",
        )
        self.assertEqual(name, "Aspire-Idaho Sod-1314-INV__06042026.pdf")

    def test_aspire_invoice_pdf_filename_hd_fowler(self) -> None:
        name = aspire_invoice_pdf_filename(
            "I7331698-INV",
            date(2026, 6, 4),
            vendor_name="H.D. Fowler Company {Turf}",
        )
        self.assertEqual(name, "Aspire-HD Fowler-I7331698-INV__06042026.pdf")

    def test_resolve_invoice_pdf_by_expected_name(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pdf = folder / "Aspire-Vendor-999-INV__01022026.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            wb = ReceiptWorkbook(
                path=Path("Vendor_999-INV.xlsx"),
                invoice_date=date(2026, 1, 2),
                vendor="Vendor",
                branch="Branch",
                vendor_invoice_num="999-INV",
                lines=[
                    ReceiptLine(
                        row_number=10,
                        item_code="",
                        item_name="Item",
                        quantity=1.0,
                        unit_cost=1.0,
                    )
                ],
            )
            found = resolve_invoice_pdf(wb, processed_dir=folder)
            self.assertIsNotNone(found)
            self.assertEqual(found.name, pdf.name)

    def test_resolve_invoice_pdf_by_invoice_token(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            pdf = folder / "scanned_invoice_888-INV_extra.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            wb = ReceiptWorkbook(
                path=Path("Some_Vendor_888-INV.xlsx"),
                invoice_date=date(2026, 3, 15),
                vendor="Some Vendor",
                branch="Branch",
                vendor_invoice_num="888-INV",
                lines=[
                    ReceiptLine(
                        row_number=10,
                        item_code="",
                        item_name="Item",
                        quantity=1.0,
                        unit_cost=1.0,
                    )
                ],
            )
            found = resolve_invoice_pdf(wb, processed_dir=folder)
            self.assertEqual(found, pdf)


if __name__ == "__main__":
    unittest.main()

"""Attach invoice PDFs to Aspire purchase receipts."""

from __future__ import annotations

import base64
import os
from datetime import date, datetime
from pathlib import Path

from aspire_common import AspireClient
from aspire_excel import ReceiptWorkbook
from idp_paths import invoices_processed_dir

DEFAULT_ATTACHMENT_TYPE_ID = 20  # Vendor Invoice (GET /AttachmentTypes)


def default_attachment_type_id() -> int:
    raw = os.environ.get("ASPIRE_ATTACHMENT_TYPE_ID", str(DEFAULT_ATTACHMENT_TYPE_ID)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"ASPIRE_ATTACHMENT_TYPE_ID must be an integer, got {raw!r}"
        ) from exc
    if value < 1:
        raise ValueError(f"ASPIRE_ATTACHMENT_TYPE_ID must be >= 1, got {value}")
    return value


def aspire_invoice_pdf_filename(vendor_invoice_num: str, invoice_date: date) -> str:
    """Aspire-{VendorInvoiceNum}__{MMDDYYYY}.pdf"""
    inv = str(vendor_invoice_num).strip()
    if not inv:
        raise ValueError("vendor_invoice_num is empty")
    return f"Aspire-{inv}__{invoice_date.strftime('%m%d%Y')}.pdf"


def move_to_aspire_pdf_name(
    pdf_path: Path,
    vendor_invoice_num: str,
    invoice_date: date,
    *,
    processed_dir: Path | None = None,
) -> Path:
    """Rename/move a PDF in Invoices - Processed to the Aspire attachment naming convention."""
    folder = processed_dir or invoices_processed_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / aspire_invoice_pdf_filename(vendor_invoice_num, invoice_date)
    source = pdf_path.resolve()
    if dest.resolve() == source:
        return dest
    if dest.exists():
        stamp = datetime.now().strftime("%H%M%S")
        dest = folder / f"{dest.stem}_{stamp}{dest.suffix}"
    pdf_path.rename(dest)
    return dest


def resolve_invoice_pdf(
    wb: ReceiptWorkbook,
    *,
    processed_dir: Path | None = None,
) -> Path | None:
    """Find the processed PDF that matches this import workbook."""
    folder = processed_dir or invoices_processed_dir()
    if not folder.is_dir():
        return None

    expected = folder / aspire_invoice_pdf_filename(wb.vendor_invoice_num, wb.invoice_date)
    if expected.is_file():
        return expected

    inv = wb.vendor_invoice_num.strip()
    if inv:
        matches = sorted(folder.glob(f"*{inv}*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]

    stem = wb.path.stem
    if stem.lower().endswith("-imported"):
        stem = stem[: -len("-imported")]
    if "_" in stem:
        tail = stem.rsplit("_", 1)[-1]
        matches = sorted(folder.glob(f"*{tail}*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]

    return None


def receipt_has_attachment(
    client: AspireClient,
    receipt_id: int,
    original_filename: str,
) -> bool:
    rows = client.get(
        "/Attachments",
        params={"$filter": f"ReceiptID eq {int(receipt_id)}", "$top": "50"},
    )
    if not isinstance(rows, list):
        return False
    target = original_filename.strip().casefold()
    for row in rows:
        name = str(row.get("OriginalFileName") or "").strip().casefold()
        if name == target:
            return True
    return False


def upload_receipt_attachment(
    client: AspireClient,
    receipt_id: int,
    pdf_path: Path,
    *,
    display_filename: str,
    type_id: int | None = None,
) -> str:
    """POST /Attachments; returns hosted file URL string."""
    data = pdf_path.read_bytes()
    body = {
        "ObjectId": int(receipt_id),
        "ObjectCode": "Receipt",
        "FileName": display_filename,
        "AttachmentTypeId": type_id if type_id is not None else default_attachment_type_id(),
        "FileData": base64.b64encode(data).decode("ascii"),
    }
    resp = client.post("/Attachments", body, timeout=300)
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        for key in ("Url", "url", "Link", "link"):
            if resp.get(key):
                return str(resp[key])
    return str(resp)


def prompt_upload_pdf(pdf_path: Path, display_filename: str) -> bool:
    while True:
        reply = input(
            f"Upload PDF {display_filename!r} ({pdf_path.name}) to this receipt? [Y/N]: "
        ).strip().upper()
        if reply in ("Y", "YES"):
            return True
        if reply in ("N", "NO"):
            return False
        print("Please enter Y or N.")

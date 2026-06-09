"""
Import a purchase receipt from a fixed-layout Excel file into Aspire.

Excel layout (column B unless noted):
  B1  Invoice date
  B2  Vendor
  B3  Branch
  B5  Invoice number
  B6  Receipt note (optional; sent as ReceiptNote on POST /Receipts)
  (InventoryLocationID is fixed — default 1, see ASPIRE_INVENTORY_LOCATION_ID)
  B10+  Item code (optional if C has name); C10+ item name; D10+ qty; E10+ unit cost
  (stop when B and C are both blank)

Creates via POST /Receipts only (not approved, not received).
After each successful create, optionally uploads the matching PDF from Invoices - Processed
and optionally marks the receipt received (POST /Receipts/Receive; receive date = today).

Usage:
  python scripts/import_purchase_receipt.py --dry-run path/to/file.xlsx
  python scripts/import_purchase_receipt.py path/to/file.xlsx
  python scripts/import_purchase_receipt.py --dry-run
    (processes *.xlsx in ASPIRE_RECEIPTS_READY or ./Receipts - Ready)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aspire_common import (  # noqa: E402
    AspireClient,
    inventory_location_id,
    require_credentials,
)
from aspire_attachments import (  # noqa: E402
    aspire_invoice_pdf_filename,
    prompt_upload_pdf,
    receipt_has_attachment,
    resolve_invoice_pdf,
    upload_receipt_attachment,
)
from aspire_receipts import (  # noqa: E402
    prompt_receive_receipt,
    receipt_is_received,
    receive_date_label,
    receive_receipt,
)
from aspire_excel import read_receipt_workbook  # noqa: E402
from aspire_lookups import LookupService  # noqa: E402
from idp_paths import is_import_excluded_xlsx  # noqa: E402


def _ready_dir() -> Path:
    env = os.environ.get("ASPIRE_RECEIPTS_READY", "").strip()
    if env:
        return Path(env)
    return ROOT / "Receipts - Ready"


def _collect_files(args: argparse.Namespace) -> list[Path]:
    if args.files:
        return [Path(p) for p in args.files]
    folder = _ready_dir()
    if not folder.is_dir():
        print(f"No files given and folder not found: {folder}", file=sys.stderr)
        sys.exit(1)
    files = sorted(
        p for p in folder.glob("*.xlsx") if not is_import_excluded_xlsx(p)
    )
    if not files:
        print(f"No .xlsx files in {folder}", file=sys.stderr)
        sys.exit(1)
    return files


def _strip_internal(payload: dict) -> dict:
    out = {k: v for k, v in payload.items() if k != "_resolved"}
    return out


def _rename_imported(path: Path) -> Path:
    """Rename workbook to {stem}-imported.xlsx after a successful API create."""
    if path.stem.lower().endswith("-imported"):
        return path
    dest = path.with_name(f"{path.stem}-imported{path.suffix}")
    if dest.exists():
        n = 2
        while dest.exists():
            dest = path.with_name(f"{path.stem}-imported_{n}{path.suffix}")
            n += 1
    path.rename(dest)
    return dest


def _maybe_attach_pdf(
    *,
    client: AspireClient,
    receipt_id: int,
    wb,
    dry_run: bool,
    skip_attach_prompt: bool,
) -> None:
    pdf_path = resolve_invoice_pdf(wb)
    display_name = aspire_invoice_pdf_filename(
        wb.vendor_invoice_num,
        wb.invoice_date,
        vendor_name=wb.vendor,
    )
    if pdf_path is None:
        print(f"  PDF: not found in Invoices - Processed (expected {display_name!r})")
        return
    print(f"  PDF: {pdf_path.name}")
    if dry_run:
        print(f"  [dry-run] Would prompt to upload {display_name!r}")
        return
    if receipt_has_attachment(client, receipt_id, display_name):
        print(f"  PDF: skip — receipt already has {display_name!r}")
        return
    if skip_attach_prompt or prompt_upload_pdf(pdf_path, display_name):
        if skip_attach_prompt:
            print(f"  Uploading PDF {display_name!r}...")
        url = upload_receipt_attachment(
            client,
            receipt_id,
            pdf_path,
            display_filename=display_name,
        )
        print(f"  Attached PDF: {display_name!r}")
        if url:
            print(f"  File URL: {url}")
    else:
        print("  PDF: skipped (user declined)")


def _maybe_receive_receipt(
    *,
    client: AspireClient,
    lookups: LookupService,
    receipt_id: int,
    vendor_invoice_num: str,
    dry_run: bool,
    skip_receive_prompt: bool,
) -> None:
    label = receive_date_label()
    if dry_run:
        print(
            f"  [dry-run] Would prompt to receive receipt {receipt_id} "
            f"({vendor_invoice_num!r}, date {label})"
        )
        return

    verified = lookups.verify_receipt(int(receipt_id))
    if receipt_is_received(verified):
        print(
            f"  Receive: skip — already received "
            f"(status={verified.get('ReceiptStatusName')!r}, "
            f"ReceivedDate={verified.get('ReceivedDate')})"
        )
        return

    if skip_receive_prompt or prompt_receive_receipt(
        int(receipt_id),
        vendor_invoice_num=vendor_invoice_num,
    ):
        if skip_receive_prompt:
            print(f"  Receiving receipt {receipt_id} (date {label})...")
        receive_receipt(client, int(receipt_id))
        verified = lookups.verify_receipt(int(receipt_id))
        print(
            f"  Received: status={verified.get('ReceiptStatusName')!r} | "
            f"ReceivedDate={verified.get('ReceivedDate')}"
        )
    else:
        print("  Receive: skipped (user declined)")


def process_file(
    path: Path,
    *,
    client: AspireClient,
    lookups: LookupService,
    dry_run: bool,
    force: bool,
    skip_duplicate: bool,
    skip_attach_prompt: bool,
    skip_receive_prompt: bool,
) -> bool:
    print(f"\n=== {path.name} ===")
    wb = read_receipt_workbook(path)
    loc_id = inventory_location_id()
    print(
        f"  Header: date={wb.invoice_date} vendor={wb.vendor!r} branch={wb.branch!r} "
        f"invoice#={wb.vendor_invoice_num!r}"
    )
    print(f"  Inventory location: ID {loc_id} (fixed)")
    print(f"  Lines: {len(wb.lines)} item(s)")

    payload = lookups.build_receipt_post(wb)
    api_items = payload["ReceiptItems"]
    resolved = payload.pop("_resolved", {})
    excel_lines = resolved.get("excel_line_count", len(wb.lines))
    if resolved.get("consolidation_skipped"):
        print(
            f"  Posting {len(api_items)} receipt line(s) without merging duplicate "
            f"catalog IDs (sod split; {excel_lines} Excel row(s))"
        )
    elif len(api_items) != len(wb.lines):
        print(
            f"  Consolidated to {len(api_items)} receipt line(s) "
            f"(duplicate catalog items merged)"
        )
    print(
        f"  Resolved: Branch {resolved.get('branch')} (ID {resolved.get('branch_id')}), "
        f"Vendor {resolved.get('vendor')} (ID {resolved.get('vendor_id')}), "
        f"InventoryLocationID {resolved.get('inventory_location_id')} (fixed)"
    )

    vendor_id = int(payload["VendorID"])
    if skip_duplicate and not force:
        existing = lookups.find_existing_receipt(vendor_id, wb.vendor_invoice_num)
        if existing:
            rid = existing.get("ReceiptID")
            print(
                f"  Skip: receipt already exists (ReceiptID={rid}, "
                f"status={existing.get('ReceiptStatusName')!r}). Use --force to create anyway."
            )
            return True

    api_body = _strip_internal(payload)
    if dry_run:
        print("  [dry-run] POST /Receipts body:")
        print(json.dumps(api_body, indent=2))
        _maybe_attach_pdf(
            client=client,
            receipt_id=0,
            wb=wb,
            dry_run=True,
            skip_attach_prompt=skip_attach_prompt,
        )
        _maybe_receive_receipt(
            client=client,
            lookups=lookups,
            receipt_id=0,
            vendor_invoice_num=wb.vendor_invoice_num,
            dry_run=True,
            skip_receive_prompt=skip_receive_prompt,
        )
        return True

    try:
        resp = client.post("/Receipts", api_body)
    except RuntimeError as exc:
        if "Unique vendor invoice number" in str(exc):
            raise RuntimeError(
                f"{exc} — delete or void the existing receipt for vendor "
                f"{vendor_id!r} and invoice {wb.vendor_invoice_num!r} in Aspire, "
                "then run import again. (--force only skips the local duplicate check.)"
            ) from exc
        raise
    receipt_id = resp.get("ReceiptID")
    if receipt_id is None:
        print(f"  Warning: unexpected response: {resp}")
    else:
        print(f"  Created ReceiptID={receipt_id}")
        verified = lookups.verify_receipt(int(receipt_id))
        print(
            f"  Status: {verified.get('ReceiptStatusName')!r} | "
            f"ApprovedDate={verified.get('ApprovedDate')} | "
            f"ReceivedDate={verified.get('ReceivedDate')}"
        )
        if verified.get("ApprovedDate") or verified.get("ReceivedDate"):
            print(
                "  Warning: receipt has approval/receive timestamps; "
                "expected both null for saved-not-approved workflow.",
                file=sys.stderr,
            )
        renamed = _rename_imported(path)
        print(f"  Renamed: {renamed.name}")
        _maybe_attach_pdf(
            client=client,
            receipt_id=int(receipt_id),
            wb=wb,
            dry_run=False,
            skip_attach_prompt=skip_attach_prompt,
        )
        _maybe_receive_receipt(
            client=client,
            lookups=lookups,
            receipt_id=int(receipt_id),
            vendor_invoice_num=wb.vendor_invoice_num,
            dry_run=False,
            skip_receive_prompt=skip_receive_prompt,
        )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Aspire purchase receipts from Excel")
    parser.add_argument(
        "files",
        nargs="*",
        help="Excel file(s). If omitted, scans ASPIRE_RECEIPTS_READY or 'Receipts - Ready'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and resolve IDs; print JSON without POST /Receipts",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create even if a receipt with same vendor + invoice # exists",
    )
    parser.add_argument(
        "--no-skip-duplicate",
        action="store_true",
        help="Do not check for existing receipts before create",
    )
    parser.add_argument(
        "--yes-attach",
        action="store_true",
        help="Upload matching PDF without prompting (default: prompt Y/N per receipt)",
    )
    parser.add_argument(
        "--yes-receive",
        action="store_true",
        help="Mark receipt received without prompting (default: prompt Y/N per receipt)",
    )
    args = parser.parse_args()

    paths = _collect_files(args)
    client_id, secret = require_credentials()
    client = AspireClient(client_id, secret)
    client.authenticate()
    lookups = LookupService(client)

    ok = True
    for path in paths:
        try:
            process_file(
                path,
                client=client,
                lookups=lookups,
                dry_run=args.dry_run,
                force=args.force,
                skip_duplicate=not args.no_skip_duplicate,
                skip_attach_prompt=args.yes_attach,
                skip_receive_prompt=args.yes_receive,
            )
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

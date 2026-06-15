"""
Backfill exports/HD Fowler Item Match Log.xlsx from archived Fowler PDFs.

Extracts with OpenAI and logs line → catalog matches only (no Excel import, no Aspire).
Requires Microsoft Excel (xlwings). Close the match log workbook before running.

Usage:
  py scripts/backfill_fowler_match_log.py
  py scripts/backfill_fowler_match_log.py --folder "Receipts - Ready/Invoices - Processed/Complete"
  py scripts/backfill_fowler_match_log.py --dry-run
  py scripts/backfill_fowler_match_log.py --force   (re-log invoices already in workbook)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from idp_match_log import (  # noqa: E402
    append_hd_fowler_match_log_from_extraction,
    hd_fowler_match_log_path,
    invoice_numbers_in_log,
    pdf_name_is_hd_fowler,
    should_log_hd_fowler,
)
from idp_openai import extract_invoice_from_pdf, format_invoice_number  # noqa: E402
from idp_paths import invoices_processed_dir  # noqa: E402
from idp_reference import ReferenceData  # noqa: E402


def _default_folder() -> Path:
    return invoices_processed_dir()


def _collect_pdfs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    pdfs = sorted(p for p in folder.glob("*.pdf") if pdf_name_is_hd_fowler(p))
    if not pdfs:
        raise FileNotFoundError(f"No HD Fowler PDFs in {folder}")
    return pdfs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill HD Fowler Item Match Log from archived PDFs"
    )
    parser.add_argument(
        "--folder",
        type=Path,
        default=_default_folder(),
        help="Folder containing Fowler PDFs (default: .../Invoices - Processed/Complete)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List PDFs that would be processed; no API calls",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract and append even if invoice # is already in the log",
    )
    args = parser.parse_args()

    pdfs = _collect_pdfs(args.folder)
    existing = invoice_numbers_in_log()
    print(f"Found {len(pdfs)} HD Fowler PDF(s) in {args.folder}")
    print(f"Match log: {hd_fowler_match_log_path()}")
    if existing and not args.force:
        print(f"Skipping {len(existing)} invoice number(s) already in log (use --force to re-run)")

    if args.dry_run:
        for pdf in pdfs:
            inv_guess = pdf.stem
            print(f"  [dry-run] Would extract: {pdf.name}")
        return

    from idp_openai import require_openai_key
    from openai import OpenAI

    refs = ReferenceData()
    refs.load()
    client = OpenAI(api_key=require_openai_key())

    ok = 0
    skipped = 0
    for pdf in pdfs:
        print(f"\n=== {pdf.name} ===")
        try:
            result = extract_invoice_from_pdf(pdf, refs, client=client)
        except Exception as exc:
            print(f"  ERROR: {exc}", file=sys.stderr)
            continue

        if not should_log_hd_fowler(result.vendor_name, result.vendor_raw):
            print(
                f"  Skip: vendor {result.vendor_name or result.vendor_raw!r} "
                "is not HD Fowler"
            )
            skipped += 1
            continue

        inv_display = format_invoice_number(result.invoice_number_raw)
        if inv_display in existing and not args.force:
            print(f"  Skip: {inv_display!r} already in match log")
            skipped += 1
            continue

        n = append_hd_fowler_match_log_from_extraction(
            result,
            pdf_name=pdf.name,
        )
        print(f"  Logged {n} line(s) for invoice {inv_display!r}")
        existing.add(inv_display)
        ok += 1

    print(f"\nDone: {ok} invoice(s) logged, {skipped} skipped.")


if __name__ == "__main__":
    main()

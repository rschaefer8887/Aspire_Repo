"""Append-only HD Fowler invoice line → catalog match log (CSV)."""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from idp_openai import ExtractionResult, LineMatch, format_invoice_number
from idp_paths import ROOT
from idp_vendor_prefs import is_hd_fowler_vendor

MATCH_LOG_FILENAME = "HD Fowler Item Match Log.csv"

FIELDNAMES = [
    "processed_at",
    "source",
    "invoice_number",
    "invoice_date",
    "vendor_name",
    "pdf_name",
    "description_raw",
    "supplier_item_code",
    "uom_raw",
    "catalog_item_code",
    "catalog_item_name",
    "confidence",
    "match_note",
]


def hd_fowler_match_log_path() -> Path:
    return ROOT / "exports" / MATCH_LOG_FILENAME


def should_log_hd_fowler(vendor_name: str | None, vendor_raw: str | None) -> bool:
    return is_hd_fowler_vendor(vendor_name) or is_hd_fowler_vendor(vendor_raw)


def _row_from_line(
    line: LineMatch,
    *,
    processed_at: str,
    source: str,
    invoice_number: str,
    invoice_date: date | None,
    vendor_name: str,
    pdf_name: str,
) -> dict[str, str]:
    return {
        "processed_at": processed_at,
        "source": source,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date.isoformat() if invoice_date else "",
        "vendor_name": vendor_name,
        "pdf_name": pdf_name,
        "description_raw": line.description_raw,
        "supplier_item_code": line.supplier_item_code or "",
        "uom_raw": line.uom_raw or "",
        "catalog_item_code": line.item_code or "",
        "catalog_item_name": line.item_name or "",
        "confidence": f"{line.confidence:.4f}",
        "match_note": line.rationale or "",
    }


def invoice_numbers_in_log(path: Path | None = None) -> set[str]:
    """Invoice numbers already present in the match log."""
    log_path = path or hd_fowler_match_log_path()
    if not log_path.is_file():
        return set()
    found: set[str] = set()
    with log_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            inv = str(row.get("invoice_number") or "").strip()
            if inv:
                found.add(inv)
    return found


def append_hd_fowler_match_log_from_extraction(
    result: ExtractionResult,
    *,
    pdf_name: str,
    source: str,
    processed_at: datetime | None = None,
) -> int:
    """
    Append Fowler invoice lines to the match log. No-op for non-Fowler vendors.
    Returns number of rows written.
    """
    if not should_log_hd_fowler(result.vendor_name, result.vendor_raw):
        return 0
    if not result.lines:
        return 0

    log_path = hd_fowler_match_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = (processed_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    inv_display = format_invoice_number(result.invoice_number_raw)
    vendor = result.vendor_name or result.vendor_raw or ""

    rows = [
        _row_from_line(
            line,
            processed_at=stamp,
            source=source,
            invoice_number=inv_display,
            invoice_date=result.invoice_date,
            vendor_name=vendor,
            pdf_name=pdf_name,
        )
        for line in result.lines
    ]

    write_header = not log_path.is_file() or log_path.stat().st_size == 0
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def pdf_name_is_hd_fowler(pdf_path: Path) -> bool:
    """True when PDF filename indicates HD Fowler (for backfill folder scans)."""
    name = pdf_path.name.lower().replace("-", " ")
    return "hd fowler" in name or "h d fowler" in name

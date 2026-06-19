"""Append-only HD Fowler invoice line → catalog match log (Excel via xlwings)."""

from __future__ import annotations

import os
import shutil
from datetime import date, datetime
from pathlib import Path

import xlwings as xw

from idp_fowler_freight import is_fowler_inbound_freight_line
from idp_openai import ExtractionResult, LineMatch, format_invoice_number
from idp_paths import ROOT
from idp_vendor_prefs import is_hd_fowler_vendor

MATCH_LOG_FILENAME = "HD Fowler Item Match Log.xlsx"
MATCH_LOG_TEMPLATE_FILENAME = "HD Fowler Item Match Log.template.xlsx"
DEFAULT_SHEET_NAME = "HD Fowler Item Match Log"
HEADER_ROW = 1

FIELDNAMES = [
    "processed_at",
    "invoice_number",
    "invoice_date",
    "vendor_name",
    "pdf_name",
    "description_raw",
    "uom_raw",
    "catalog_item_code",
    "catalog_item_name",
    "confidence",
    "match_note",
]


def match_log_sheet_name() -> str:
    return os.environ.get("IDP_MATCH_LOG_SHEET", DEFAULT_SHEET_NAME).strip() or DEFAULT_SHEET_NAME


def hd_fowler_match_log_path() -> Path:
    return ROOT / "exports" / MATCH_LOG_FILENAME


def hd_fowler_match_log_template_path() -> Path:
    return ROOT / "exports" / MATCH_LOG_TEMPLATE_FILENAME


def should_log_hd_fowler(vendor_name: str | None, vendor_raw: str | None) -> bool:
    return is_hd_fowler_vendor(vendor_name) or is_hd_fowler_vendor(vendor_raw)


def _row_from_line(
    line: LineMatch,
    *,
    processed_at: str,
    invoice_number: str,
    invoice_date: date | None,
    vendor_name: str,
    pdf_name: str,
) -> dict[str, str]:
    return {
        "processed_at": processed_at,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date.isoformat() if invoice_date else "",
        "vendor_name": vendor_name,
        "pdf_name": pdf_name,
        "description_raw": line.description_raw,
        "uom_raw": line.uom_raw or "",
        "catalog_item_code": line.item_code or "",
        "catalog_item_name": line.item_name or "",
        "confidence": f"{line.confidence:.4f}",
        "match_note": line.rationale or "",
    }


def rows_to_values(rows: list[dict[str, str]]) -> list[list[str]]:
    """Map row dicts to a 2D list in FIELDNAMES column order."""
    return [[row.get(name, "") for name in FIELDNAMES] for row in rows]


def _ensure_log_workbook(log_path: Path) -> None:
    """Create the log file from template when missing."""
    if log_path.is_file():
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    template = hd_fowler_match_log_template_path()
    if template.is_file():
        shutil.copy2(template, log_path)
        return
    raise FileNotFoundError(
        f"Match log not found: {log_path}\n"
        f"Create a formatted workbook there (row {HEADER_ROW} = headers), "
        f"or place a template at {template}."
    )


def _last_used_row(ws: xw.main.Sheet) -> int:
    """Last row with data in column A (header row counts when present)."""
    return ws.range(f"A{ws.cells.last_cell.row}").end("up").row


def _header_values(ws: xw.main.Sheet) -> list[str]:
    raw = ws.range((HEADER_ROW, 1), (HEADER_ROW, len(FIELDNAMES))).value
    if raw is None:
        return []
    if isinstance(raw, list):
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        return [str(v).strip() if v is not None else "" for v in raw]
    return [str(raw).strip()]


def _invoice_number_column(headers: list[str]) -> int:
    try:
        return headers.index("invoice_number") + 1
    except ValueError:
        return FIELDNAMES.index("invoice_number") + 1


def _normalize_column_values(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [str(raw).strip()] if str(raw).strip() else []
    if raw and isinstance(raw[0], list):
        raw = [row[0] for row in raw]
    return [str(v).strip() for v in raw if v is not None and str(v).strip()]


def _read_invoice_numbers_from_sheet(ws: xw.main.Sheet) -> set[str]:
    headers = _header_values(ws)
    inv_col = _invoice_number_column(headers)
    last_row = _last_used_row(ws)
    if last_row <= HEADER_ROW:
        return set()
    raw = ws.range((HEADER_ROW + 1, inv_col), (last_row, inv_col)).value
    return set(_normalize_column_values(raw))


def _append_values_with_xlwings(
    log_path: Path,
    values: list[list[str]],
    *,
    sheet_name: str,
) -> None:
    if not values:
        return
    _ensure_log_workbook(log_path)
    with xw.App(visible=False) as app:
        app.display_alerts = False
        app.screen_updating = False
        wb = app.books.open(str(log_path))
        try:
            try:
                ws = wb.sheets[sheet_name]
            except Exception as exc:
                names = [s.name for s in wb.sheets]
                raise ValueError(
                    f"Sheet {sheet_name!r} not found in {log_path.name}. "
                    f"Available sheets: {names}"
                ) from exc

            last_row = _last_used_row(ws)
            start_row = HEADER_ROW + 1 if last_row <= HEADER_ROW else last_row + 1
            ws.range((start_row, 1)).value = values
            wb.save()
        finally:
            wb.close()


def _read_invoice_numbers_with_xlwings(log_path: Path, *, sheet_name: str) -> set[str]:
    if not log_path.is_file():
        return set()
    with xw.App(visible=False) as app:
        app.display_alerts = False
        app.screen_updating = False
        wb = app.books.open(str(log_path))
        try:
            ws = wb.sheets[sheet_name]
            return _read_invoice_numbers_from_sheet(ws)
        finally:
            wb.close()


def invoice_numbers_in_log(path: Path | None = None) -> set[str]:
    """Invoice numbers already present in the match log."""
    log_path = path or hd_fowler_match_log_path()
    return _read_invoice_numbers_with_xlwings(log_path, sheet_name=match_log_sheet_name())


def append_hd_fowler_match_log_from_extraction(
    result: ExtractionResult,
    *,
    pdf_name: str,
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
    stamp = (processed_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    inv_display = format_invoice_number(result.invoice_number_raw)
    vendor = result.vendor_name or result.vendor_raw or ""

    rows = [
        _row_from_line(
            line,
            processed_at=stamp,
            invoice_number=inv_display,
            invoice_date=result.invoice_date,
            vendor_name=vendor,
            pdf_name=pdf_name,
        )
        for line in result.lines
        if not is_fowler_inbound_freight_line(line.description_raw)
    ]
    if not rows:
        return 0

    _append_values_with_xlwings(
        log_path,
        rows_to_values(rows),
        sheet_name=match_log_sheet_name(),
    )
    return len(rows)


def pdf_name_is_hd_fowler(pdf_path: Path) -> bool:
    """True when PDF filename indicates HD Fowler (for backfill folder scans)."""
    name = pdf_path.name.lower().replace("-", " ")
    return "hd fowler" in name or "h d fowler" in name

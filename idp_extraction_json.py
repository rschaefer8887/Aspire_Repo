"""Save post-match extraction audit JSON for troubleshooting (OpenAI + catalog match)."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from idp_excel import extraction_to_lines, output_filename
from idp_openai import ExtractionResult, LineMatch, format_invoice_number
from idp_paths import review_extraction_json_dir
from idp_vendor_profiles import vendor_profile_for


def _json_default(obj: Any) -> Any:
    if isinstance(obj, date):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _line_to_dict(line: LineMatch) -> dict[str, Any]:
    return {
        "description_raw": line.description_raw,
        "quantity": line.quantity,
        "unit_price": line.unit_price,
        "uom_raw": line.uom_raw,
        "supplier_item_code": line.supplier_item_code,
        "item_code": line.item_code,
        "item_name": line.item_name,
        "item_alternate_name": line.item_alternate_name,
        "confidence": line.confidence,
        "rationale": line.rationale,
    }


def build_extraction_audit(
    result: ExtractionResult,
    *,
    pdf_name: str,
    openai_model: str,
    flags: list[str],
) -> dict[str, Any]:
    """Full audit payload: OpenAI raw, matched lines, Aspire import qty after conversions."""
    profile = vendor_profile_for(result.vendor_name, result.vendor_raw)
    aspire_lines = extraction_to_lines(result, profile=profile)
    return {
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_name": pdf_name,
        "openai_model": openai_model,
        "review_flags": flags,
        "invoice_date": result.invoice_date.isoformat() if result.invoice_date else None,
        "vendor_raw": result.vendor_raw,
        "vendor_name": result.vendor_name,
        "vendor_id": result.vendor_id,
        "vendor_confidence": result.vendor_confidence,
        "vendor_rationale": result.vendor_rationale,
        "invoice_number_raw": result.invoice_number_raw,
        "invoice_number": format_invoice_number(result.invoice_number_raw),
        "invoice_total": result.invoice_total,
        "receipt_note": result.receipt_note,
        "openai_raw": result.openai_raw,
        "lines": [_line_to_dict(ln) for ln in result.lines],
        "aspire_import_lines": [
            {
                "item_code": ln.item_code,
                "item_name": ln.item_name,
                "quantity": ln.quantity,
                "unit_cost": ln.unit_cost,
            }
            for ln in aspire_lines
        ],
    }


def extraction_json_path(
    result: ExtractionResult,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Target JSON path (same stem as import workbook)."""
    folder = output_dir or review_extraction_json_dir()
    vendor = result.vendor_name or result.vendor_raw or "Unknown_Vendor"
    inv = format_invoice_number(result.invoice_number_raw)
    base = output_filename(vendor, inv).replace(".xlsx", ".json")
    path = folder / base
    if not path.exists():
        return path
    stem = path.stem
    n = 2
    while path.exists():
        path = folder / f"{stem}_{n}.json"
        n += 1
    return path


def save_extraction_json(
    result: ExtractionResult,
    *,
    pdf_name: str,
    openai_model: str,
    flags: list[str],
    output_dir: Path | None = None,
) -> Path:
    """Write audit JSON; returns path written."""
    folder = output_dir or review_extraction_json_dir()
    folder.mkdir(parents=True, exist_ok=True)
    payload = build_extraction_audit(
        result,
        pdf_name=pdf_name,
        openai_model=openai_model,
        flags=flags,
    )
    path = extraction_json_path(result, output_dir=folder)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    return path

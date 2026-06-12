"""OpenAI vision extraction with structured outputs for invoice IDP."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

from openai import OpenAI

from idp_paths import confidence_threshold
from idp_review_triggers import (
    is_pinch_clamp_tool_ct108_line,
    is_review_tool_line,
    pinch_clamp_tool_ct108_review_flag,
    review_tool_flag,
)
from idp_sod import transform_idaho_sod_extraction
from idp_roll_conversion import roll_line_missing_feet_per_roll
from idp_reference import (
    ReferenceData,
    _SIZE_STRICT_PRODUCT_HINTS,
    _product_hint,
)


@dataclass
class LineMatch:
    description_raw: str
    quantity: float
    unit_price: float
    uom_raw: str = ""
    item_code: str | None = None
    item_name: str | None = None
    item_alternate_name: str | None = None
    supplier_item_code: str | None = None
    confidence: float = 0.0
    rationale: str = ""


@dataclass
class ExtractionResult:
    invoice_date: date | None
    vendor_raw: str
    vendor_name: str | None
    vendor_id: int | None
    vendor_confidence: float
    vendor_rationale: str
    invoice_number_raw: str
    invoice_total: float | None = None
    lines: list[LineMatch] = field(default_factory=list)
    receipt_note: str | None = None
    sod_split: object | None = field(default=None, repr=False)


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_date": {
            "type": ["string", "null"],
            "description": "ISO date YYYY-MM-DD from invoice",
        },
        "vendor_raw": {"type": "string", "description": "Vendor name as printed on invoice"},
        "vendor_name": {
            "type": ["string", "null"],
            "description": "Must exactly match one vendor_name from the provided vendor list, or null",
        },
        "vendor_confidence": {"type": "number"},
        "vendor_rationale": {"type": "string"},
        "invoice_number_raw": {"type": "string"},
        "invoice_total": {
            "type": ["number", "null"],
            "description": "Grand total amount due on the invoice (final total including tax)",
        },
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description_raw": {
                        "type": "string",
                        "description": (
                            "Line description exactly as printed; preserve hyphenated "
                            "fractional sizes (e.g. 1-1/2 not 1/2 when that is what is printed)"
                        ),
                    },
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "uom_raw": {
                        "type": "string",
                        "description": (
                            "Unit of measure as printed on the invoice line "
                            "(e.g. RL for roll, EA, FT, BX)"
                        ),
                    },
                    "supplier_item_code": {
                        "type": ["string", "null"],
                        "description": "Part/catalog number printed on the invoice line, if any",
                    },
                    "read_confidence": {
                        "type": "number",
                        "description": "Confidence that qty, price, and description were read correctly",
                    },
                    "rationale": {"type": "string"},
                },
                "required": [
                    "description_raw",
                    "quantity",
                    "unit_price",
                    "uom_raw",
                    "supplier_item_code",
                    "read_confidence",
                    "rationale",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "invoice_date",
        "vendor_raw",
        "vendor_name",
        "vendor_confidence",
        "vendor_rationale",
        "invoice_number_raw",
        "invoice_total",
        "lines",
    ],
    "additionalProperties": False,
}


def require_openai_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Set OPENAI_API_KEY in .env")
    return key


def pdf_render_scale() -> float:
    """PDF page rasterization scale for vision OCR (default 3 for clearer fractions)."""
    raw = os.environ.get("IDP_PDF_RENDER_SCALE", "3").strip()
    try:
        scale = float(raw)
    except ValueError:
        scale = 3.0
    return max(1.0, min(scale, 4.0))


def pdf_to_base64_images(pdf_path: Path, max_pages: int = 10) -> list[str]:
    if fitz is None:
        raise RuntimeError("Install pymupdf: pip install pymupdf")
    scale = pdf_render_scale()
    doc = fitz.open(pdf_path)
    images: list[str] = []
    try:
        matrix = fitz.Matrix(scale, scale)
        for i in range(min(len(doc), max_pages)):
            page = doc[i]
            pix = page.get_pixmap(matrix=matrix)
            images.append(base64.b64encode(pix.tobytes("png")).decode("ascii"))
    finally:
        doc.close()
    return images


# Common vision misreads of Fowler-style mixed fractions at the start of a line.
_FRACTION_OCR_FIXES: tuple[tuple[str, str], ...] = (
    ("1/2", "1-1/2"),
    ("1/4", "1-1/4"),
    ("1/8", "1-1/8"),
)

_LEADING_SIMPLE_FRACTION_RE = re.compile(
    r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*\"",
    re.IGNORECASE,
)


def _hyphenated_fraction_present(desc: str, hyphenated: str) -> bool:
    """True if desc already contains the mixed fraction (e.g. 1-1/2)."""
    parts = hyphenated.split("-", 1)
    if len(parts) != 2:
        return False
    whole, frac = parts[0], parts[1]
    if re.search(rf"\b{re.escape(hyphenated)}\b", desc, re.IGNORECASE):
        return True
    if re.search(
        rf"\b{re.escape(whole)}\s+{re.escape(frac)}\s*\"",
        desc,
        re.IGNORECASE,
    ):
        return True
    return False


def maybe_correct_hyphenated_fraction_size(
    desc: str,
    refs: ReferenceData,
    supplier_item_code: str | None = None,
    *,
    min_match_conf: float = 0.85,
) -> tuple[str, str]:
    """
    When OCR drops the leading whole number (1/2 vs 1-1/2), retry matching after
    fixing the leading size if the catalog strongly prefers the hyphenated form.
    """
    desc = desc.strip()
    if not desc:
        return desc, ""
    hint = _product_hint(desc)
    if not hint or hint not in _SIZE_STRICT_PRODUCT_HINTS:
        return desc, ""

    m = _LEADING_SIMPLE_FRACTION_RE.match(desc)
    if not m:
        return desc, ""
    lead = f"{m.group(1)}/{m.group(2)}"

    for wrong, right in _FRACTION_OCR_FIXES:
        if lead != wrong:
            continue
        if _hyphenated_fraction_present(desc, right):
            return desc, ""
        candidate = _LEADING_SIMPLE_FRACTION_RE.sub(
            f'{right}"',
            desc,
            count=1,
        )
        if candidate == desc:
            return desc, ""
        rec_fix, conf_fix, _ = refs.match_line(candidate, supplier_item_code)
        if not rec_fix or conf_fix < min_match_conf:
            return desc, ""
        rec_orig, conf_orig, _ = refs.match_line(desc, supplier_item_code)
        note = f"Corrected OCR size {wrong}→{right} in description"
        if conf_fix > conf_orig or conf_orig < min_match_conf:
            return candidate, note
        # Both SKUs match confidently; prefer the hyphenated catalog row.
        if (
            rec_orig
            and rec_fix.item_name != rec_orig.item_name
            and right in (rec_fix.item_name or "")
            and wrong in (rec_orig.item_name or "")
        ):
            return candidate, note
    return desc, ""


def _parse_total(value) -> float | None:
    if value is None:
        return None
    try:
        total = float(value)
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return date.fromisoformat(s)
    return None


def format_invoice_number(raw: str) -> str:
    raw = str(raw).strip()
    if not raw:
        return "UNKNOWN-INV"
    upper = raw.upper()
    if upper.endswith("-INV"):
        return raw
    return f"{raw}-INV"


def extract_invoice_from_pdf(
    pdf_path: Path,
    refs: ReferenceData,
    *,
    client: OpenAI | None = None,
) -> ExtractionResult:
    if client is None:
        client = OpenAI(api_key=require_openai_key())
    model = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
    images = pdf_to_base64_images(pdf_path)
    if not images:
        raise ValueError(f"No pages in PDF: {pdf_path}")

    vendor_list = json.dumps(refs.vendors_for_llm(), ensure_ascii=False)

    system = (
        "You extract purchase invoice data from images. "
        "For vendor_name you MUST pick exactly one vendor_name string from the vendor list "
        "or set vendor_name to null if no confident match. "
        "For H.D. Fowler / HD Fowler invoices always use the Fowler {Turf} vendor from the list, "
        "never Waterworks or other Fowler variants. "
        "For each line, copy description_raw, uom_raw (unit of measure column, e.g. RL, EA, FT), "
        "and supplier_item_code as printed on the invoice. "
        "Preserve hyphenated fractional inch sizes exactly as printed "
        "(e.g. 1-1/2 or 1-1/4, not 1/2 or 1/4 when the invoice shows the hyphenated form). "
        "Do not invent catalog codes. unit_price is the pre-tax unit price. "
        "invoice_total is the final invoice grand total (amount due, including tax). "
        "For Idaho Sod invoices: invoice_total is the 'Total Due' amount (bottom right). "
        "The sod material line quantity is square feet (the number before the grass type, "
        "e.g. Kentucky Bluegrass or RTF). Include delivery, pallet deposit, and fuel "
        "surcharge as separate lines if printed — they are included in Total Due for pricing. "
        "Kentucky on the invoice means Kentucky Bluegrass; RTF means Rhizomatous Tall Fescue. "
        "read_confidence is 0.0 to 1.0 for OCR/extraction quality only."
    )
    user_content: list[dict] = [
        {
            "type": "text",
            "text": f"VENDOR LIST (use exact vendor_name):\n{vendor_list}",
        }
    ]
    for b64 in images:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            }
        )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "invoice_extraction",
                "strict": True,
                "schema": EXTRACTION_SCHEMA,
            },
        },
        temperature=0.1,
    )
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("OpenAI returned empty content")
    data = json.loads(raw)

    vendor_raw = str(data.get("vendor_raw") or "")
    vendor_name = data.get("vendor_name")
    vendor_rec = refs.resolve_vendor_name(vendor_name, vendor_raw=vendor_raw or None)
    vendor_id = vendor_rec.vendor_id if vendor_rec else None
    if vendor_name and not vendor_rec:
        vendor_name = None

    lines: list[LineMatch] = []
    for row in data.get("lines") or []:
        qty = float(row.get("quantity") or 0)
        price = float(row.get("unit_price") or 0)
        if qty <= 0:
            continue
        desc = str(row.get("description_raw") or "")
        uom_raw = str(row.get("uom_raw") or "").strip()
        supplier_code = row.get("supplier_item_code") or None
        if supplier_code is not None:
            supplier_code = str(supplier_code).strip() or None
        desc, size_fix_note = maybe_correct_hyphenated_fraction_size(
            desc, refs, supplier_code
        )
        read_conf = float(row.get("read_confidence") or 0)
        inv, match_conf, match_note = refs.match_line(
            desc,
            supplier_code,
            vendor_name=vendor_rec.vendor_name if vendor_rec else vendor_name,
            vendor_raw=vendor_raw or None,
        )
        code = inv.item_code if inv else None
        name = inv.item_name if inv else None
        conf = min(read_conf, match_conf) if inv else 0.0
        rationale = str(row.get("rationale") or "")
        if size_fix_note:
            rationale = f"{rationale}; {size_fix_note}".strip("; ")
        rationale = f"{rationale}; {match_note}".strip("; ")
        lines.append(
            LineMatch(
                description_raw=desc,
                quantity=qty,
                unit_price=price,
                uom_raw=uom_raw,
                item_code=code or None,
                item_name=name,
                item_alternate_name=None,
                supplier_item_code=supplier_code,
                confidence=conf,
                rationale=rationale,
            )
        )

    result = ExtractionResult(
        invoice_date=_parse_date(data.get("invoice_date")),
        vendor_raw=vendor_raw,
        vendor_name=vendor_rec.vendor_name if vendor_rec else vendor_name,
        vendor_id=vendor_id,
        vendor_confidence=float(data.get("vendor_confidence") or 0),
        vendor_rationale=str(data.get("vendor_rationale") or ""),
        invoice_number_raw=str(data.get("invoice_number_raw") or ""),
        invoice_total=_parse_total(data.get("invoice_total")),
        lines=lines,
    )
    return transform_idaho_sod_extraction(result, refs)


def collect_review_flags(result: ExtractionResult, threshold: float | None = None) -> list[str]:
    th = threshold if threshold is not None else confidence_threshold()
    flags: list[str] = []
    if not result.vendor_name or result.vendor_confidence < th:
        flags.append(
            f"LOW CONFIDENCE VENDOR ({result.vendor_confidence:.2f}):\n"
            f"  Raw: {result.vendor_raw!r}\n"
            f"  Matched: {result.vendor_name!r}"
        )
    if not result.invoice_date:
        flags.append("MISSING INVOICE DATE")
    if result.invoice_total is None:
        flags.append("MISSING INVOICE TOTAL (column F cannot be reconciled)")
    for i, line in enumerate(result.lines):
        if line.confidence < th or (not line.item_code and not line.item_name):
            flags.append(
                f"LOW CONFIDENCE LINE ({line.confidence:.2f}) row {10 + i}:\n"
                f"  Raw: {line.description_raw!r}\n"
                f"  Matched: ItemCode={line.item_code!r} ItemName={line.item_name!r}"
            )
        if roll_line_missing_feet_per_roll(
            line.description_raw,
            line.uom_raw,
            line.item_name,
            item_code=line.item_code,
        ):
            flags.append(
                f"ROLL LINE MISSING LENGTH row {10 + i}:\n"
                f"  UoM: {line.uom_raw!r}\n"
                f"  Raw: {line.description_raw!r}\n"
                f"  Matched: ItemName={line.item_name!r}"
            )
        if is_pinch_clamp_tool_ct108_line(line.description_raw):
            flags.append(
                pinch_clamp_tool_ct108_review_flag(
                    line.description_raw,
                    row=10 + i,
                )
            )
        if is_review_tool_line(
            item_code=line.item_code,
            item_name=line.item_name,
            description_raw=line.description_raw,
        ):
            flags.append(
                review_tool_flag(
                    item_code=line.item_code,
                    item_name=line.item_name,
                    description_raw=line.description_raw,
                    row=10 + i,
                )
            )
    return flags

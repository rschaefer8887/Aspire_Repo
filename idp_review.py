"""Pending invoice review sessions for the Streamlit dashboard."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

try:
    import fitz  # pymupdf
except ImportError:
    fitz = None

from idp_openai import ExtractionResult, LineMatch, format_invoice_number
from idp_costs import effective_invoice_total
from idp_paths import ROOT, confidence_threshold, review_pending_dir
from idp_reference import InventoryRecord, ReferenceData


@dataclass
class ReviewLine:
    description_raw: str
    quantity: float
    unit_price: float
    item_code: str | None = None
    item_name: str | None = None
    confidence: float = 0.0
    rationale: str = ""
    needs_review: bool = False
    excluded: bool = False


@dataclass
class ReviewSession:
    session_id: str
    created_at: str
    pdf_path: str
    pdf_name: str
    invoice_date: str | None
    vendor_raw: str
    vendor_name: str | None
    vendor_confidence: float
    invoice_number_raw: str
    invoice_total: float | None
    invoice_total_original: float | None = None
    lines: list[ReviewLine] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def original_invoice_total(self) -> float | None:
        if self.invoice_total_original is not None:
            return self.invoice_total_original
        return self.invoice_total

    def adjusted_invoice_total(self) -> float | None:
        return effective_invoice_total(self.original_invoice_total(), self.lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReviewSession:
        lines: list[ReviewLine] = []
        for row in data.get("lines") or []:
            lines.append(
                ReviewLine(
                    description_raw=str(row.get("description_raw") or ""),
                    quantity=float(row.get("quantity") or 0),
                    unit_price=float(row.get("unit_price") or 0),
                    item_code=row.get("item_code"),
                    item_name=row.get("item_name"),
                    confidence=float(row.get("confidence") or 0),
                    rationale=str(row.get("rationale") or ""),
                    needs_review=bool(row.get("needs_review", False)),
                    excluded=bool(row.get("excluded", False)),
                )
            )
        invoice_total = data.get("invoice_total")
        invoice_total_original = data.get("invoice_total_original")
        if invoice_total_original is None:
            invoice_total_original = invoice_total
        return cls(
            session_id=str(data["session_id"]),
            created_at=str(data.get("created_at") or ""),
            pdf_path=str(data["pdf_path"]),
            pdf_name=str(data.get("pdf_name") or Path(data["pdf_path"]).name),
            invoice_date=data.get("invoice_date"),
            vendor_raw=str(data.get("vendor_raw") or ""),
            vendor_name=data.get("vendor_name"),
            vendor_confidence=float(data.get("vendor_confidence") or 0),
            invoice_number_raw=str(data.get("invoice_number_raw") or ""),
            invoice_total=invoice_total,
            invoice_total_original=invoice_total_original,
            lines=lines,
            flags=list(data.get("flags") or []),
        )


def _session_id(vendor: str, invoice_number: str) -> str:
    from idp_paths import sanitize_filename_part

    v = sanitize_filename_part(vendor, 40)
    inv = sanitize_filename_part(format_invoice_number(invoice_number), 30)
    return f"{v}_{inv}"


def session_path(session_id: str) -> Path:
    return review_pending_dir() / f"{session_id}.json"


def extraction_to_session(
    result: ExtractionResult,
    pdf_path: Path,
    *,
    flags: list[str],
) -> ReviewSession:
    th = confidence_threshold()
    vendor_needs = not result.vendor_name or result.vendor_confidence < th
    lines: list[ReviewLine] = []
    for line in result.lines:
        line_needs = (
            line.confidence < th or (not line.item_code and not line.item_name)
        )
        lines.append(
            ReviewLine(
                description_raw=line.description_raw,
                quantity=line.quantity,
                unit_price=line.unit_price,
                item_code=line.item_code,
                item_name=line.item_name,
                confidence=line.confidence,
                rationale=line.rationale,
                needs_review=line_needs or vendor_needs,
            )
        )
    vendor = result.vendor_name or result.vendor_raw or "Unknown_Vendor"
    sid = _session_id(vendor, result.invoice_number_raw)
    return ReviewSession(
        session_id=sid,
        created_at=datetime.now().isoformat(timespec="seconds"),
        pdf_path=str(pdf_path.resolve()),
        pdf_name=pdf_path.name,
        invoice_date=result.invoice_date.isoformat() if result.invoice_date else None,
        vendor_raw=result.vendor_raw,
        vendor_name=result.vendor_name,
        vendor_confidence=result.vendor_confidence,
        invoice_number_raw=result.invoice_number_raw,
        invoice_total=result.invoice_total,
        invoice_total_original=result.invoice_total,
        lines=lines,
        flags=flags,
    )


def session_to_extraction(session: ReviewSession) -> ExtractionResult:
    included = [ln for ln in session.lines if not ln.excluded]
    if not included:
        raise ValueError("Cannot approve — all lines are excluded from the invoice")
    inv_date: date | None = None
    if session.invoice_date:
        try:
            inv_date = date.fromisoformat(session.invoice_date)
        except ValueError:
            inv_date = None
    lines = [
        LineMatch(
            description_raw=ln.description_raw,
            quantity=ln.quantity,
            unit_price=ln.unit_price,
            item_code=ln.item_code or None,
            item_name=ln.item_name or None,
            confidence=1.0 if ln.item_code or ln.item_name else ln.confidence,
            rationale=ln.rationale,
        )
        for ln in included
    ]
    vendor_id = None
    refs = ReferenceData()
    refs.load()
    if session.vendor_name:
        rec = refs.resolve_vendor_name(session.vendor_name)
        vendor_id = rec.vendor_id if rec else None
    return ExtractionResult(
        invoice_date=inv_date,
        vendor_raw=session.vendor_raw,
        vendor_name=session.vendor_name,
        vendor_id=vendor_id,
        vendor_confidence=session.vendor_confidence,
        vendor_rationale="",
        invoice_number_raw=session.invoice_number_raw,
        invoice_total=session.adjusted_invoice_total(),
        lines=lines,
    )


def save_session(session: ReviewSession) -> Path:
    path = session_path(session.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    return path


def load_session(path: Path) -> ReviewSession:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ReviewSession.from_dict(data)


def list_pending_sessions() -> list[tuple[Path, ReviewSession]]:
    folder = review_pending_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out: list[tuple[Path, ReviewSession]] = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append((path, load_session(path)))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return out


def delete_session(session_id: str) -> None:
    path = session_path(session_id)
    if path.is_file():
        path.unlink()


def catalog_label(rec: InventoryRecord) -> str:
    code = (rec.item_code or "").strip()
    name = (rec.item_name or rec.item_alternate_name or "").strip()
    if code and name:
        return f"{code} | {name}"
    return code or name or ""


def build_catalog_options(refs: ReferenceData) -> list[str]:
    options = [""]
    seen: set[str] = set()
    for rec in refs.inventory:
        label = catalog_label(rec)
        if not label or label in seen:
            continue
        seen.add(label)
        options.append(label)
    options[1:] = sorted(options[1:], key=str.lower)
    return options


def build_vendor_options(refs: ReferenceData) -> list[str]:
    return sorted({v.vendor_name for v in refs.vendors if v.vendor_name})


def build_catalog_label_index(
    refs: ReferenceData,
) -> dict[str, tuple[str | None, str | None]]:
    """Map dropdown label -> (ItemCode, ItemName) for Streamlit selections."""
    index: dict[str, tuple[str | None, str | None]] = {}
    for rec in refs.inventory:
        lab = catalog_label(rec)
        if not lab or lab in index:
            continue
        code = (rec.item_code or "").strip() or None
        name = (rec.item_name or rec.item_alternate_name or "").strip() or None
        index[lab] = (code, name)
    return index


def resolve_catalog_label(
    label: str,
    catalog_index: dict[str, tuple[str | None, str | None]] | None = None,
) -> tuple[str | None, str | None]:
    """Parse a catalog dropdown value into Aspire ItemCode and ItemName."""
    label = (label or "").strip()
    if not label:
        return None, None
    if catalog_index and label in catalog_index:
        return catalog_index[label]
    if " | " in label:
        code, name = label.split(" | ", 1)
        return code.strip() or None, name.strip() or None
    return None, label


def parse_catalog_label(label: str) -> tuple[str | None, str | None]:
    """Parse catalog label without index (name-only labels -> name, not code)."""
    return resolve_catalog_label(label, None)


def label_for_line(item_code: str | None, item_name: str | None) -> str:
    code = (item_code or "").strip()
    name = (item_name or "").strip()
    if code and name:
        return f"{code} | {name}"
    return code or name or ""


def resolve_pdf_path(session: ReviewSession) -> Path | None:
    candidates = [
        Path(session.pdf_path),
        ROOT / session.pdf_path,
    ]
    if not Path(session.pdf_path).is_absolute():
        from idp_paths import invoices_processed_dir

        candidates.append(invoices_processed_dir() / session.pdf_name)
        candidates.append(invoices_processed_dir() / Path(session.pdf_path).name)
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return None


def _require_fitz():
    if fitz is None:
        raise RuntimeError("Install pymupdf: pip install pymupdf")


def pdf_page_count(pdf_path: Path) -> int:
    _require_fitz()
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def _line_focus_clip(page: fitz.Page, line_index: int, total_lines: int) -> fitz.Rect:
    rect = page.rect
    item_top = rect.height * 0.22
    item_height = rect.height * 0.68
    if total_lines <= 1:
        band_top = item_top
        band_height = min(item_height, rect.height * 0.35)
    else:
        band_height = min(item_height / max(total_lines, 1) * 2.8, item_height * 0.45)
        fraction = line_index / max(total_lines - 1, 1)
        center = item_top + fraction * item_height
        band_top = max(item_top, center - band_height / 2)
        band_top = min(band_top, item_top + item_height - band_height)
    return fitz.Rect(0, band_top, rect.width, band_top + band_height)


def render_pdf_png(
    pdf_path: Path,
    *,
    page_index: int = 0,
    line_index: int | None = None,
    total_lines: int = 1,
    scale: float = 2.0,
    full_page: bool = False,
) -> bytes:
    _require_fitz()
    doc = fitz.open(pdf_path)
    try:
        page_index = max(0, min(page_index, len(doc) - 1))
        page = doc[page_index]
        matrix = fitz.Matrix(scale, scale)
        if full_page or line_index is None:
            pix = page.get_pixmap(matrix=matrix)
        else:
            clip = _line_focus_clip(page, line_index, total_lines)
            pix = page.get_pixmap(matrix=matrix, clip=clip)
        return pix.tobytes("png")
    finally:
        doc.close()


def render_pdf_for_streamlit(
    pdf_path: Path,
    *,
    page_index: int = 0,
    line_index: int | None = None,
    total_lines: int = 1,
    full_page: bool = False,
) -> BytesIO:
    data = render_pdf_png(
        pdf_path,
        page_index=page_index,
        line_index=line_index,
        total_lines=total_lines,
        full_page=full_page,
    )
    return BytesIO(data)

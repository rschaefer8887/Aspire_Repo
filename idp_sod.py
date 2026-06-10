"""Idaho Sod and shared sod-invoice transforms (Total Due / sq ft, price split)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from idp_costs import LineOutput, line_total_cost, reconcile_line_costs
from idp_reference import InventoryRecord, ReferenceData
from idp_vendor_prefs import is_idaho_sod_vendor

if TYPE_CHECKING:
    from idp_openai import ExtractionResult, LineMatch

# Invoice grass wording → substring that must appear in catalog ItemName (lower).
SOD_CATALOG_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brtf\b|rhizomatous", re.I), "rtf"),
    (re.compile(r"kentucky|bluegrass", re.I), "bluegrass"),
    (re.compile(r"meadow", re.I), "meadow"),
    (re.compile(r"\bfescue\b", re.I), "fescue"),
    (re.compile(r"native", re.I), "native sod"),
)

_CHARGE_LINE_RE = re.compile(
    r"delivery|fuel\s*surcharge|surcharge|pallet|deposit",
    re.I,
)

_SOD_MATERIAL_RE = re.compile(
    r"kentucky|bluegrass|fescue|meadow|rtf|rhizomatous|\bsod\b",
    re.I,
)


@dataclass(frozen=True)
class SodSplitResult:
    single_line_ok: bool
    line_a: tuple[float, float]  # qty, unit_cost
    line_b: tuple[float, float] | None
    note: str = ""


def sod_catalog_items(refs: ReferenceData) -> list[InventoryRecord]:
    """Material catalog rows whose name contains 'sod'."""
    return [
        rec
        for rec in refs.inventory
        if rec.item_type == "Material" and "sod" in (rec.item_name or "").lower()
    ]


def match_sod_catalog(
    description_raw: str,
    refs: ReferenceData,
) -> tuple[InventoryRecord | None, float, str]:
    """Map invoice grass description to one of the sod Material SKUs."""
    desc = description_raw or ""
    if not _SOD_MATERIAL_RE.search(desc):
        return None, 0.0, "No sod grass type in description"

    hint: str | None = None
    for pattern, catalog_hint in SOD_CATALOG_HINTS:
        if pattern.search(desc):
            hint = catalog_hint
            break
    if hint is None:
        return None, 0.0, "Unrecognized sod type"

    candidates = sod_catalog_items(refs)
    if hint == "native sod":
        matches = [c for c in candidates if "native" in (c.item_name or "").lower()]
    elif hint == "rtf":
        matches = [c for c in candidates if "rtf" in (c.item_name or "").lower()]
    elif hint == "bluegrass":
        matches = [
            c
            for c in candidates
            if "bluegrass" in (c.item_name or "").lower()
            and "rtf" not in (c.item_name or "").lower()
        ]
    elif hint == "meadow":
        matches = [c for c in candidates if "meadow" in (c.item_name or "").lower()]
    elif hint == "fescue":
        matches = [
            c
            for c in candidates
            if "fescue" in (c.item_name or "").lower()
            and "rtf" not in (c.item_name or "").lower()
            and "rhizomatous" not in (c.item_name or "").lower()
        ]
    else:
        matches = []

    if len(matches) == 1:
        rec = matches[0]
        return rec, 0.95, f"Sod alias → {rec.item_name!r}"
    if len(matches) > 1:
        rec = matches[0]
        return rec, 0.80, f"Ambiguous sod match; picked {rec.item_name!r}"
    return None, 0.0, f"No catalog sod for hint {hint!r}"


def is_sod_charge_line(description_raw: str) -> bool:
    return bool(_CHARGE_LINE_RE.search(description_raw or ""))


def is_sod_material_line(description_raw: str) -> bool:
    desc = description_raw or ""
    return bool(_SOD_MATERIAL_RE.search(desc)) and not is_sod_charge_line(desc)


def compute_sod_price_split(total: float, qty: float) -> SodSplitResult:
    """
    Compute a two-line manual split (3-decimal unit costs) that sums to Total Due.
    Used for B6 receipt note when a single import line cannot match exactly.
    """
    target = round(float(total), 2)
    sqft = float(qty)
    if sqft <= 0 or target <= 0:
        return SodSplitResult(
            False,
            (sqft, 0.0),
            None,
            note="Invalid total or quantity",
        )

    single = [LineOutput("", "", sqft, round(target / sqft, 3))]
    if reconcile_line_costs(single, target):
        return SodSplitResult(
            True,
            (sqft, single[0].unit_cost),
            None,
            note="Single line reconciled to Total Due",
        )

    qty_int = int(round(sqft))
    if qty_int <= 1:
        return SodSplitResult(
            False,
            (sqft, single[0].unit_cost),
            None,
            note="Quantity too small to split",
        )

    base_unit = round(target / sqft, 3)
    half = qty_int // 2

    for qty1 in range(max(1, half - 500), min(qty_int, half + 500) + 1):
        qty2 = qty_int - qty1
        if qty2 <= 0:
            continue
        for d1 in range(-5, 6):
            for d2 in range(-5, 6):
                u1 = round(base_unit + d1 * 0.001, 3)
                u2 = round(base_unit + d2 * 0.001, 3)
                if u1 < 0 or u2 < 0:
                    continue
                ext = round(qty1 * u1 + qty2 * u2, 2)
                if abs(ext - target) < 0.005:
                    return SodSplitResult(
                        False,
                        (float(qty1), u1),
                        (float(qty2), u2),
                        note=(
                            f"Split {qty_int} sq ft into {qty1}+{qty2} "
                            f"at {u1}/{u2} per sq ft"
                        ),
                    )

    qty1 = float(half)
    qty2 = sqft - qty1
    u1 = base_unit
    ext1 = line_total_cost(qty1, u1)
    u2 = round((target - ext1) / qty2, 3) if qty2 > 0 else 0.0
    ext = round(line_total_cost(qty1, u1) + line_total_cost(qty2, u2), 2)
    if abs(ext - target) < 0.02:
        return SodSplitResult(
            False,
            (qty1, u1),
            (qty2, u2),
            note="Approximate split (verify Total Due)",
        )

    return SodSplitResult(
        False,
        (sqft, single[0].unit_cost),
        None,
        note="Could not find exact 3-decimal split",
    )


def format_sod_receipt_note(
    invoice_total: float,
    sqft: float,
    import_unit: float,
    split: SodSplitResult,
) -> str | None:
    """B6 / ReceiptNote text when 3-decimal single-line import differs from Total Due."""
    target = round(float(invoice_total), 2)
    import_ext = line_total_cost(sqft, import_unit)
    variance = round(target - import_ext, 2)

    if abs(variance) < 0.005:
        return None

    return f"Variance {variance:+,.2f} (3-decimal limit)."


def build_sod_receipt_note(
    invoice_total: float,
    lines: list[LineOutput],
    split: SodSplitResult,
) -> str | None:
    if not lines:
        return None
    ln = lines[0]
    return format_sod_receipt_note(invoice_total, ln.quantity, ln.unit_cost, split)


def transform_idaho_sod_extraction(
    result: ExtractionResult,
    refs: ReferenceData,
) -> ExtractionResult:
    """
    Collapse Idaho Sod invoice to one sod catalog line priced from Total Due ÷ sq ft.
    Delivery / pallet / fuel lines are dropped (already in Total Due).
    """
    from idp_openai import LineMatch

    if not (
        is_idaho_sod_vendor(result.vendor_name)
        or is_idaho_sod_vendor(result.vendor_raw)
    ):
        return result

    invoice_total = result.invoice_total
    if invoice_total is None or invoice_total <= 0:
        return result

    material_lines = [
        ln for ln in result.lines if is_sod_material_line(ln.description_raw)
    ]
    if not material_lines:
        return result

    material = max(material_lines, key=lambda ln: ln.quantity)
    sqft = material.quantity
    if sqft <= 0:
        return result

    rec, match_conf, match_note = match_sod_catalog(material.description_raw, refs)
    if not rec:
        return result

    split = compute_sod_price_split(invoice_total, sqft)
    import_unit = round(invoice_total / sqft, 3)

    result.lines = [
        LineMatch(
            description_raw=material.description_raw,
            quantity=sqft,
            unit_price=import_unit,
            uom_raw=material.uom_raw or "SF",
            item_code=rec.item_code or None,
            item_name=rec.item_name,
            confidence=max(
                0.95,
                min(material.confidence, match_conf)
                if material.confidence
                else match_conf,
            ),
            rationale=(
                f"Idaho Sod: Total Due {invoice_total:.2f} / {sqft:.0f} sq ft; "
                f"{match_note}; single import line"
            ),
        )
    ]
    result.sod_split = split
    return result

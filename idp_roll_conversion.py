"""Convert Fowler roll-priced invoice lines to feet qty + per-foot unit cost."""

from __future__ import annotations

import re

# Fallback when UoM is RL but roll length could not be parsed from the description.
ROLL_ITEM_FALLBACK_FEET: dict[str, int] = {
    "Wire - 18 GA 13 Strand": 500,
    "Wire - 14 GA Red/Blue, Golf (for 2-wire systems)": 1000,
    # Legacy export typo — keep so older catalog CSV rows still resolve.
    "Wire - 14 GA Red/Blue, Gold (for 2-wire systems)": 1000,
}

# Fowler mislabels UoM as EA; treat matched catalog ItemName as roll (feet per roll).
ROLL_ITEMS_EA_MEANS_ROLL: dict[str, int] = {
    "Wire - 14 GA Red/Blue, Golf (for 2-wire systems)": 1000,
    "Wire - 14 GA Red/Blue, Gold (for 2-wire systems)": 1000,
}

# Fowler Hunter 2-wire decoder cable — roll in description, UoM often EA.
_INVOICE_HUNTER_2WIRE_ROLL_RE = re.compile(
    r"14/2\s+jacketed.*hunter\s+2-?wire",
    re.IGNORECASE | re.DOTALL,
)

# Rain Bird SPX-FLEX swing pipe — 100' rolls, UoM often EA.
_INVOICE_SPX_FLEX_SWING_PIPE_RE = re.compile(
    r"spx-?\s*flex.*swing\s+pipe|swing\s+pipe.*spx-?\s*flex",
    re.IGNORECASE | re.DOTALL,
)

# Pro Turf / Fowler SIDR-15 poly — Fowler qty/UoM is feet; do not treat 300' ROLL as roll count.
_SIDR15_POLY_NO_ROLL_CONVERSION_RE = re.compile(
    r"pro\s+turf\s+green.*sidr-?\s*15|sidr-?\s*15.*pro\s+turf\s+green|"
    r"sidr-?\s*15.*poly\s+pipe.*(?:3608|black)|"
    r"(?:3608|black).*sidr-?\s*15.*poly\s+pipe",
    re.IGNORECASE | re.DOTALL,
)

_EXPLICIT_FEET_RE = re.compile(
    r"""
    \b(\d{2,4})\s*(?:FT|FEET)\b   # 500 FT
    |
    \b(\d{2,4})'                   # 500'
    """,
    re.IGNORECASE | re.VERBOSE,
)

_ROLL_LENGTH_WHITELIST_RE = re.compile(r"\b(250|500|1000|2000)\b")


def normalize_uom(uom: str | None) -> str:
    if not uom:
        return ""
    s = str(uom).strip().upper()
    if s in {"RL", "ROLL", "ROL", "ROLLS"}:
        return "RL"
    return s


def is_roll_uom(uom: str | None) -> bool:
    return normalize_uom(uom) == "RL"


def _skip_roll_conversion(description_raw: str) -> bool:
    """Invoice lines where qty is already feet (or each), not roll count."""
    return bool(_SIDR15_POLY_NO_ROLL_CONVERSION_RE.search(description_raw or ""))


def _should_convert_as_roll(
    uom_raw: str | None,
    item_name: str | None,
    description_raw: str = "",
) -> bool:
    if is_roll_uom(uom_raw):
        return True
    if item_name and item_name in ROLL_ITEMS_EA_MEANS_ROLL:
        return True
    return _invoice_description_means_roll(description_raw) is not None


def _invoice_description_means_roll(description_raw: str) -> int | None:
    """
    One-off Fowler invoice lines sold as rolls but UoM is often EA.
    Returns feet per roll when description matches, else None.
    """
    desc = description_raw or ""
    if _INVOICE_HUNTER_2WIRE_ROLL_RE.search(desc):
        return (
            feet_per_roll_from_description(desc)
            or feet_per_roll_whitelist(desc)
            or 1000
        )
    if _INVOICE_SPX_FLEX_SWING_PIPE_RE.search(desc):
        return feet_per_roll_from_description(desc) or 100
    return None


def _catalog_fallback_feet(item_name: str | None) -> int | None:
    if not item_name:
        return None
    if item_name in ROLL_ITEM_FALLBACK_FEET:
        return ROLL_ITEM_FALLBACK_FEET[item_name]
    if item_name in ROLL_ITEMS_EA_MEANS_ROLL:
        return ROLL_ITEMS_EA_MEANS_ROLL[item_name]
    return None


def feet_per_roll_from_description(description: str) -> int | None:
    """Parse explicit roll length from description (500 FT, 500', etc.)."""
    for match in _EXPLICIT_FEET_RE.finditer(description or ""):
        raw = match.group(1) or match.group(2)
        if raw:
            return int(raw)
    return None


def feet_per_roll_whitelist(description: str) -> int | None:
    """Common Fowler roll lengths when UoM is already RL."""
    match = _ROLL_LENGTH_WHITELIST_RE.search(description or "")
    return int(match.group(1)) if match else None


def resolve_feet_per_roll(
    description_raw: str,
    uom_raw: str | None,
    *,
    item_name: str | None = None,
) -> tuple[int | None, str | None]:
    """
    Return (feet_per_roll, source) where source is 'description' or 'catalog'.
    """
    if not _should_convert_as_roll(uom_raw, item_name, description_raw):
        return None, None

    feet = feet_per_roll_from_description(description_raw)
    if feet:
        return feet, "description"

    feet = feet_per_roll_whitelist(description_raw)
    if feet:
        return feet, "description"

    feet = _catalog_fallback_feet(item_name)
    if feet:
        return feet, "catalog"

    feet = _invoice_description_means_roll(description_raw)
    if feet:
        return feet, "description"

    return None, None


def roll_line_missing_feet_per_roll(
    description_raw: str,
    uom_raw: str | None,
    item_name: str | None = None,
) -> bool:
    """True when line should convert as roll but feet per roll cannot be determined."""
    if not _should_convert_as_roll(uom_raw, item_name, description_raw):
        return False
    feet, _ = resolve_feet_per_roll(
        description_raw, uom_raw, item_name=item_name
    )
    return feet is None


def maybe_convert_roll_line(
    quantity: float,
    unit_price: float,
    *,
    description_raw: str,
    uom_raw: str | None,
    item_name: str | None = None,
) -> tuple[float, float, str | None]:
    """
    When UoM is RL, convert roll qty/price to feet qty and per-foot pre-tax price.
    Preserves line extended total. Returns (qty, unit_price, note_or_none).
    """
    if quantity <= 0:
        return quantity, unit_price, None

    if _skip_roll_conversion(description_raw):
        return quantity, unit_price, None

    feet, source = resolve_feet_per_roll(
        description_raw, uom_raw, item_name=item_name
    )
    if not feet:
        return quantity, unit_price, None

    new_qty = quantity * feet
    new_price = unit_price / feet
    uom_label = "RL" if is_roll_uom(uom_raw) else "EA→roll"
    note = f"roll→ft: {quantity:g} {uom_label} × {feet} = {new_qty:g} ({source})"
    return new_qty, new_price, note

"""Convert Fowler pack-priced lines (canister, box) to each qty + per-each unit cost."""

from __future__ import annotations

import re

from idp_reference import is_irrigation_staples_invoice_line

# Aspire ItemCode -> units per canister (invoice qty is canister count).
CANISTER_ITEMS_BY_CODE: dict[str, int] = {
    "10241": 100,
}

# Fowler King Innovation blue connector — invoice text when ItemCode is absent.
_KING_BLUE_CONNECTOR_10241_RE = re.compile(
    r"blue\s+king\s+connector.*(?:#)?10241|(?:#)?10241.*king\s+innovation",
    re.IGNORECASE | re.DOTALL,
)

_UNITS_PER_CANISTER_RE = re.compile(
    r"\b(\d{1,5})\s+per\s+canister\b",
    re.IGNORECASE,
)

# Aspire ItemCode -> units per box (invoice qty is box count).
BOX_ITEMS_BY_CODE: dict[str, int] = {}

# Catalog ItemName -> units per box.
BOX_ITEMS_BY_NAME: dict[str, int] = {
    "Irrigation Staples": 1000,
}

_UNITS_PER_BOX_RE = re.compile(
    r"\b(\d{1,5})\s+per\s+box\b",
    re.IGNORECASE,
)


def _normalize_item_code(item_code: str | None) -> str:
    if not item_code:
        return ""
    return str(item_code).strip().lstrip("#")


def units_per_canister_from_description(description_raw: str) -> int | None:
    match = _UNITS_PER_CANISTER_RE.search(description_raw or "")
    return int(match.group(1)) if match else None


def units_per_box_from_description(description_raw: str) -> int | None:
    match = _UNITS_PER_BOX_RE.search(description_raw or "")
    return int(match.group(1)) if match else None


def _is_king_blue_connector_line(
    description_raw: str,
    item_code: str | None,
) -> bool:
    code = _normalize_item_code(item_code)
    if code == "10241":
        return True
    desc = description_raw or ""
    if re.search(r"(?:#|\b)10241\b", desc, re.IGNORECASE):
        return True
    return bool(_KING_BLUE_CONNECTOR_10241_RE.search(desc))


def resolve_units_per_canister(
    description_raw: str,
    *,
    item_code: str | None = None,
    item_name: str | None = None,
) -> tuple[int | None, str | None]:
    """Return (units_per_canister, source) where source is 'catalog' or 'description'."""
    _ = item_name
    code = _normalize_item_code(item_code)
    if code in CANISTER_ITEMS_BY_CODE:
        return CANISTER_ITEMS_BY_CODE[code], "catalog"

    if not _is_king_blue_connector_line(description_raw, item_code):
        return None, None

    units = units_per_canister_from_description(description_raw) or 100
    return units, "description"


def maybe_convert_canister_line(
    quantity: float,
    unit_price: float,
    *,
    description_raw: str,
    item_code: str | None = None,
    item_name: str | None = None,
) -> tuple[float, float, str | None]:
    """
    When invoice qty is canisters, convert to each qty and per-each pre-tax price.
    Preserves line extended total.
    """
    if quantity <= 0:
        return quantity, unit_price, None

    units, source = resolve_units_per_canister(
        description_raw,
        item_code=item_code,
        item_name=item_name,
    )
    if not units:
        return quantity, unit_price, None

    new_qty = quantity * units
    new_price = unit_price / units
    note = f"canister→ea: {quantity:g} × {units} = {new_qty:g} ({source})"
    return new_qty, new_price, note


def _is_jute_staples_box_line(
    description_raw: str,
    item_code: str | None,
    item_name: str | None,
) -> bool:
    code = _normalize_item_code(item_code)
    if code in BOX_ITEMS_BY_CODE:
        return True
    if item_name and item_name in BOX_ITEMS_BY_NAME:
        return True
    if item_name and _norm_item_name(item_name) == "irrigation staples":
        return True
    return is_irrigation_staples_invoice_line(description_raw or "")


def _norm_item_name(item_name: str) -> str:
    return " ".join(str(item_name).strip().lower().split())


def resolve_units_per_box(
    description_raw: str,
    *,
    item_code: str | None = None,
    item_name: str | None = None,
) -> tuple[int | None, str | None]:
    """Return (units_per_box, source) where source is 'catalog' or 'description'."""
    code = _normalize_item_code(item_code)
    if code in BOX_ITEMS_BY_CODE:
        return BOX_ITEMS_BY_CODE[code], "catalog"
    if item_name and item_name in BOX_ITEMS_BY_NAME:
        return BOX_ITEMS_BY_NAME[item_name], "catalog"

    if not _is_jute_staples_box_line(description_raw, item_code, item_name):
        return None, None

    units = units_per_box_from_description(description_raw) or 1000
    return units, "description"


def maybe_convert_box_line(
    quantity: float,
    unit_price: float,
    *,
    description_raw: str,
    item_code: str | None = None,
    item_name: str | None = None,
) -> tuple[float, float, str | None]:
    """
    When invoice qty is boxes, convert to each qty and per-each pre-tax price.
    Preserves line extended total.
    """
    if quantity <= 0:
        return quantity, unit_price, None

    units, source = resolve_units_per_box(
        description_raw,
        item_code=item_code,
        item_name=item_name,
    )
    if not units:
        return quantity, unit_price, None

    new_qty = quantity * units
    new_price = unit_price / units
    note = f"box→ea: {quantity:g} × {units} = {new_qty:g} ({source})"
    return new_qty, new_price, note

"""One-off rules that queue invoices for Streamlit review (exclude-from-invoice workflow)."""

from __future__ import annotations

import re

_PINCH_CLAMP_CT108_RE = re.compile(
    r"pinch\s+clamp\s+tool.*\bct108\b|\bct108\b.*pinch\s+clamp",
    re.IGNORECASE | re.DOTALL,
)

# Catalog tools — queue for review so user can exclude from receipt if not inventory.
_REVIEW_TOOL_BY_CODE: dict[str, str] = {
    "ROTORTOOL": "Rain Bird Universal Rotor Tool Green",
    "SS200": "Dawn SS200 Large PVC Cutter",
    "CT112": "PINCH CLAMP TOOL LARGE CT112",
}


def _normalize_item_code(item_code: str | None) -> str:
    return str(item_code or "").strip().lstrip("#").upper()


def is_pinch_clamp_tool_ct108_line(description_raw: str) -> bool:
    """Fowler tool rental/loan lines the user may exclude from inventory receipt."""
    return bool(_PINCH_CLAMP_CT108_RE.search(description_raw or ""))


def pinch_clamp_tool_ct108_review_flag(
    description_raw: str,
    *,
    row: int,
) -> str:
    return (
        f"PINCH CLAMP TOOL CT108 row {row} — review and exclude if not inventory:\n"
        f"  Raw: {description_raw!r}"
    )


def is_review_tool_line(
    *,
    item_code: str | None,
    item_name: str | None = None,
    description_raw: str = "",
) -> bool:
    """True when a matched catalog tool should always go through Streamlit review."""
    code = _normalize_item_code(item_code)
    if code in _REVIEW_TOOL_BY_CODE:
        return True
    desc_u = (description_raw or "").upper()
    for tool_code in _REVIEW_TOOL_BY_CODE:
        if tool_code in desc_u:
            return True
    return False


def review_tool_flag(
    *,
    item_code: str | None,
    item_name: str | None,
    description_raw: str,
    row: int,
) -> str:
    code = _normalize_item_code(item_code)
    label = _REVIEW_TOOL_BY_CODE.get(code) or (item_name or code or "tool")
    return (
        f"TOOL row {row} ({label}) — review and exclude if not inventory:\n"
        f"  Code: {item_code!r}  Name: {item_name!r}\n"
        f"  Raw: {description_raw!r}"
    )

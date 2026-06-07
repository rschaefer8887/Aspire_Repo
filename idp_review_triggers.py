"""One-off rules that queue invoices for Streamlit review (exclude-from-invoice workflow)."""

from __future__ import annotations

import re

_PINCH_CLAMP_CT108_RE = re.compile(
    r"pinch\s+clamp\s+tool.*\bct108\b|\bct108\b.*pinch\s+clamp",
    re.IGNORECASE | re.DOTALL,
)


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

"""HD Fowler inbound freight lines — allocate into material unit costs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from idp_costs import LineOutput, apply_tax, line_total_cost
from idp_vendor_profiles import HD_FOWLER_PROFILE, VendorProfile

_FOWLER_INBOUND_FREIGHT_RE = re.compile(
    r"inbound\s+(?:frt|freight)\b|inbound\s+frt\s*/\s*billable",
    re.IGNORECASE,
)


def is_fowler_inbound_freight_line(description_raw: str | None) -> bool:
    """True for Fowler billable inbound freight (not a catalog item)."""
    return bool(_FOWLER_INBOUND_FREIGHT_RE.search(description_raw or ""))


@dataclass(frozen=True)
class FowlerFreightAllocation:
    """Summary after spreading taxed freight into material unit costs."""

    freight_line_count: int
    freight_total_taxed: float
    material_unit_count: float
    freight_per_unit: float


def taxed_freight_extended(
    quantity: float, unit_price: float, *, profile: VendorProfile
) -> float:
    return line_total_cost(quantity, apply_tax(unit_price, profile=profile))


def allocate_fowler_freight_per_unit(
    material_lines: list[LineOutput],
    freight_lines: list[tuple[float, float]],
    *,
    profile: VendorProfile,
) -> FowlerFreightAllocation | None:
    """
    Sum taxed freight and add freight_per_unit to each material line's unit_cost.

    freight_lines: (quantity, pre-tax unit_price) from each freight invoice row.
    """
    if not freight_lines:
        return None
    if profile.profile_id != HD_FOWLER_PROFILE.profile_id:
        return None
    if not material_lines:
        raise ValueError(
            "HD Fowler invoice has inbound freight but no material lines to allocate it to."
        )

    freight_total = round(
        sum(
            taxed_freight_extended(qty, price, profile=profile)
            for qty, price in freight_lines
        ),
        2,
    )
    total_units = sum(float(ln.quantity) for ln in material_lines)
    if total_units <= 0:
        raise ValueError(
            "HD Fowler freight cannot be allocated — total material quantity is zero."
        )

    freight_per_unit = round(freight_total / total_units, 3)
    for ln in material_lines:
        ln.unit_cost = round(ln.unit_cost + freight_per_unit, 3)

    return FowlerFreightAllocation(
        freight_line_count=len(freight_lines),
        freight_total_taxed=freight_total,
        material_unit_count=total_units,
        freight_per_unit=freight_per_unit,
    )

"""Line cost math and reconciliation for IDP Excel output."""

from __future__ import annotations

from dataclasses import dataclass

from idp_paths import tax_multiplier


@dataclass
class LineOutput:
    item_code: str
    item_name: str
    quantity: float
    unit_cost: float


def apply_tax(unit_price: float) -> float:
    return round(unit_price * tax_multiplier(), 3)


def line_total_cost(quantity: float, unit_cost: float) -> float:
    return round(quantity * unit_cost, 2)


def taxed_line_total(quantity: float, unit_price_pre_tax: float) -> float:
    """Column F value for a line (pre-tax unit price × tax × qty)."""
    return line_total_cost(quantity, apply_tax(unit_price_pre_tax))


def effective_invoice_total(
    original_total: float | None,
    lines: list,
) -> float | None:
    """
    Invoice grand total after excluding lines marked excluded=True.
    Each excluded line subtracts its taxed extended cost from original_total.
    """
    if original_total is None:
        return None
    excluded_sum = 0.0
    for ln in lines:
        if getattr(ln, "excluded", False):
            excluded_sum += taxed_line_total(ln.quantity, ln.unit_price)
    return round(float(original_total) - excluded_sum, 2)


def reconcile_line_costs(
    lines: list[LineOutput], invoice_total: float | None
) -> bool:
    """
    Nudge unit costs (3 decimal places) so sum of line totals matches invoice_total.
    Returns True if totals match within one cent.
    """
    if invoice_total is None or invoice_total <= 0 or not lines:
        return True
    target = round(float(invoice_total), 2)

    def extended() -> list[float]:
        return [line_total_cost(l.quantity, l.unit_cost) for l in lines]

    def grand(ext: list[float]) -> float:
        return round(sum(ext), 2)

    ext = extended()
    if abs(grand(ext) - target) < 0.005:
        return True

    current = grand(ext)
    if current > 0 and abs(current - target) >= 0.01:
        factor = target / current
        for line in lines:
            line.unit_cost = round(line.unit_cost * factor, 3)

    adjustable = [ln for ln in lines if ln.quantity > 0]
    if not adjustable:
        return False

    by_qty = sorted(adjustable, key=lambda ln: ln.quantity)

    for _ in range(800):
        ext = extended()
        diff = round(target - grand(ext), 2)
        if abs(diff) < 0.005:
            return True
        step = 0.01 if diff > 0 else -0.01
        improved = False
        for line in by_qty:
            idx = lines.index(line)
            new_ext = round(ext[idx] + step, 2)
            if new_ext < 0:
                continue
            old_uc = line.unit_cost
            line.unit_cost = round(new_ext / line.quantity, 3)
            if abs(grand(extended()) - target) < abs(diff):
                improved = True
                break
            line.unit_cost = old_uc
        if not improved:
            line = by_qty[0]
            idx = lines.index(line)
            new_ext = round(ext[idx] + diff, 2)
            if new_ext >= 0:
                line.unit_cost = round(new_ext / line.quantity, 3)

    return abs(grand(extended()) - target) < 0.01

"""Unit tests for invoice line total reconciliation."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_costs import LineOutput, reconcile_line_costs  # noqa: E402


def _grand(lines: list[LineOutput]) -> float:
    return round(sum(round(l.quantity * l.unit_cost, 2) for l in lines), 2)


def test_reconcile_hits_target():
    lines = [
        LineOutput("", "a", 10, 6.773),
        LineOutput("", "b", 25, 3.858),
        LineOutput("", "c", 20, 16.218),
    ]
    target = _grand(lines) + 0.07
    reconcile_line_costs(lines, target)
    assert abs(_grand(lines) - target) < 0.01
    for line in lines:
        assert line.unit_cost == round(line.unit_cost, 3)


def test_unit_costs_stay_three_decimals():
    lines = [LineOutput("", "x", 3, 1.234)]
    reconcile_line_costs(lines, 3.71)
    for line in lines:
        assert line.unit_cost == round(line.unit_cost, 3)

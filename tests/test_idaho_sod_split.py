"""Sod price split math for 3-decimal Aspire unit costs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_sod import compute_sod_price_split  # noqa: E402


def _ext(qty: float, unit: float) -> float:
    return round(qty * unit, 2)


class TestIdahoSodSplit(unittest.TestCase):
    def test_single_line_when_exact(self) -> None:
        split = compute_sod_price_split(100.00, 100)
        self.assertTrue(split.single_line_ok)
        self.assertIsNone(split.line_b)
        q, u = split.line_a
        self.assertAlmostEqual(_ext(q, u), 100.00, places=2)

    def test_two_line_split_large_qty(self) -> None:
        total = 5432.17
        qty = 3450
        split = compute_sod_price_split(total, qty)
        self.assertIsNotNone(split.line_b)
        q1, u1 = split.line_a
        q2, u2 = split.line_b
        self.assertEqual(q1 + q2, qty)
        self.assertAlmostEqual(_ext(q1, u1) + _ext(q2, u2), total, places=2)
        self.assertEqual(u1, round(u1, 3))
        self.assertEqual(u2, round(u2, 3))

    def test_three_decimal_units(self) -> None:
        split = compute_sod_price_split(8123.45, 5200)
        lines = [split.line_a]
        if split.line_b:
            lines.append(split.line_b)
        for _q, u in lines:
            self.assertEqual(u, round(u, 3))


if __name__ == "__main__":
    unittest.main()

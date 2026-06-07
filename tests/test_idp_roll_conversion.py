"""Unit tests for roll UoM → feet quantity conversion."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_costs import apply_tax, line_total_cost  # noqa: E402
from idp_excel import extraction_to_lines  # noqa: E402
from idp_openai import ExtractionResult, LineMatch  # noqa: E402
from idp_roll_conversion import (  # noqa: E402
    feet_per_roll_from_description,
    is_roll_uom,
    maybe_convert_roll_line,
    roll_line_missing_feet_per_roll,
)
from idp_vendor_profiles import HD_FOWLER_PROFILE  # noqa: E402


class TestRollConversion(unittest.TestCase):
    def test_is_roll_uom(self) -> None:
        self.assertTrue(is_roll_uom("RL"))
        self.assertTrue(is_roll_uom("roll"))
        self.assertTrue(is_roll_uom(" ROL "))
        self.assertFalse(is_roll_uom("EA"))
        self.assertFalse(is_roll_uom(""))

    def test_feet_from_explicit_description(self) -> None:
        self.assertEqual(
            feet_per_roll_from_description("WIRE 18GA 13 STRAND 500 FT SOL CU"),
            500,
        )
        self.assertEqual(
            feet_per_roll_from_description("14 GA RED/BLUE 1000' 2-WIRE"),
            1000,
        )
        self.assertEqual(
            feet_per_roll_from_description("CABLE 250 FEET RL"),
            250,
        )

    def test_gauge_and_strand_not_used_as_feet_without_uom(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            50.0,
            description_raw="WIRE 18 GA 13 STRAND SOL CU",
            uom_raw="EA",
        )
        self.assertEqual(qty, 2)
        self.assertEqual(price, 50.0)
        self.assertIsNone(note)

    def test_convert_18ga_500ft_roll(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            125.0,
            description_raw="WIRE 18GA 13 STRAND 500 FT SOL CU",
            uom_raw="RL",
            item_name="Wire - 18 GA 13 Strand",
        )
        self.assertEqual(qty, 1000)
        self.assertAlmostEqual(price, 0.25)
        self.assertIn("roll→ft", note or "")
        self.assertAlmostEqual(qty * price, 250.0)

    def test_convert_14ga_1000ft_roll(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            200.0,
            description_raw="14 GA RED/BLUE GOLD 1000 FT 2-WIRE",
            uom_raw="RL",
            item_name="Wire - 14 GA Red/Blue, Golf (for 2-wire systems)",
        )
        self.assertEqual(qty, 2000)
        self.assertAlmostEqual(price, 0.2)
        self.assertIsNotNone(note)
        self.assertAlmostEqual(qty * price, 400.0)

    def test_hunter_2wire_invoice_ea_uom_with_exact_description(self) -> None:
        desc = (
            "14/2 Jacketed 1000' roll decoder cable for hunter 2-wire systems "
            "red/blue 14 ga twisted in blue jacketing"
        )
        self.assertEqual(feet_per_roll_from_description(desc), 1000)
        qty, price, note = maybe_convert_roll_line(
            2,
            180.0,
            description_raw=desc,
            uom_raw="EA",
            item_name="Wire - 14 GA Red/Blue, Golf (for 2-wire systems)",
        )
        self.assertEqual(qty, 2000)
        self.assertAlmostEqual(price, 0.18)
        self.assertIn("EA→roll", note or "")

    def test_hunter_2wire_invoice_ea_without_catalog_match(self) -> None:
        desc = (
            "14/2 Jacketed 1000' roll decoder cable for hunter 2-wire systems "
            "red/blue 14 ga twisted in blue jacketing"
        )
        qty, price, note = maybe_convert_roll_line(
            1,
            90.0,
            description_raw=desc,
            uom_raw="EA",
            item_name=None,
        )
        self.assertEqual(qty, 1000)
        self.assertAlmostEqual(price, 0.09)
        self.assertIsNotNone(note)

    def test_spx_flex_swing_pipe_100ft_roll_exact_invoice(self) -> None:
        desc = (
            'SPX-FLEX 1/2" DIAMETER SWING PIPE 100\' ROLL RAIN BIRD'
        )
        self.assertEqual(feet_per_roll_from_description(desc), 100)
        qty, price, note = maybe_convert_roll_line(
            2,
            85.0,
            description_raw=desc,
            uom_raw="EA",
            item_name=None,
        )
        self.assertEqual(qty, 200)
        self.assertAlmostEqual(price, 0.85)
        self.assertIn("EA→roll", note or "")
        self.assertAlmostEqual(qty * price, 170.0)

    def test_spx_flex_swing_pipe_with_rl_uom(self) -> None:
        desc = 'SPX-FLEX 1/2" DIAMETER SWING PIPE 100\' ROLL RAIN BIRD'
        qty, price, note = maybe_convert_roll_line(
            1,
            50.0,
            description_raw=desc,
            uom_raw="RL",
        )
        self.assertEqual(qty, 100)
        self.assertAlmostEqual(price, 0.5)
        self.assertIn("roll→ft", note or "")

    def test_pro_turf_sidr15_poly_not_converted_as_roll(self) -> None:
        desc = (
            '1" PRO TURF GREEN SIDR-15 100 PSI POLY PIPE 300\' ROLL 3608 HDPE'
        )
        qty, price, note = maybe_convert_roll_line(
            300,
            0.45,
            description_raw=desc,
            uom_raw="FT",
        )
        self.assertEqual(qty, 300)
        self.assertAlmostEqual(price, 0.45)
        self.assertIsNone(note)

    def test_pro_turf_sidr15_poly_not_converted_when_uom_rl(self) -> None:
        desc = (
            '1" PRO TURF GREEN SIDR-15 100 PSI POLY PIPE 300\' ROLL 3608 HDPE'
        )
        qty, price, note = maybe_convert_roll_line(
            300,
            0.45,
            description_raw=desc,
            uom_raw="RL",
        )
        self.assertEqual(qty, 300)
        self.assertAlmostEqual(price, 0.45)
        self.assertIsNone(note)

    def test_black_sidr15_poly_not_converted_when_uom_rl(self) -> None:
        desc = (
            '1-1/2" 100 PSI SIDR-15 POLY PIPE 300\' ROLL 3608 RESIN, BLACK'
        )
        qty, price, note = maybe_convert_roll_line(
            300,
            0.55,
            description_raw=desc,
            uom_raw="RL",
        )
        self.assertEqual(qty, 300)
        self.assertAlmostEqual(price, 0.55)
        self.assertIsNone(note)

    def test_whitelist_length_when_uom_rl(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            1,
            75.0,
            description_raw="WIRE 18GA 13 STRAND SOL 500",
            uom_raw="RL",
        )
        self.assertEqual(qty, 500)
        self.assertAlmostEqual(price, 0.15)
        self.assertIsNotNone(note)

    def test_ea_uom_treated_as_roll_for_hunter_2wire_catalog(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            180.0,
            description_raw="14/2 JACKETED 1000 FT HUNTER 2-WIRE RED/BLUE",
            uom_raw="EA",
            item_name="Wire - 14 GA Red/Blue, Golf (for 2-wire systems)",
        )
        self.assertEqual(qty, 2000)
        self.assertAlmostEqual(price, 0.18)
        self.assertIn("EA→roll", note or "")

    def test_ea_without_catalog_match_or_invoice_hint_does_not_convert(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            180.0,
            description_raw="14/2 JACKETS RED/BLUE WIRE 1000 FT",
            uom_raw="EA",
            item_name=None,
        )
        self.assertEqual(qty, 2)
        self.assertEqual(price, 180.0)
        self.assertIsNone(note)

    def test_catalog_fallback_when_rl_without_length_in_text(self) -> None:
        qty, price, note = maybe_convert_roll_line(
            2,
            100.0,
            description_raw="WIRE 18GA 13 STRAND SOL CU",
            uom_raw="RL",
            item_name="Wire - 18 GA 13 Strand",
        )
        self.assertEqual(qty, 1000)
        self.assertAlmostEqual(price, 0.2)
        self.assertIn("catalog", note or "")

    def test_roll_missing_length_flags_review(self) -> None:
        self.assertTrue(
            roll_line_missing_feet_per_roll(
                "WIRE 18GA 13 STRAND SOL CU",
                "RL",
                item_name=None,
            )
        )
        self.assertFalse(
            roll_line_missing_feet_per_roll(
                "WIRE 18GA 13 STRAND 500 FT SOL CU",
                "RL",
            )
        )

    def test_extraction_to_lines_preserves_extended_with_tax(self) -> None:
        result = ExtractionResult(
            invoice_date=date(2025, 1, 1),
            vendor_raw="H.D. Fowler",
            vendor_name="H.D. Fowler Company {Turf}",
            vendor_id=1,
            vendor_confidence=1.0,
            vendor_rationale="",
            invoice_number_raw="12345",
            lines=[
                LineMatch(
                    description_raw="WIRE 18GA 13 STRAND 500 FT",
                    quantity=2,
                    unit_price=50.0,
                    uom_raw="RL",
                    item_code="W18",
                    item_name="Wire - 18 GA 13 Strand",
                    confidence=1.0,
                )
            ],
        )
        lines = extraction_to_lines(result, profile=HD_FOWLER_PROFILE)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].quantity, 1000)
        expected_unit = apply_tax(50.0 / 500, profile=HD_FOWLER_PROFILE)
        self.assertEqual(lines[0].unit_cost, expected_unit)
        self.assertAlmostEqual(
            line_total_cost(lines[0].quantity, lines[0].unit_cost),
            round(1000 * expected_unit, 2),
        )
        self.assertAlmostEqual(
            line_total_cost(lines[0].quantity, lines[0].unit_cost),
            round(2 * apply_tax(50.0, profile=HD_FOWLER_PROFILE), 2),
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for supply-line matching (light tape rules, pipe dope, item codes)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import (  # noqa: E402
    InventoryRecord,
    ReferenceData,
    _code_appears_in_description,
    _invoice_excludes_wire_nuts,
    _is_pipe_dope_line,
    _is_tape_line,
    _norm,
    _product_hint,
)


def _refs_consumables() -> ReferenceData:
    refs = ReferenceData()
    refs.inventory = [
        InventoryRecord(
            "DT-2",
            'Duct Tape - 2" x 60 YDS Silver',
            "",
            "Material",
        ),
        InventoryRecord(
            "70886",
            'Blue Monster PTFE Thread Seal Tape - 3/4"',
            "",
            "Material",
        ),
        InventoryRecord("", 'Wire Nuts - Blue', "", "Material"),
        InventoryRecord("", 'PVC Close Nipple - 2" (SCH 80)', "", "Material"),
        InventoryRecord(
            "",
            "Blue Monster Pipe Dope (thread sealant)",
            "",
            "Material",
        ),
        InventoryRecord(
            "",
            "Weld On - White Seal Plus (pipe dope)",
            "",
            "Material",
        ),
    ]
    for rec in refs.inventory:
        if rec.item_code:
            refs._by_code[_norm(rec.item_code)] = rec
    return refs


class TestConsumableHelpers(unittest.TestCase):
    def test_is_tape_line_thread_seal_tape(self) -> None:
        self.assertTrue(
            _is_tape_line('3/4" x 1429\' Blue Monster PTFE Thread Seal Tape 70886')
        )
        self.assertTrue(_is_tape_line('Duct Tape 2" x 60 YDS Silver 9MIL'))

    def test_is_tape_line_false_for_ptfe_pipe_dope(self) -> None:
        self.assertFalse(
            _is_tape_line("WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON")
        )

    def test_is_tape_line_blue_monster_without_tape_word(self) -> None:
        self.assertTrue(
            _is_tape_line('3/4" x 1429" Blue Monster PTFE Thread Seal 70886')
        )
        self.assertTrue(_is_tape_line('3/4" Blue Monster PTFE 70886'))

    def test_is_tape_line_blue_monster_compound_not_pipe_dope(self) -> None:
        self.assertTrue(_is_tape_line("BLUE MONSTER PTFE COMPOUND"))

    def test_is_pipe_dope_line(self) -> None:
        self.assertTrue(
            _is_pipe_dope_line("WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON")
        )
        self.assertFalse(_is_pipe_dope_line('3/4" Blue Monster Thread Seal Tape'))

    def test_product_hint_pipe_dope_not_tape(self) -> None:
        self.assertEqual(
            _product_hint("WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON"),
            "pipe dope",
        )
        self.assertIsNone(_product_hint('Duct Tape 2" x 60 YDS'))

    def test_invoice_excludes_wire_nuts_one_off(self) -> None:
        desc = "3/4 blue monster ptfe thread seal 70886"
        self.assertTrue(
            _invoice_excludes_wire_nuts(desc, "wire nuts - blue")
        )
        self.assertTrue(_invoice_excludes_wire_nuts("some tape product", "wire nut"))
        self.assertTrue(_invoice_excludes_wire_nuts("white seal plus", "wire nuts"))
        self.assertFalse(
            _invoice_excludes_wire_nuts(
                "3m red/yellow wire nut bag qty 100",
                "wire nuts - red/yellow",
            )
        )

    def test_code_appears_with_trailing_period(self) -> None:
        self.assertTrue(
            _code_appears_in_description(
                "70886",
                '3/4" Blue Monster PTFE Thread Seal Tape 70886.',
            )
        )
        self.assertFalse(_code_appears_in_description("7088", "Tape 70886"))


class TestConsumableMatch(unittest.TestCase):
    def test_duct_tape_not_nipple(self) -> None:
        refs = _refs_consumables()
        desc = 'Duct Tape 2" x 60 YDS Silver 9MIL'
        rec, conf, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(conf, 0.85)
        name = (rec.item_name or "").lower()
        self.assertIn("duct", name)
        self.assertIn("tape", name)
        self.assertNotIn("nipple", name)

    def test_blue_monster_by_code_in_description(self) -> None:
        refs = _refs_consumables()
        desc = '3/4" x 1429" Blue Monster PTFE Thread Seal Tape 70886'
        rec, conf, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "70886")
        self.assertGreaterEqual(conf, 0.85)
        self.assertNotIn("wire", (rec.item_name or "").lower())

    def test_blue_monster_thread_seal_without_tape_word_not_wire_nuts(self) -> None:
        refs = _refs_consumables()
        desc = '3/4" x 1429" Blue Monster PTFE Thread Seal 70886'
        rec, conf, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "70886")
        self.assertGreaterEqual(conf, 0.85)
        self.assertNotIn("wire", (rec.item_name or "").lower())

    def test_blue_monster_only_seal_word_blocks_wire_nuts(self) -> None:
        refs = _refs_consumables()
        # Minimal OCR: seal but no "tape" and _is_tape_line may be false
        desc = '3/4" Blue Monster PTFE Thread Seal 70886'
        rec, _, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertNotEqual((rec.item_name or "").lower(), "wire nuts - blue")

    def test_supplier_code_only_field(self) -> None:
        refs = _refs_consumables()
        desc = '3/4" Blue Monster PTFE Thread Seal Tape'
        rec, conf, note = refs.match_line(desc, "70886")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "70886")
        self.assertIn("supplier item code", note.lower())

    def test_white_seal_weld_on_not_blue_monster_tape_or_dope(self) -> None:
        refs = _refs_consumables()
        desc = "WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON"
        rec, conf, _ = refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        self.assertGreaterEqual(conf, 0.85)
        name = (rec.item_name or "").lower()
        self.assertIn("white seal", name)
        self.assertIn("weld on", name)
        self.assertNotIn("tape", name)
        self.assertNotIn("wire", name)


class TestConsumableCatalogIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.refs = ReferenceData()
        catalog = ROOT / "exports" / "catalog_items.csv"
        if not catalog.is_file():
            cls.refs = None
            return
        cls.refs.load()

    def test_white_seal_still_not_wire_nuts(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        rec, conf, _ = self.refs.match_line("WHITE SEAL PLUS PIPE DOPE", None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertNotIn("wire nut", name)

    def test_white_seal_with_ptfe_weld_on_from_real_catalog(self) -> None:
        if self.refs is None:
            self.skipTest("exports/catalog_items.csv not present")
        desc = "WHITE SEAL PLUS PIPE DOPE WITH PTFE PINT WELD ON"
        rec, conf, _ = self.refs.match_line(desc, None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertTrue(
            "white seal" in name or "weld on" in name,
            msg=f"Expected Weld On / White Seal, got {rec.item_name!r}",
        )
        self.assertNotIn("tape", name)


if __name__ == "__main__":
    unittest.main()

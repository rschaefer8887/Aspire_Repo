"""Unit tests for IDP helpers (no OpenAI)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_costs import (  # noqa: E402
    apply_tax,
    effective_invoice_total,
    taxed_line_total,
)
from idp_excel import output_filename  # noqa: E402
from idp_fowler_freight import normalize_fowler_invoice_number
from idp_openai import format_invoice_number, resolve_openai_model  # noqa: E402
from idp_paths import is_import_excluded_xlsx, sanitize_filename_part  # noqa: E402
from idp_reference import (  # noqa: E402
    ReferenceData,
    _catalog_matches_product_hint,
    _code_appears_in_description,
    _code_tokens_from_text,
    _leading_code_token,
    _norm,
    _product_hint,
)
from idp_vendor_profiles import (  # noqa: E402
    DEFAULT_PROFILE,
    HD_FOWLER_PROFILE,
    vendor_profile_for,
)
from idp_review import (  # noqa: E402
    ReviewLine,
    ReviewSession,
    build_catalog_label_index,
    catalog_label,
    parse_catalog_label,
    resolve_catalog_label,
    session_to_extraction,
)


class TestIdpHelpers(unittest.TestCase):
    def test_format_invoice_number_appends_inv(self) -> None:
        self.assertEqual(format_invoice_number("12345"), "12345-INV")
        self.assertEqual(format_invoice_number("12345-INV"), "12345-INV")

    def test_normalize_fowler_invoice_number_fixes_leading_one(self) -> None:
        self.assertEqual(normalize_fowler_invoice_number("17343986"), "I7343986")
        self.assertEqual(normalize_fowler_invoice_number("17343986-INV"), "I7343986-INV")
        self.assertEqual(normalize_fowler_invoice_number("I7343986"), "I7343986")
        self.assertEqual(normalize_fowler_invoice_number("i7343986"), "I7343986")

    def test_apply_tax_rounds_three_decimals(self) -> None:
        self.assertEqual(apply_tax(100.0, profile=HD_FOWLER_PROFILE), 106.0)
        self.assertEqual(
            apply_tax(10.555, profile=HD_FOWLER_PROFILE),
            round(10.555 * 1.06, 3),
        )
        self.assertEqual(apply_tax(100.0, profile=DEFAULT_PROFILE), 100.0)

    def test_sanitize_filename(self) -> None:
        self.assertNotIn("/", sanitize_filename_part("A/B Corp"))

    def test_sanitize_filename_strips_braced_suffix(self) -> None:
        name = sanitize_filename_part("H.D. Fowler Company {Turf}")
        self.assertNotIn("{", name)
        self.assertNotIn("}", name)
        self.assertNotIn("Turf", name)
        self.assertIn("Fowler", name)

    def test_output_filename_hd_fowler_without_turf(self) -> None:
        name = output_filename("H.D. Fowler Company {Turf}", "I7325981-INV")
        self.assertEqual(name, "H.D._Fowler_Company_I7325981-INV.xlsx")

    def test_template_excluded_from_import(self) -> None:
        self.assertTrue(is_import_excluded_xlsx(Path("PR Template.xlsx")))
        self.assertTrue(is_import_excluded_xlsx(Path("Vendor_123-INV-imported.xlsx")))
        self.assertFalse(is_import_excluded_xlsx(Path("Vendor_123-INV.xlsx")))

    def test_output_filename(self) -> None:
        name = output_filename("Ace Hardware", "999-INV")
        self.assertTrue(name.endswith(".xlsx"))
        self.assertIn("Ace", name)

    def test_resolve_openai_model_numeric_choices(self) -> None:
        self.assertEqual(resolve_openai_model("1"), "gpt-4o")
        self.assertEqual(resolve_openai_model("2"), "gpt-4.1")
        self.assertEqual(resolve_openai_model("3"), "gpt-4.1-mini")

    def test_resolve_openai_model_aliases(self) -> None:
        self.assertEqual(resolve_openai_model("4o"), "gpt-4o")
        self.assertEqual(resolve_openai_model("mini"), "gpt-4.1-mini")

    def test_load_vendors_csv(self) -> None:
        refs = ReferenceData()
        refs._load_vendors()
        self.assertGreater(len(refs.vendors), 10)

    def test_leading_code_token_extracts_letter_skus(self) -> None:
        self.assertEqual(_leading_code_token("XFFCOUP 17MM COUPLING"), "XFFCOUP")
        self.assertEqual(_leading_code_token('XQ 1/4" DRIP TUBE'), "XQ")

    def test_code_tokens_include_all_letter_skus(self) -> None:
        tokens = _code_tokens_from_text("XFFCOUP 17MM COUPLING", None)
        self.assertIn("XFFCOUP", tokens)

    def test_coupler_hint_matches_coupling_in_catalog(self) -> None:
        self.assertTrue(
            _catalog_matches_product_hint("coupler", "barb coupling adapter 17mm")
        )

    def test_code_appears_in_description(self) -> None:
        self.assertTrue(
            _code_appears_in_description("XFFCOUP", "XFFCOUP 17MM COUPLING")
        )
        self.assertFalse(
            _code_appears_in_description("XQ", "XEMT-6XERI EMITTER")
        )

    def test_match_xffcoup_line(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line("XFFCOUP 17MM COUPLING BARB FITTING", None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "XFFCOUP")
        self.assertGreaterEqual(conf, 0.85)

    def test_match_xfftee_line(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line("XFFTEE 17MM TEE BARB FITTING", None)
        self.assertIsNotNone(rec)
        self.assertIn(rec.item_code, ("RBXXFFTEE", "XXFFTEE"))
        self.assertGreaterEqual(conf, 0.85)

    def test_no_hub_torque_wrench_does_not_match_pipe_wrench(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line("NO HUB TORQUE WRENCH", None)
        if rec is not None:
            self.assertNotIn("Pipe Wrench", rec.item_name or "")
        self.assertLess(conf, 0.85)

    def test_white_seal_plus_pipe_dope_matches_sealant_not_wire(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line("WHITE SEAL PLUS PIPE DOPE", None)
        self.assertIsNotNone(rec)
        name = (rec.item_name or "").lower()
        self.assertNotIn("wire", name)
        self.assertTrue(
            "white seal" in name or "pipe dope" in name,
            msg=f"Expected sealant, got {rec.item_name!r}",
        )
        self.assertGreaterEqual(conf, 0.85)

    def test_item_code_in_description_beats_name_match(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, note = refs.match_line("PGV-101G 1\" GLOBE VALVE W/FLOW CONTROL", None)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.item_code, "PGV-101G")
        self.assertGreaterEqual(conf, 0.98)
        self.assertIn("item code", note.lower())

    def test_norm_expands_galv_abbreviation(self) -> None:
        self.assertIn("galvanized", _norm("Galv. Tee - 1\""))
        self.assertIn("galvanized", _norm("GALVANIZED nipple"))
        self.assertIn("galvanized", _norm("1 INCH GALV COUPLING"))

    def test_galvanized_invoice_matches_galv_catalog_name(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line(
            '1" SCH 40 GALVANIZED MALE INSERT ADAPTER IMPORT',
            None,
        )
        self.assertIsNotNone(rec)
        self.assertIn("Galv.", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.85)

    def test_galv_abbrev_invoice_matches_galvanized_catalog(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line(
            '1" GALV. MALE INSERT ADAPTER SCH 40',
            None,
        )
        self.assertIsNotNone(rec)
        self.assertIn("Galv.", rec.item_name or "")
        self.assertGreaterEqual(conf, 0.85)

    def test_product_hint_tee_uses_word_boundary(self) -> None:
        self.assertEqual(_product_hint("1 GALV. TEE"), "tee")
        self.assertEqual(_product_hint("TEE, 1 INCH"), "tee")
        self.assertIsNone(_product_hint("STEELYARD FITTING"))

    def test_catalog_tee_hint_requires_word_boundary(self) -> None:
        self.assertTrue(_catalog_matches_product_hint("tee", "galv. tee - 1"))
        self.assertFalse(_catalog_matches_product_hint("tee", "steelyard fitting"))

    def test_galv_tee_invoice_matches_galv_tee_catalog(self) -> None:
        refs = ReferenceData()
        refs.load()
        rec, conf, _ = refs.match_line('1" GALV. TEE', None)
        self.assertIsNotNone(rec)
        self.assertIn("Galv. Tee", rec.item_name or "")
        self.assertIn('1"', rec.item_name or "")
        self.assertGreaterEqual(conf, 0.85)

    def test_parse_catalog_label_name_only(self) -> None:
        self.assertEqual(parse_catalog_label("Laborer"), (None, "Laborer"))

    def test_parse_catalog_label_with_code(self) -> None:
        self.assertEqual(
            parse_catalog_label("XFFCOUP | RBXFFCOUP"),
            ("XFFCOUP", "RBXFFCOUP"),
        )

    def test_resolve_catalog_label_uses_index(self) -> None:
        refs = ReferenceData()
        refs.load()
        index = build_catalog_label_index(refs)
        rec = next(r for r in refs.inventory if (r.item_code or "") == "XFFCOUP")
        lab = catalog_label(rec)
        code, name = resolve_catalog_label(lab, index)
        self.assertEqual(code, "XFFCOUP")
        self.assertTrue(name)

    def test_resolve_catalog_label_name_only_from_index(self) -> None:
        refs = ReferenceData()
        refs.load()
        index = build_catalog_label_index(refs)
        rec = next(r for r in refs.inventory if not (r.item_code or "").strip())
        lab = catalog_label(rec)
        code, name = resolve_catalog_label(lab, index)
        self.assertIsNone(code)
        self.assertEqual(name, (rec.item_name or rec.item_alternate_name or "").strip())

    def test_catalog_loads_material_items_only(self) -> None:
        refs = ReferenceData()
        refs.load()
        self.assertGreater(len(refs.inventory), 100)
        self.assertTrue(all(r.item_type.lower() == "material" for r in refs.inventory))
        names = {(r.item_name or "").lower() for r in refs.inventory}
        self.assertNotIn("laborer", names)

    def test_taxed_line_total_includes_tax(self) -> None:
        self.assertEqual(
            taxed_line_total(10, 1.25, profile=HD_FOWLER_PROFILE), 13.25
        )
        self.assertEqual(
            taxed_line_total(10, 1.25, profile=DEFAULT_PROFILE), 12.5
        )

    def test_vendor_profile_hd_fowler(self) -> None:
        prof = vendor_profile_for("H.D. Fowler Company {Turf}")
        self.assertEqual(prof.profile_id, "hd_fowler")
        self.assertTrue(prof.reconcile_to_invoice_total)
        self.assertEqual(prof.tax_multiplier, 1.06)
        self.assertFalse(prof.skip_receipt_item_consolidation)

    def test_vendor_profile_idaho_sod(self) -> None:
        prof = vendor_profile_for("Idaho Sod")
        self.assertEqual(prof.profile_id, "idaho_sod")
        self.assertTrue(prof.reconcile_to_invoice_total)
        self.assertFalse(prof.skip_receipt_item_consolidation)

    def test_vendor_profile_cedron_sod(self) -> None:
        prof = vendor_profile_for("Cedron Sod")
        self.assertEqual(prof.profile_id, "cedron_sod")
        self.assertTrue(prof.reconcile_to_invoice_total)
        self.assertFalse(prof.skip_receipt_item_consolidation)

    def test_vendor_profile_default_for_unknown(self) -> None:
        prof = vendor_profile_for("Acme Supply Co")
        self.assertEqual(prof.profile_id, "default")
        self.assertFalse(prof.reconcile_to_invoice_total)
        self.assertEqual(prof.tax_multiplier, 1.0)

    def test_effective_invoice_total_subtracts_excluded_lines(self) -> None:
        lines = [
            ReviewLine("TOOL", 1, 100.0, excluded=True),
            ReviewLine("PART", 2, 50.0, excluded=False),
        ]
        adjusted = effective_invoice_total(
            200.0,
            lines,
            profile=HD_FOWLER_PROFILE,
        )
        self.assertEqual(
            adjusted,
            round(
                200.0 - taxed_line_total(1, 100.0, profile=HD_FOWLER_PROFILE),
                2,
            ),
        )

    def test_session_to_extraction_omits_excluded_lines(self) -> None:
        session = ReviewSession(
            session_id="test",
            created_at="2026-01-01",
            pdf_path="x.pdf",
            pdf_name="x.pdf",
            invoice_date="2026-01-01",
            vendor_raw="Vendor",
            vendor_name="MD Internal Vendor",
            vendor_confidence=0.95,
            invoice_number_raw="123",
            invoice_total=100.0,
            invoice_total_original=113.25,
            lines=[
                ReviewLine(
                    "NO HUB TORQUE WRENCH",
                    1,
                    12.5,
                    excluded=True,
                ),
                ReviewLine(
                    "XQ DRIP TUBE",
                    1,
                    10.0,
                    item_code="XQ",
                    item_name="Drip Tube",
                    excluded=False,
                ),
            ],
        )
        result = session_to_extraction(session)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].item_code, "XQ")
        self.assertEqual(
            result.invoice_total,
            round(113.25 - taxed_line_total(1, 12.5, profile=DEFAULT_PROFILE), 2),
        )

    def test_session_to_extraction_rejects_all_excluded(self) -> None:
        session = ReviewSession(
            session_id="test",
            created_at="2026-01-01",
            pdf_path="x.pdf",
            pdf_name="x.pdf",
            invoice_date=None,
            vendor_raw="Vendor",
            vendor_name="Vendor",
            vendor_confidence=1.0,
            invoice_number_raw="123",
            invoice_total=50.0,
            lines=[ReviewLine("ITEM", 1, 10.0, excluded=True)],
        )
        with self.assertRaises(ValueError):
            session_to_extraction(session)


if __name__ == "__main__":
    unittest.main()

"""HD Fowler invoice line match log (Excel via xlwings)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_match_log import (  # noqa: E402
    FIELDNAMES,
    append_hd_fowler_match_log_from_extraction,
    invoice_numbers_in_log,
    pdf_name_is_hd_fowler,
    rows_to_values,
    should_log_hd_fowler,
)
from idp_openai import ExtractionResult, LineMatch  # noqa: E402


class TestMatchLogHelpers(unittest.TestCase):
    def test_should_log_fowler_only(self) -> None:
        self.assertTrue(should_log_hd_fowler("H.D. Fowler Company {Turf}", None))
        self.assertFalse(should_log_hd_fowler("Idaho Sod", None))

    def test_pdf_name_is_hd_fowler(self) -> None:
        self.assertTrue(
            pdf_name_is_hd_fowler(Path("Aspire-HD Fowler-I7331698-INV__06042026.pdf"))
        )
        self.assertFalse(
            pdf_name_is_hd_fowler(Path("Aspire-Idaho Sod-35JNVB.pdf"))
        )

    def test_rows_to_values_column_order(self) -> None:
        row = {name: name for name in FIELDNAMES}
        values = rows_to_values([row])
        self.assertEqual(values, [[name for name in FIELDNAMES]])


class TestMatchLogAppend(unittest.TestCase):
    def test_append_fowler_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "HD Fowler Item Match Log.xlsx"
            import idp_match_log as ml

            original_path = ml.hd_fowler_match_log_path
            appended: list[tuple[Path, list[list[str]], str]] = []

            def fake_append(path: Path, values: list[list[str]], *, sheet_name: str) -> None:
                appended.append((path, values, sheet_name))

            ml.hd_fowler_match_log_path = lambda: log_path  # type: ignore[method-assign]
            try:
                with patch.object(ml, "_append_values_with_xlwings", side_effect=fake_append):
                    result = ExtractionResult(
                        invoice_date=date(2026, 6, 4),
                        vendor_raw="H.D. Fowler",
                        vendor_name="H.D. Fowler Company {Turf}",
                        vendor_id=1,
                        vendor_confidence=0.99,
                        vendor_rationale="",
                        invoice_number_raw="I7331698",
                        invoice_total=100.0,
                        lines=[
                            LineMatch(
                                description_raw='1" PVC INSERT TEE',
                                quantity=2,
                                unit_price=1.5,
                                uom_raw="EA",
                                item_code="TEE1",
                                item_name='1" PVC Insert Tee',
                                confidence=0.95,
                                rationale="One-off: test",
                            )
                        ],
                    )
                    n = append_hd_fowler_match_log_from_extraction(
                        result,
                        pdf_name="test.pdf",
                    )
                self.assertEqual(n, 1)
                self.assertEqual(len(appended), 1)
                self.assertEqual(appended[0][0], log_path)
                self.assertEqual(appended[0][2], ml.DEFAULT_SHEET_NAME)
                row = dict(zip(FIELDNAMES, appended[0][1][0], strict=True))
                self.assertEqual(row["invoice_number"], "I7331698-INV")
                self.assertNotIn("source", row)
            finally:
                ml.hd_fowler_match_log_path = original_path  # type: ignore[method-assign]

    def test_skip_non_fowler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "HD Fowler Item Match Log.xlsx"
            import idp_match_log as ml

            original_path = ml.hd_fowler_match_log_path
            ml.hd_fowler_match_log_path = lambda: log_path  # type: ignore[method-assign]
            try:
                with patch.object(ml, "_append_values_with_xlwings") as mock_append:
                    result = ExtractionResult(
                        invoice_date=None,
                        vendor_raw="Idaho Sod",
                        vendor_name="Idaho Sod",
                        vendor_id=1,
                        vendor_confidence=0.99,
                        vendor_rationale="",
                        invoice_number_raw="35JNVB",
                        lines=[
                            LineMatch(
                                description_raw="Sod",
                                quantity=1,
                                unit_price=1.0,
                            )
                        ],
                    )
                    n = append_hd_fowler_match_log_from_extraction(
                        result, pdf_name="sod.pdf"
                    )
                self.assertEqual(n, 0)
                mock_append.assert_not_called()
            finally:
                ml.hd_fowler_match_log_path = original_path  # type: ignore[method-assign]

    def test_invoice_numbers_in_log_reads_sheet(self) -> None:
        import idp_match_log as ml

        with patch.object(
            ml,
            "_read_invoice_numbers_with_xlwings",
            return_value={"I7331698-INV", "I7000000-INV"},
        ):
            found = invoice_numbers_in_log(Path("dummy.xlsx"))
        self.assertEqual(found, {"I7331698-INV", "I7000000-INV"})


class TestMatchLogXlwingsIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.log_path = ROOT / "exports" / "HD Fowler Item Match Log.xlsx"
        if not cls.log_path.is_file():
            cls.log_path = None

    def test_read_existing_log_invoice_numbers(self) -> None:
        if self.log_path is None:
            self.skipTest("exports/HD Fowler Item Match Log.xlsx not present")
        found = invoice_numbers_in_log(self.log_path)
        self.assertIsInstance(found, set)
        self.assertGreater(len(found), 0)


class TestMatchLogSheetHelpers(unittest.TestCase):
    def test_normalize_column_values(self) -> None:
        import idp_match_log as ml

        self.assertEqual(ml._normalize_column_values("I7331698-INV"), ["I7331698-INV"])
        self.assertEqual(
            ml._normalize_column_values([["A"], ["B"], [None]]),
            ["A", "B"],
        )

    def test_read_invoice_numbers_from_sheet(self) -> None:
        import idp_match_log as ml

        data_range = MagicMock()
        data_range.value = ["I7331698-INV", "I7000000-INV"]
        ws = MagicMock()
        ws.range.return_value = data_range

        with patch.object(ml, "_header_values", return_value=FIELDNAMES):
            with patch.object(ml, "_last_used_row", return_value=4):
                found = ml._read_invoice_numbers_from_sheet(ws)
        self.assertEqual(found, {"I7331698-INV", "I7000000-INV"})


if __name__ == "__main__":
    unittest.main()

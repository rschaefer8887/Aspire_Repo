"""Batch attach/receive prompt resolution for bulk import."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_attachments import resolve_batch_attach_decision  # noqa: E402
from aspire_receipts import resolve_batch_receive_decision  # noqa: E402


class TestResolveBatchAttach(unittest.TestCase):
    def test_single_file_prompts_per_receipt(self) -> None:
        self.assertIsNone(
            resolve_batch_attach_decision(
                1, dry_run=False, yes=False, no=False, bulk_mode=False
            )
        )

    def test_single_file_yes_attach(self) -> None:
        self.assertTrue(
            resolve_batch_attach_decision(
                1, dry_run=False, yes=True, no=False, bulk_mode=False
            )
        )

    def test_bulk_yes_attach(self) -> None:
        self.assertTrue(
            resolve_batch_attach_decision(
                12, dry_run=False, yes=True, no=False, bulk_mode=True
            )
        )

    def test_bulk_no_attach_flag_skips_all(self) -> None:
        self.assertFalse(
            resolve_batch_attach_decision(
                12, dry_run=False, yes=False, no=True, bulk_mode=True
            )
        )

    @patch("aspire_attachments.prompt_batch_upload_pdfs", return_value=True)
    def test_bulk_prompt_yes_attaches_all(self, mock_prompt: unittest.mock.MagicMock) -> None:
        decision = resolve_batch_attach_decision(
            12, dry_run=False, yes=False, no=False, bulk_mode=True
        )
        self.assertTrue(decision)
        mock_prompt.assert_called_once_with(12)

    @patch("aspire_attachments.prompt_batch_upload_pdfs", return_value=False)
    def test_bulk_prompt_no_prompts_each(self, mock_prompt: unittest.mock.MagicMock) -> None:
        decision = resolve_batch_attach_decision(
            12, dry_run=False, yes=False, no=False, bulk_mode=True
        )
        self.assertIsNone(decision)
        mock_prompt.assert_called_once_with(12)

    def test_bulk_dry_run_returns_per_receipt_mode(self) -> None:
        decision = resolve_batch_attach_decision(
            12, dry_run=True, yes=False, no=False, bulk_mode=True
        )
        self.assertIsNone(decision)


class TestResolveBatchReceive(unittest.TestCase):
    def test_single_file_prompts_per_receipt(self) -> None:
        self.assertIsNone(
            resolve_batch_receive_decision(
                1, dry_run=False, yes=False, no=False, bulk_mode=False
            )
        )

    @patch("aspire_receipts.prompt_batch_receive_receipts", return_value=True)
    def test_bulk_prompt_yes_receives_all(self, mock_prompt: unittest.mock.MagicMock) -> None:
        decision = resolve_batch_receive_decision(
            5, dry_run=False, yes=False, no=False, bulk_mode=True
        )
        self.assertTrue(decision)
        mock_prompt.assert_called_once_with(5)

    @patch("aspire_receipts.prompt_batch_receive_receipts", return_value=False)
    def test_bulk_prompt_no_prompts_each(self, mock_prompt: unittest.mock.MagicMock) -> None:
        decision = resolve_batch_receive_decision(
            5, dry_run=False, yes=False, no=False, bulk_mode=True
        )
        self.assertIsNone(decision)
        mock_prompt.assert_called_once_with(5)

    def test_bulk_no_receive_flag_skips_all(self) -> None:
        self.assertFalse(
            resolve_batch_receive_decision(
                5, dry_run=False, yes=False, no=True, bulk_mode=True
            )
        )


if __name__ == "__main__":
    unittest.main()

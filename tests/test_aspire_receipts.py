"""Tests for receipt receive helpers (no API)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_receipts import (  # noqa: E402
    receipt_is_received,
    receive_date_label,
)


class TestAspireReceipts(unittest.TestCase):
    def test_receive_date_label_defaults_to_today(self) -> None:
        self.assertEqual(receive_date_label(), date.today().strftime("%m/%d/%Y"))

    def test_receive_date_label_explicit(self) -> None:
        self.assertEqual(receive_date_label(date(2026, 6, 3)), "06/03/2026")

    def test_receipt_is_received_by_date(self) -> None:
        self.assertTrue(
            receipt_is_received({"ReceivedDate": "2026-06-03T12:00:00Z"})
        )

    def test_receipt_is_received_by_status_name(self) -> None:
        self.assertTrue(
            receipt_is_received({"ReceiptStatusName": "Received"})
        )

    def test_receipt_not_received(self) -> None:
        self.assertFalse(
            receipt_is_received(
                {"ReceiptStatusName": "Ready", "ReceivedDate": None}
            )
        )


if __name__ == "__main__":
    unittest.main()

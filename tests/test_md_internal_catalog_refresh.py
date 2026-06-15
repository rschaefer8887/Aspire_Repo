"""MD Internal catalog refresh prompt on import."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_catalog_refresh import (  # noqa: E402
    MdInternalCatalogState,
    maybe_refresh_catalog_for_md_internal,
)
from idp_vendor_prefs import md_internal_vendor_id  # noqa: E402


class TestMdInternalCatalogRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.client = MagicMock()
        self.lookups = MagicMock()
        self.state = MdInternalCatalogState()

    def test_non_md_internal_vendor_no_op(self) -> None:
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=99,
            state=self.state,
            dry_run=False,
            no_catalog_prompt=False,
            yes_refresh_catalog=False,
            no_refresh_catalog=False,
        )
        self.assertIsNone(self.state.decision)
        self.lookups.refresh_catalog_indexes.assert_not_called()

    @patch("aspire_catalog_refresh.refresh_catalog_for_md_internal_import")
    @patch("aspire_catalog_refresh.prompt_md_internal_catalog_refresh", return_value=True)
    def test_md_internal_prompt_yes_refreshes(
        self, _mock_prompt: unittest.mock.MagicMock, mock_refresh: unittest.mock.MagicMock
    ) -> None:
        mock_refresh.return_value = 100
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=md_internal_vendor_id(),
            state=self.state,
            dry_run=False,
            no_catalog_prompt=False,
            yes_refresh_catalog=False,
            no_refresh_catalog=False,
        )
        self.assertEqual(self.state.decision, "refresh")
        mock_refresh.assert_called_once()

    @patch("aspire_catalog_refresh.refresh_catalog_for_md_internal_import")
    @patch("aspire_catalog_refresh.prompt_md_internal_catalog_refresh", return_value=False)
    def test_md_internal_prompt_no_skips(
        self, _mock_prompt: unittest.mock.MagicMock, mock_refresh: unittest.mock.MagicMock
    ) -> None:
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=md_internal_vendor_id(),
            state=self.state,
            dry_run=False,
            no_catalog_prompt=False,
            yes_refresh_catalog=False,
            no_refresh_catalog=False,
        )
        self.assertEqual(self.state.decision, "skip")
        mock_refresh.assert_not_called()

    @patch("aspire_catalog_refresh.refresh_catalog_for_md_internal_import")
    def test_yes_refresh_catalog_flag(self, mock_refresh: unittest.mock.MagicMock) -> None:
        mock_refresh.return_value = 50
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=md_internal_vendor_id(),
            state=self.state,
            dry_run=False,
            no_catalog_prompt=False,
            yes_refresh_catalog=True,
            no_refresh_catalog=False,
        )
        self.assertEqual(self.state.decision, "refresh")
        mock_refresh.assert_called_once()

    def test_second_md_internal_file_reuses_refresh_decision(self) -> None:
        self.state.decision = "refresh"
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=md_internal_vendor_id(),
            state=self.state,
            dry_run=False,
            no_catalog_prompt=False,
            yes_refresh_catalog=False,
            no_refresh_catalog=False,
        )
        self.lookups.refresh_catalog_indexes.assert_not_called()

    def test_dry_run_does_not_refresh(self) -> None:
        maybe_refresh_catalog_for_md_internal(
            self.client,
            self.lookups,
            vendor_id=md_internal_vendor_id(),
            state=self.state,
            dry_run=True,
            no_catalog_prompt=False,
            yes_refresh_catalog=False,
            no_refresh_catalog=False,
        )
        self.assertEqual(self.state.decision, "skip")


if __name__ == "__main__":
    unittest.main()

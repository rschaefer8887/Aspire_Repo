"""Shared paths for IDP and receipt import."""

from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def receipts_ready_dir() -> Path:
    env = os.environ.get("ASPIRE_RECEIPTS_READY", "").strip()
    if env:
        return Path(env)
    return ROOT / "Receipts - Ready"


def invoices_incoming_dir() -> Path:
    env = os.environ.get("IDP_INVOICES_INCOMING", "").strip()
    if env:
        return Path(env)
    return receipts_ready_dir() / "Invoices - Ready"


def invoices_processed_dir() -> Path:
    env = os.environ.get("IDP_INVOICES_PROCESSED", "").strip()
    if env:
        return Path(env)
    return receipts_ready_dir() / "Invoices - Processed" / "Complete"


def review_dashboard_path() -> Path:
    env = os.environ.get("IDP_REVIEW_DASHBOARD", "").strip()
    if env:
        return Path(env)
    return receipts_ready_dir() / "review_dashboard.txt"


def vendors_csv_path() -> Path:
    env = os.environ.get("IDP_VENDORS_CSV", "").strip()
    if env:
        return Path(env)
    return ROOT / "exports" / "vendors.csv"


def catalog_items_csv_path() -> Path:
    """Aspire catalog export used for IDP line-item matching (refresh via export_reference_data)."""
    env = os.environ.get("IDP_CATALOG_CSV", "").strip()
    if env:
        return Path(env)
    return ROOT / "exports" / "catalog_items.csv"


def catalog_item_type_filter() -> str:
    """Only catalog rows with this ItemType are used for IDP matching (default: Material)."""
    return os.environ.get("IDP_CATALOG_ITEM_TYPE", "Material").strip()


def review_pending_dir() -> Path:
    env = os.environ.get("IDP_REVIEW_PENDING", "").strip()
    if env:
        return Path(env)
    return receipts_ready_dir() / "review" / "pending"


def inventory_master_path() -> Path:
    """Deprecated alias — IDP uses catalog_items.csv only."""
    return catalog_items_csv_path()


def excel_template_path() -> Path:
    env = os.environ.get("ASPIRE_EXCEL_TEMPLATE", "").strip()
    if env:
        return ROOT / env if not Path(env).is_absolute() else Path(env)
    return receipts_ready_dir() / "PR Template.xlsx"


def default_branch() -> str:
    return os.environ.get("ASPIRE_DEFAULT_BRANCH", "MD Nursery & Landscaping").strip()


def confidence_threshold() -> float:
    try:
        return float(os.environ.get("IDP_CONFIDENCE_THRESHOLD", "0.85"))
    except ValueError:
        return 0.85


def tax_multiplier() -> float:
    try:
        return float(os.environ.get("IDP_TAX_MULTIPLIER", "1.06"))
    except ValueError:
        return 1.06


def sanitize_filename_part(text: str, max_len: int = 80) -> str:
    s = str(text).strip()
    s = re.sub(r"\{[^}]*\}", "", s)
    s = re.sub(r'[<>:"/\\|?*{}]', "_", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("._")
    return (s[:max_len] if s else "unknown")


def is_import_excluded_xlsx(path: Path) -> bool:
    name = path.name.lower()
    if "template" in name:
        return True
    return name.endswith("-imported.xlsx")

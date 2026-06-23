"""Per-vendor rules for tax and Excel total reconciliation (IDP → Aspire import)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


def _tax_multiplier_from_env(default: float) -> float:
    try:
        return float(os.environ.get("IDP_TAX_MULTIPLIER", str(default)))
    except ValueError:
        return default


def _norm_key(name: str) -> str:
    from idp_vendor_prefs import normalize_vendor_key

    return normalize_vendor_key(name)


@dataclass(frozen=True)
class VendorProfile:
    """How to turn extracted invoice lines into Aspire receipt Excel costs."""

    profile_id: str
    display_name: str
    tax_multiplier: float
    reconcile_to_invoice_total: bool
    unit_prices_are_pre_tax: bool
    skip_receipt_item_consolidation: bool = False

    @property
    def applies_tax(self) -> bool:
        return abs(self.tax_multiplier - 1.0) > 1e-9

    def tax_percent_label(self) -> str:
        if not self.applies_tax:
            return "no tax adjustment"
        pct = round((self.tax_multiplier - 1.0) * 100)
        return f"{pct}% tax on unit costs"


DEFAULT_PROFILE = VendorProfile(
    profile_id="default",
    display_name="Default",
    tax_multiplier=1.0,
    reconcile_to_invoice_total=False,
    unit_prices_are_pre_tax=False,
)

HD_FOWLER_PROFILE = VendorProfile(
    profile_id="hd_fowler",
    display_name="H.D. Fowler",
    tax_multiplier=_tax_multiplier_from_env(1.06),
    reconcile_to_invoice_total=True,
    unit_prices_are_pre_tax=True,
    skip_receipt_item_consolidation=False,
)

IDAHO_SOD_PROFILE = VendorProfile(
    profile_id="idaho_sod",
    display_name="Idaho Sod",
    tax_multiplier=1.0,
    reconcile_to_invoice_total=True,
    unit_prices_are_pre_tax=False,
    skip_receipt_item_consolidation=False,
)

CEDRON_SOD_PROFILE = VendorProfile(
    profile_id="cedron_sod",
    display_name="Cedron Sod",
    tax_multiplier=1.0,
    reconcile_to_invoice_total=True,
    unit_prices_are_pre_tax=False,
    skip_receipt_item_consolidation=False,
)

# Normalized vendor keys (from Aspire VendorName) → profile.
_VENDOR_PROFILE_BY_KEY: dict[str, VendorProfile] = {
    _norm_key("H.D. Fowler Company {Turf}"): HD_FOWLER_PROFILE,
    _norm_key("H.D. Fowler Company"): HD_FOWLER_PROFILE,
    _norm_key("Idaho Sod"): IDAHO_SOD_PROFILE,
    _norm_key("Cedron Sod"): CEDRON_SOD_PROFILE,
}


def vendor_profile_for(
    vendor_name: str | None,
    vendor_raw: str | None = None,
) -> VendorProfile:
    """Resolve vendor-specific tax/reconcile rules; unknown vendors use DEFAULT_PROFILE."""
    for candidate in (vendor_name, vendor_raw):
        if not candidate:
            continue
        key = _norm_key(candidate)
        if key in _VENDOR_PROFILE_BY_KEY:
            return _VENDOR_PROFILE_BY_KEY[key]
        if "fowler" in key:
            return HD_FOWLER_PROFILE
        if "idaho" in key and "sod" in key:
            return IDAHO_SOD_PROFILE
        if "cedron" in key and "sod" in key:
            return CEDRON_SOD_PROFILE
    return DEFAULT_PROFILE


def is_sod_vendor_profile(profile: VendorProfile) -> bool:
    return profile.profile_id in (
        IDAHO_SOD_PROFILE.profile_id,
        CEDRON_SOD_PROFILE.profile_id,
    )


def register_vendor_profile(vendor_name: str, profile: VendorProfile) -> None:
    """Register an exact Aspire vendor name (after {_norm_key}) for lookups."""
    _VENDOR_PROFILE_BY_KEY[_norm_key(vendor_name)] = profile

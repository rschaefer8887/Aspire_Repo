"""Preferred Aspire vendor names for IDP and import (e.g. HD Fowler Turf vs Waterworks)."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from idp_reference import ReferenceData, VendorRecord

_DEFAULT_HD_FOWLER_VENDOR = "H.D. Fowler Company {Turf}"
_DEFAULT_IDAHO_SOD_VENDOR = "Idaho Sod"


def hd_fowler_preferred_vendor_name() -> str:
    return (
        os.environ.get("IDP_HD_FOWLER_VENDOR_NAME", "").strip()
        or _DEFAULT_HD_FOWLER_VENDOR
    )


def idaho_sod_preferred_vendor_name() -> str:
    return (
        os.environ.get("IDP_IDAHO_SOD_VENDOR_NAME", "").strip()
        or _DEFAULT_IDAHO_SOD_VENDOR
    )


def is_idaho_sod_vendor(name: str | None) -> bool:
    if not name:
        return False
    key = normalize_vendor_key(name)
    return "idaho" in key and "sod" in key


def normalize_vendor_key(name: str) -> str:
    """Lowercase vendor key; keeps {Turf}/{Waterworks} tags (do not strip braces)."""
    s = str(name).strip().lower()
    s = re.sub(r"\{([^}]*)\}", r" \1 ", s)
    return " ".join(s.split())


def is_hd_fowler_vendor(name: str | None) -> bool:
    if not name:
        return False
    return "fowler" in normalize_vendor_key(name)


def exclude_vendor_from_llm_list(vendor_name: str) -> bool:
    """Hide non-preferred HD Fowler variants from the OpenAI vendor pick list."""
    if not is_hd_fowler_vendor(vendor_name):
        return False
    return (
        normalize_vendor_key(vendor_name)
        != normalize_vendor_key(hd_fowler_preferred_vendor_name())
    )


def pick_preferred_vendor_match(
    matches: list[tuple[int, str]],
    query_text: str | None = None,
) -> tuple[int, str] | None:
    """
    When multiple (or wrong) HD Fowler vendors match, return the preferred Turf row.
    Returns None if this rule does not apply.
    """
    if not matches:
        return None
    if not (
        any(is_hd_fowler_vendor(name) for _, name in matches)
        or is_hd_fowler_vendor(query_text)
    ):
        return None
    pref_key = normalize_vendor_key(hd_fowler_preferred_vendor_name())
    for vid, name in matches:
        if normalize_vendor_key(name) == pref_key:
            return vid, name
    return None


def resolve_hd_fowler_vendor(
    refs: ReferenceData,
    vendor_name: str | None,
    vendor_raw: str | None = None,
) -> VendorRecord | None:
    """
    Resolve vendor from Aspire list; map any HD Fowler variant to preferred Turf vendor.
    """
    preferred_name = hd_fowler_preferred_vendor_name()
    rec: VendorRecord | None = None

    if vendor_name:
        rec = refs.lookup_vendor_record(vendor_name)

    if rec is None and vendor_raw and is_hd_fowler_vendor(vendor_raw):
        rec = refs.lookup_vendor_record(preferred_name)

    if not (
        is_hd_fowler_vendor(vendor_name)
        or is_hd_fowler_vendor(vendor_raw)
        or (rec and is_hd_fowler_vendor(rec.vendor_name))
    ):
        return rec

    turf = refs.lookup_vendor_record(preferred_name)
    return turf or rec


def resolve_idaho_sod_vendor(
    refs: ReferenceData,
    vendor_name: str | None,
    vendor_raw: str | None = None,
) -> VendorRecord | None:
    """Resolve vendor from Aspire list; map Idaho Sod variants to preferred name."""
    preferred_name = idaho_sod_preferred_vendor_name()
    rec: VendorRecord | None = None

    if vendor_name:
        rec = refs.lookup_vendor_record(vendor_name)

    if rec is None and vendor_raw and is_idaho_sod_vendor(vendor_raw):
        rec = refs.lookup_vendor_record(preferred_name)

    if not (
        is_idaho_sod_vendor(vendor_name)
        or is_idaho_sod_vendor(vendor_raw)
        or (rec and is_idaho_sod_vendor(rec.vendor_name))
    ):
        return rec

    preferred = refs.lookup_vendor_record(preferred_name)
    return preferred or rec

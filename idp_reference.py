"""Load vendor and catalog reference data for IDP matching."""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from idp_paths import catalog_items_csv_path, catalog_item_type_filter, vendors_csv_path
from idp_vendor_prefs import (
    exclude_vendor_from_llm_list,
    is_hd_fowler_vendor,
    is_idaho_sod_vendor,
    resolve_hd_fowler_vendor,
    resolve_idaho_sod_vendor,
)


def _norm(s: str) -> str:
    collapsed = " ".join(str(s).strip().lower().split())
    return _expand_matching_abbreviations(collapsed)


def _expand_matching_abbreviations(s: str) -> str:
    """Treat catalog abbreviations as their full terms for matching."""
    return re.sub(r"\bgalv\.?\b", "galvanized", s, flags=re.IGNORECASE)


_CODE_TOKEN_RE = re.compile(
    r"\b[A-Z][A-Z0-9]*(?:[-./][A-Z0-9]+)+\b|\b[A-Z]{2,}\d+[A-Z0-9]*\b|\b\d{5,}\b",
    re.IGNORECASE,
)

_BLOB_TOKEN_RE = re.compile(
    r"[A-Z]{2,}\d+[A-Z0-9-]*|[A-Z]{2,}-[A-Z0-9]+|[A-Z]{4,14}\b"
)

_TOKEN_STOPWORDS = frozenset(
    {
        "rain",
        "bird",
        "hunter",
        "action",
        "import",
        "sold",
        "each",
        "bag",
        "qty",
        "roll",
        "stem",
        "threaded",
        "galvanized",
        "sch",
        "fipt",
        "mip",
        "barb",
        "ixi",
        "ixmipt",
        "control",
        "flow",
        "globe",
        "yellow",
        "pop",
        "up",
        "company",
        "turf",
    }
)


def _token_priority(token: str) -> int:
    score = len(token)
    if re.search(r"[-./]", token):
        score += 20
    if re.search(r"\d", token):
        score += 15
    if token.lower() in _TOKEN_STOPWORDS:
        score -= 50
    return score


def _use_supplier_code(code: str, desc: str) -> bool:
    c = code.strip()
    if not c:
        return False
    if c.lower() in _norm(desc):
        return True
    if re.fullmatch(r"\d+", c) and c not in desc:
        return False
    return True


def _scrub_desc_for_code_match(desc: str) -> str:
    """Normalize description so trailing punctuation does not glue to part numbers."""
    scrubbed = _norm(desc)
    return re.sub(r"[,;.#]+", " ", scrubbed)


def _code_appears_in_description(code: str, desc: str) -> bool:
    c = re.sub(r"[^\w-]", "", _norm(code))
    if not c:
        return False
    scrubbed = _scrub_desc_for_code_match(desc)
    return bool(
        re.search(rf"(?<![a-z0-9]){re.escape(c)}(?![a-z0-9])", scrubbed)
    )


_COLOR_ONLY_WORDS = frozenset(
    {"blue", "red", "yellow", "green", "silver", "white", "black", "orange"}
)


def _is_tape_line(desc: str) -> bool:
    """True for real tape lines only (not pipe dope that mentions PTFE)."""
    if _is_pipe_dope_line(desc):
        return False
    d = _norm(desc)
    if "duct tape" in d:
        return True
    if re.search(r"\bthread\s+seal\s+tape\b", d):
        return True
    if re.search(r"\btape\b", desc, re.IGNORECASE):
        return True
    # Fowler/OCR often drops "tape"; Blue Monster + thread seal or PTFE is still tape.
    if "blue monster" in d and ("thread seal" in d or "ptfe" in d):
        return True
    return False


def _is_pipe_dope_line(desc: str) -> bool:
    d = _norm(desc)
    if "pipe dope" in d:
        return True
    if "weld on" in d or "weld-on" in d:
        return True
    if "white seal" in d:
        return True
    return False


def _skip_inch_size_overlap(desc: str) -> bool:
    """Tape/supply lines: do not match catalog rows only because of a shared inch size."""
    if _is_tape_line(desc):
        return True
    d = _norm(desc)
    return bool(re.search(r"\b(yds?|mil)\b", d))


def _consumable_blocks_catalog(desc_n: str, name_n: str) -> bool:
    """Reject fittings/wire nuts when the invoice line is clearly tape/supply."""
    if not _is_tape_line(desc_n):
        return False
    if re.search(r"\bnipple\b", name_n) and not re.search(r"\bnipple\b", desc_n):
        return True
    if "wire nut" in name_n and "wire nut" not in desc_n:
        return True
    return False


def _invoice_excludes_wire_nuts(desc_n: str, name_n: str) -> bool:
    """One-off: invoice lines with these words are never wire nuts."""
    if "wire nut" not in name_n:
        return False
    if "wire nut" in desc_n:
        return False
    if "blue monster" in desc_n:
        return True
    if re.search(r"\btape\b", desc_n):
        return True
    if "seal" in desc_n:
        return True
    return False


def _pipe_dope_blocks_catalog(desc_n: str, name_n: str) -> bool:
    """Reject thread-seal tape SKUs on pipe-dope invoice lines."""
    if not _is_pipe_dope_line(desc_n):
        return False
    if re.search(r"\btape\b", name_n):
        return True
    if "blue monster" in name_n and "white seal" in desc_n:
        return True
    return False


_IRRIGATION_STAPLES_ITEM_NAME = "Irrigation Staples"

_WORM_CLAMP_ITEM_NAME = "Worm Clamp"
_WORM_DRIVE_HOSE_CLAMP_RE = re.compile(
    r"worm\s+drive\s+hose\s+clamp",
    re.IGNORECASE,
)

# Fowler: 6" staples 11 GA jute matting sold by the box (1000 per box).
_IRRIGATION_STAPLES_INVOICE_RE = re.compile(
    r"staples?\s+11\s+ga\s+jute\s+matting|jute\s+matting.*sold\s+by\s+the\s+box",
    re.IGNORECASE | re.DOTALL,
)


def is_irrigation_staples_invoice_line(desc: str) -> bool:
    """True for Fowler jute matting box lines that map to Irrigation Staples."""
    return bool(_IRRIGATION_STAPLES_INVOICE_RE.search(desc or ""))


def is_worm_clamp_invoice_line(desc: str) -> bool:
    """True for worm drive hose clamp lines (size ignored → Worm Clamp)."""
    return bool(_WORM_DRIVE_HOSE_CLAMP_RE.search(desc or ""))


_VAN_NOZZLE_ITEM_NAME = "Rain Bird (VAN) Nozzle - All (or Hunter)"
_RAIN_BIRD_VAN_NOZZLE_RE = re.compile(
    r"\bvan\b.*variable\s+arc.*nozzle"
    r"|\brain\s+bird\b.*\bvan\b.*(?:variable\s+arc|nozzle)"
    r"|\bvan\b.*variable\s+arc.*nozzle.*\brain\s+bird\b",
    re.IGNORECASE,
)
_HUNTER_ADJUSTABLE_ARC_NOZZLE_RE = re.compile(
    r"adjustable\s+arc\s+nozzle.*\bhunter\b"
    r"|\bhunter\b.*adjustable\s+arc\s+nozzle"
    r"|\b\d{1,2}-A\b.*adjustable\s+arc\s+nozzle",
    re.IGNORECASE,
)


def is_van_nozzle_invoice_line(desc: str) -> bool:
    """Rain Bird VAN or Hunter adjustable arc nozzles → single catch-all catalog row."""
    d = desc or ""
    return bool(
        _RAIN_BIRD_VAN_NOZZLE_RE.search(d)
        or _HUNTER_ADJUSTABLE_ARC_NOZZLE_RE.search(d)
    )


def _catalog_is_van_nozzle_catch_all(name_n: str) -> bool:
    return _norm(_VAN_NOZZLE_ITEM_NAME) == name_n or (
        "van" in name_n and "nozzle" in name_n and "all" in name_n
    )


def _van_nozzle_blocks_catalog(desc: str, name_n: str) -> bool:
    """On VAN nozzle invoice lines, only the catch-all catalog row may score."""
    if not is_van_nozzle_invoice_line(desc):
        return False
    return not _catalog_is_van_nozzle_catch_all(name_n)


_STEEL_LOCK_NUT_INVOICE_RE = re.compile(
    r"steel\s+lock\s+nut|lock\s+nut.*\bsteel\b",
    re.IGNORECASE,
)


def is_steel_lock_nut_invoice_line(desc: str) -> bool:
    """Invoice lines for Lock Nut, Steel (size from description)."""
    return bool(_STEEL_LOCK_NUT_INVOICE_RE.search(desc or ""))


def _catalog_is_steel_lock_nut(name_n: str) -> bool:
    return "lock nut" in name_n and "steel" in name_n


def _steel_lock_nut_blocks_catalog(desc: str, name_n: str) -> bool:
    """On steel lock nut lines, only Lock Nut, Steel catalog rows may score."""
    if not is_steel_lock_nut_invoice_line(desc):
        return False
    return not _catalog_is_steel_lock_nut(name_n)


def _steel_lock_nut_sizes_match(desc_sizes: set[str], cat_sizes: set[str]) -> bool:
    if not desc_sizes or not cat_sizes:
        return False
    if desc_sizes == cat_sizes:
        return True
    if len(cat_sizes) == 1:
        return next(iter(cat_sizes)) in desc_sizes
    return bool(desc_sizes & cat_sizes)


_CONDUIT_GRAY_CATALOG_PREFIX = "conduit gray"


def _fowler_match_context_ok(
    vendor_name: str | None,
    vendor_raw: str | None,
) -> bool:
    """When vendor is unknown (tests), allow Fowler one-offs on description alone."""
    if not vendor_name and not vendor_raw:
        return True
    return is_hd_fowler_vendor(vendor_name) or is_hd_fowler_vendor(vendor_raw)


def is_fowler_gray_pvc_conduit_invoice_line(
    desc: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """Fowler invoice lines for gray SCH 40 PVC conduit sticks (10' lengths)."""
    if not _fowler_match_context_ok(vendor_name, vendor_raw):
        return False
    d = _norm(desc)
    if "conduit" not in d:
        return False
    if "gray" not in d and "grey" not in d:
        return False
    if "pvc" not in d:
        return False
    return bool(re.search(r"sch\s*40|schedule\s*40", d))


def _gray_pvc_conduit_blocks_catalog(
    desc: str,
    name_n: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """On Fowler gray PVC conduit lines, only Conduit Gray catalog rows may score."""
    if not is_fowler_gray_pvc_conduit_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    return "conduit gray" not in name_n


_PRO_TURF_SIDR15_POLY_INVOICE_RE = re.compile(
    r"pro\s+turf\s+green.*sidr-?\s*15|sidr-?\s*15.*pro\s+turf\s+green",
    re.IGNORECASE | re.DOTALL,
)

# Exact Aspire ItemName for Fowler Pro Turf Green SIDR-15 (leading invoice size → catalog).
_PRO_TURF_GREEN_SIDR15_CATALOG_BY_SIZE: dict[str, str] = {
    "1": 'Green Poly Pipe - 1" (SIDR 15)',
    "1-1/4": 'Green Poly Pipe - 1-1/4" (SIDR 15)',
}

_LEADING_PIPE_SIZE_RE = re.compile(
    r'^\s*(\d{1,2}-\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}|\d{1,2})\s*"',
    re.IGNORECASE,
)


def is_pro_turf_sidr15_poly_pipe_invoice_line(
    desc: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """Fowler Pro Turf Green SIDR-15 HDPE poly pipe rolls."""
    if not _fowler_match_context_ok(vendor_name, vendor_raw):
        return False
    d = _norm(desc)
    if "poly" not in d or "pipe" not in d:
        return False
    return bool(_PRO_TURF_SIDR15_POLY_INVOICE_RE.search(desc or ""))


def _leading_pipe_size_from_desc(desc: str) -> str | None:
    """Leading inch size on Fowler poly pipe lines (e.g. 1-1/4\")."""
    match = _LEADING_PIPE_SIZE_RE.match(desc or "")
    if not match:
        return None
    raw = match.group(1)
    sizes = _sizes_from_text(f'{raw}"')
    if not sizes:
        return raw
    for size in sizes:
        if "-" in size or "/" in size:
            return size
    return next(iter(sizes))


def _poly_pipe_sidr_rating(name_n: str) -> int | None:
    match = re.search(r"sidr-?\s*(\d+)", name_n, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _catalog_is_green_poly_pipe_sidr15(name_n: str) -> bool:
    return (
        "green" in name_n
        and "poly pipe" in name_n
        and _poly_pipe_sidr_rating(name_n) == 15
    )


def _pro_turf_sidr15_blocks_catalog(
    desc: str,
    name_n: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """On Pro Turf SIDR-15 lines, only Green Poly Pipe (SIDR 15) may score."""
    if not is_pro_turf_sidr15_poly_pipe_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    return not _catalog_is_green_poly_pipe_sidr15(name_n)


_BLACK_SIDR15_POLY_INVOICE_RE = re.compile(
    r"sidr-?\s*15.*poly\s+pipe.*(?:3608|black)|"
    r"(?:3608|black).*sidr-?\s*15.*poly\s+pipe",
    re.IGNORECASE | re.DOTALL,
)

# Fowler black SIDR-15 poly (3608 resin) — invoice size → Aspire ItemName.
_BLACK_SIDR15_POLY_CATALOG_BY_SIZE: dict[str, str] = {
    "1-1/2": 'Poly Pipe - 1.5" (SIDR 15)',
}


def is_fowler_black_sidr15_poly_pipe_invoice_line(
    desc: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """Fowler black SIDR-15 poly pipe rolls (3608 resin; not Pro Turf Green)."""
    if not _fowler_match_context_ok(vendor_name, vendor_raw):
        return False
    d = _norm(desc)
    if "poly" not in d or "pipe" not in d:
        return False
    if "pro turf" in d and "green" in d:
        return False
    return bool(_BLACK_SIDR15_POLY_INVOICE_RE.search(desc or ""))


def _catalog_is_poly_pipe_sidr15_non_green(name_n: str) -> bool:
    return (
        "poly pipe" in name_n
        and "green" not in name_n
        and _poly_pipe_sidr_rating(name_n) == 15
    )


def _black_sidr15_poly_blocks_catalog(
    desc: str,
    name_n: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """On Fowler black SIDR-15 poly lines, only plain Poly Pipe (SIDR 15) may score."""
    if not is_fowler_black_sidr15_poly_pipe_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    return not _catalog_is_poly_pipe_sidr15_non_green(name_n)


# Fowler HDPE mainline coil — invoice SDR/SIDR 11 + IPS/HDPE → Poly Pipe (SIDR 11).
_HDPE_SIDR11_PIPE_CATALOG_BY_SIZE: dict[str, str] = {
    "2": 'Poly Pipe - 2" (SIDR 11)',
}


def is_fowler_hdpe_sidr11_pipe_invoice_line(
    desc: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """Fowler HDPE IPS mainline coil (SDR/SIDR 11); not fittings or SIDR-15 turf pipe."""
    if not _fowler_match_context_ok(vendor_name, vendor_raw):
        return False
    d = _norm(desc)
    if not re.search(r"sidr-?\s*11|sdr-?\s*11", desc or "", re.I):
        return False
    if "hdpe" not in d and "ips" not in d:
        return False
    if "pipe" not in d and "coil" not in d:
        return False
    if re.search(r"\b(adapter|reducer|tee|elbow|coupl|union|valve)\b", d):
        return False
    if is_pro_turf_sidr15_poly_pipe_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    if is_fowler_black_sidr15_poly_pipe_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    return True


def _catalog_is_poly_pipe_sidr11(name_n: str) -> bool:
    return "poly pipe" in name_n and _poly_pipe_sidr_rating(name_n) == 11


def _hdpe_sidr11_pipe_blocks_catalog(
    desc: str,
    name_n: str,
    *,
    vendor_name: str | None = None,
    vendor_raw: str | None = None,
) -> bool:
    """On Fowler HDPE SIDR-11 pipe lines, only Poly Pipe (SIDR 11) may score."""
    if not is_fowler_hdpe_sidr11_pipe_invoice_line(
        desc, vendor_name=vendor_name, vendor_raw=vendor_raw
    ):
        return False
    return not _catalog_is_poly_pipe_sidr11(name_n)


_PVC_INSERT_TEE_FIPT_BRANCH_RE = re.compile(
    r"ixixf(?:ipt|pt)?|\bfipt\b",
    re.IGNORECASE,
)

# Equal PVC insert tee with female threaded branch (IxI x FIPT / IxIxF).
_PVC_INSERT_TEE_FIPT_BRANCH_CATALOG_BY_SIZE: dict[str, str] = {
    "1-1/2": 'PVC Insert Tee x Female adapter- 1-1/2" (IxIxF)',
}

# Reducing PVC insert tee with female threaded branch (IxIxFIPT on invoice).
_PVC_INSERT_TEE_FIPT_REDUCING_CATALOG: dict[frozenset[str], str] = {
    frozenset({"1-1/4", "1"}): 'PVC Insert Tee x Female Adapter - 1-1/4"x1"',
    frozenset({"1-1/2", "1"}): 'PVC Insert Tee x Female Adapter - 1-1/2"x1"',
    frozenset({"2", "1"}): 'PVC Insert Tee x Female Adapter - 2"x1"',
    frozenset({"2", "1-1/2"}): 'PVC Insert Tee x Female Adapter - 2"x1-1/2"',
}


def is_pvc_insert_tee_fipt_branch_invoice_line(desc: str) -> bool:
    """PVC insert tee with FIPT / IxIxF female branch (IxIxFIPT on invoice)."""
    d = _norm(desc)
    if not re.search(r"\btee\b", desc or "", re.I):
        return False
    if "pvc" not in d or "insert" not in d:
        return False
    return bool(_PVC_INSERT_TEE_FIPT_BRANCH_RE.search(desc or ""))


def _catalog_is_pvc_insert_tee_female_branch(name_n: str) -> bool:
    return "insert tee" in name_n and "female" in name_n


def _pvc_insert_tee_fipt_branch_blocks_catalog(desc: str, name_n: str) -> bool:
    """On IxIxFIPT insert tee lines, only PVC Insert Tee x Female adapter may score."""
    if not is_pvc_insert_tee_fipt_branch_invoice_line(desc):
        return False
    return not _catalog_is_pvc_insert_tee_female_branch(name_n)


_PVC_INSERT_ELBOW_IXFIPT_RE = re.compile(r"\bixf(?:ipt|pt)?\b", re.IGNORECASE)

# Reducing PVC insert 90° elbow with female threaded branch (IxFIPT on invoice).
_PVC_INSERT_ELBOW_IXF_REDUCING_CATALOG: dict[frozenset[str], str] = {
    frozenset({"1-1/4", "3/4"}): 'PVC Insert Elbow (90) Reducing - 1-1/4" x 3/4" (IxF)',
    frozenset({"1-1/2", "1"}): 'PVC Insert Elbow (90) Reducing - 1-1/2" x 1" (IxF)',
    frozenset({"2", "1-1/2"}): 'PVC Insert Elbow (90) Reducing - 2" x 1-1/2" (IxF)',
}


def is_pvc_insert_elbow_ixfipt_line(desc: str) -> bool:
    """PVC insert 90° elbow with IxFIPT female branch (not IXIXFIPT tee)."""
    d = _norm(desc)
    if not re.search(r"\belbow\b", desc or "", re.I):
        return False
    if "pvc" not in d or "insert" not in d:
        return False
    if not re.search(r"\b90\b", desc or ""):
        return False
    return bool(_PVC_INSERT_ELBOW_IXFIPT_RE.search(desc or ""))


def _catalog_is_pvc_insert_elbow_ixf(name_n: str) -> bool:
    return "insert elbow" in name_n and "ixf" in name_n


def _pvc_insert_elbow_ixfipt_blocks_catalog(desc: str, name_n: str) -> bool:
    """On IxFIPT insert elbow lines, only PVC Insert Elbow (IxF) may score."""
    if not is_pvc_insert_elbow_ixfipt_line(desc):
        return False
    return not _catalog_is_pvc_insert_elbow_ixf(name_n)


def _poly_pipe_sizes_match(desc_sizes: set[str], cat_sizes: set[str]) -> bool:
    if not desc_sizes or not cat_sizes:
        return False
    if desc_sizes == cat_sizes:
        return True
    if len(cat_sizes) == 1:
        return next(iter(cat_sizes)) in desc_sizes
    return bool(desc_sizes & cat_sizes)


def _conduit_gray_sizes(name: str) -> set[str]:
    """Size tokens from Conduit Gray - {size} catalog names (often without inch mark)."""
    sizes = _sizes_from_text(name)
    if sizes:
        return sizes
    match = re.search(
        r"conduit gray\s*-\s*(.+?)(?:\s*\(|$)",
        _norm(name),
        re.I,
    )
    if not match:
        return set()
    token = match.group(1).strip().strip('"').strip()
    if not token:
        return set()
    quoted = _sizes_from_text(f'{token}"')
    return quoted if quoted else {token}


def _conduit_gray_sizes_match(desc_sizes: set[str], cat_sizes: set[str]) -> bool:
    if not desc_sizes or not cat_sizes:
        return False
    if desc_sizes == cat_sizes:
        return True
    if len(cat_sizes) == 1:
        return next(iter(cat_sizes)) in desc_sizes
    return bool(desc_sizes & cat_sizes)


_PRODUCT_HINTS: list[tuple[str, tuple[str, ...]]] = [
    ("coupler", ("coupling", "coupler", "coupl")),
    ("elbow", ("elbow",)),
    ("adapter", ("adapter", "adaptor")),
    ("bushing", ("bushing",)),
    ("tee", ("tee",)),
    ("plug", ("plug",)),
    ("valve", ("valve",)),
    ("manifold", ("manifold",)),
    ("nipple", ("nipple",)),
    ("union", ("union",)),
    ("pipe dope", ("pipe dope", "weld on", "weld-on", "white seal")),
    ("wire nut", ("wire nut",)),
    ("drip", ("drip", "emitter", "tubing")),
    ("flag", ("flag",)),
]

# Product families matched as whole words (avoids substring false positives).
_PRODUCT_HINT_WORD_RE: dict[str, re.Pattern[str]] = {
    "tee": re.compile(r"\btee\b", re.IGNORECASE),
    "plug": re.compile(r"\bplug\b", re.IGNORECASE),
    "bushing": re.compile(r"\bbushing\b", re.IGNORECASE),
    "nipple": re.compile(r"\bnipple\b", re.IGNORECASE),
    "union": re.compile(r"\bunion\b", re.IGNORECASE),
}

# Fittings where invoice sizes must match catalog sizes exactly (not partial overlap).
_SIZE_STRICT_PRODUCT_HINTS = frozenset(
    {"tee", "elbow", "coupler", "adapter", "bushing", "plug", "union"}
)

# Shared words that do not count toward per-word catalog scoring (see _pvc_insert_baseline).
_SCORING_STOPWORDS = frozenset({"pvc", "insert"})


def _product_hint(desc: str) -> str | None:
    d = desc.lower()
    if _is_pipe_dope_line(desc):
        return "pipe dope"
    for hint, words in _PRODUCT_HINTS:
        word_re = _PRODUCT_HINT_WORD_RE.get(hint)
        if word_re is not None:
            if word_re.search(desc):
                return hint
            continue
        if any(w in d for w in words):
            return hint
    return None


def _catalog_matches_product_hint(hint: str, catalog_text_norm: str) -> bool:
    """True if catalog name/alt text matches the invoice product family."""
    if hint == "pipe dope":
        return bool(
            "pipe dope" in catalog_text_norm
            or "white seal" in catalog_text_norm
            or "weld on" in catalog_text_norm
            or "weld-on" in catalog_text_norm
        )
    word_re = _PRODUCT_HINT_WORD_RE.get(hint)
    if word_re is not None:
        return bool(word_re.search(catalog_text_norm))
    for key, words in _PRODUCT_HINTS:
        if hint != key:
            continue
        return any(w.strip() in catalog_text_norm for w in words)
    return hint in catalog_text_norm


def _name_words_for_score(name_n: str) -> list[str]:
    return [
        w
        for w in name_n.split()
        if len(w) > 2 and w not in _SCORING_STOPWORDS and w not in _GENERIC_COMPACT_TOKENS
    ]


def _pvc_insert_baseline(desc_n: str, name_n: str) -> float:
    """Small bonus when invoice and catalog are both PVC insert (counts once, not per word)."""
    if "pvc" in desc_n and "insert" in desc_n and "pvc" in name_n and "insert" in name_n:
        return 0.08
    return 0.0


def _leading_code_token(desc: str) -> str | None:
    """First token on the line when it looks like a supplier SKU (e.g. XFFCOUP, XQ)."""
    m = re.match(r"^\s*([A-Z][A-Z0-9-]{1,14})\b", desc or "", re.I)
    if not m:
        return None
    token = m.group(1).upper()
    if token.lower() in _TOKEN_STOPWORDS or token.lower() in _GENERIC_COMPACT_TOKENS:
        return None
    if re.fullmatch(r"[A-Z]{2,14}", token):
        return token
    if re.search(r"[-./]", token) or (
        re.search(r"\d", token) and re.search(r"[A-Z]", token, re.I)
    ):
        return token
    return None


def _is_letter_sku_token(word: str) -> bool:
    """All-letter Rain Bird / vendor codes (e.g. XFFCOUP, XFFTEE)."""
    w = word.upper()
    if len(w) < 2 or len(w) > 14:
        return False
    if w.lower() in _TOKEN_STOPWORDS or w.lower() in _GENERIC_COMPACT_TOKENS:
        return False
    return bool(re.fullmatch(r"[A-Z]+", w))


def _compact_alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm(s))


def _is_structured_blob_token(token: str) -> bool:
    """SKU-shaped invoice token vs a plain English word (e.g. WHITE, SEAL)."""
    if re.search(r"[-./]", token):
        return True
    if re.search(r"\d", token):
        return True
    return _is_letter_sku_token(token)


def _plain_blob_score(hit_count: int) -> float:
    """Cap confidence for generic word overlap; require multiple words for 0.90."""
    if hit_count <= 0:
        return 0.0
    if hit_count == 1:
        return 0.60
    if hit_count == 2:
        return 0.78
    return 0.90


# Too generic for substring/compact code matching (e.g. "elbow" inside "rbxffelbow").
_GENERIC_COMPACT_TOKENS = frozenset(
    {
        "elbow",
        "coupling",
        "coupler",
        "adapter",
        "insert",
        "valve",
        "manifold",
        "flag",
        "wire",
        "nut",
        "pvc",
        "galv",
        "galvanized",
        "male",
        "female",
        "barb",
        "drip",
        "tubing",
        "emitter",
        "cap",
        "tee",
        "ball",
        "threaded",
        "import",
        "sch",
        "brass",
        "wrench",
        "torque",
        "pipe",
        "straight",
        "tool",
        "tools",
    }
)


def _sizes_from_text(text: str) -> set[str]:
    """Normalized size tokens from invoice/catalog text (e.g. 1-1/4, 3/4, 2)."""
    found: set[str] = set()
    consumed: list[tuple[int, int]] = []

    def _overlaps(span: tuple[int, int]) -> bool:
        start, end = span
        return any(start < b and end > a for a, b in consumed)

    def _consume(span: tuple[int, int], size: str) -> None:
        if _overlaps(span):
            return
        consumed.append(span)
        found.add(size)

    def _consume_pair(span: tuple[int, int], size_a: str, size_b: str) -> None:
        if _overlaps(span):
            return
        consumed.append(span)
        found.add(size_a)
        found.add(size_b)

    # Compact reducing sizes (e.g. 1-1/2"x1", 2"x1-1/2") — run before standalone inch passes.
    for m in re.finditer(
        r'(\d{1,2}-\d{1,2}/\d{1,2})"\s*x\s*(\d{1,2})"',
        text,
        re.I,
    ):
        _consume_pair(m.span(), m.group(1), m.group(2))
    for m in re.finditer(
        r'(\d{1,2})"\s*x\s*(\d{1,2}-\d{1,2}/\d{1,2})"',
        text,
        re.I,
    ):
        _consume_pair(m.span(), m.group(1), m.group(2))
    for m in re.finditer(
        r'(\d{1,2}-\d{1,2}/\d{1,2})"\s*x\s*(\d{1,2}/\d{1,2})"',
        text,
        re.I,
    ):
        a, b = m.group(2).split("/")
        _consume_pair(m.span(), m.group(1), f"{a}/{b}")
        found.add(f"{a}-{b}/{b}")
    for m in re.finditer(
        r'(?<!\d-)(\d{1,2})"\s*x\s*(\d{1,2})"(?!/)',
        text,
        re.I,
    ):
        _consume_pair(m.span(), m.group(1), m.group(2))

    for m in re.finditer(
        r"(?:^|\s)(\d{1,2})\s*-\s*(\d{1,2})\s*/\s*(\d{1,2})\s*\"",
        text,
        re.I,
    ):
        _consume(m.span(), f"{m.group(1)}-{m.group(2)}/{m.group(3)}")
    for m in re.finditer(
        r"(?:^|\s)(\d{1,2})\s+(\d{1,2})\s*/\s*(\d{1,2})\s*\"",
        text,
        re.I,
    ):
        _consume(m.span(), f"{m.group(1)}-{m.group(2)}/{m.group(3)}")
    for m in re.finditer(r"(?:^|\s)(\d{1,2})\s*/\s*(\d{1,2})\s*\"", text, re.I):
        a, b = m.group(1), m.group(2)
        _consume(m.span(), f"{a}/{b}")
        _consume(m.span(), f"{a}-{b}/{b}")
    for m in re.finditer(r'(?:^|\s)(\d{1,2})\s*"', text):
        _consume(m.span(), m.group(1))
    return found


def _sizes_compatible(desc_sizes: set[str], cat_sizes: set[str]) -> bool:
    """Loose rule: any shared normalized size token (non-fitting items)."""
    if not desc_sizes:
        return True
    if not cat_sizes:
        return False
    return bool(desc_sizes & cat_sizes)


def _fitting_sizes_compatible(desc_sizes: set[str], cat_sizes: set[str]) -> bool:
    """
    Strict size rules for tees, elbows, couplers, adapters, bushings, unions.

    - Invoice lists 2+ sizes (run x branch): catalog must have the same set.
    - Invoice lists 1 size (equal fitting): catalog must have exactly that size.
    """
    if not desc_sizes:
        return True
    if not cat_sizes:
        return False
    if len(desc_sizes) >= 2:
        return desc_sizes == cat_sizes
    if len(cat_sizes) == 1:
        return desc_sizes == cat_sizes
    return False


def _size_match_score(desc_sizes: set[str], cat_sizes: set[str]) -> tuple[float, int]:
    """Graded size bonus and tie-break weight (exact set match wins)."""
    if not desc_sizes or not cat_sizes:
        return 0.0, 0
    overlap = desc_sizes & cat_sizes
    if not overlap:
        return 0.0, 0
    score = 0.25 * len(overlap)
    if desc_sizes == cat_sizes:
        score += 0.35
    tie = len(overlap) * 100 + (1000 if desc_sizes == cat_sizes else 0)
    return score, tie


def _sizes_match_for_desc(
    desc: str, desc_sizes: set[str], cat_sizes: set[str], *, hint: str | None
) -> bool:
    if _skip_inch_size_overlap(desc):
        return True
    if not desc_sizes:
        return True
    if not cat_sizes:
        return False
    if hint in _SIZE_STRICT_PRODUCT_HINTS:
        return _fitting_sizes_compatible(desc_sizes, cat_sizes)
    return _sizes_compatible(desc_sizes, cat_sizes)


def _size_matches(
    desc_sizes: set[str], catalog_text: str, *, desc: str | None = None
) -> bool:
    cat_sizes = _sizes_from_text(catalog_text)
    hint = _product_hint(desc) if desc else None
    return _sizes_match_for_desc(desc or "", desc_sizes, cat_sizes, hint=hint)


def _material_hint(desc: str) -> str | None:
    d = _norm(desc)
    if "pvc" in d:
        return "pvc"
    if "galvanized" in d:
        return "galv"
    if "brass" in d:
        return "brass"
    return None


def _code_tokens_from_text(desc: str, supplier_item_code: str | None) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        t = raw.strip().upper()
        if len(t) < 2 or t in seen:
            return
        seen.add(t)
        tokens.append(t)

    leading = _leading_code_token(desc)
    if leading:
        add(leading)
    if supplier_item_code and _use_supplier_code(supplier_item_code, desc):
        add(supplier_item_code)
    for match in _CODE_TOKEN_RE.finditer(desc or ""):
        add(match.group())
    for word in re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", (desc or "").upper()):
        if word.lower() in _GENERIC_COMPACT_TOKENS:
            continue
        if _is_letter_sku_token(word):
            add(word)
            continue
        if re.search(r"[A-Z].*[0-9]|[0-9].*[A-Z]", word) or len(word) <= 5:
            add(word)
    return tokens


@dataclass
class VendorRecord:
    vendor_id: int
    vendor_name: str
    accounting_vendor_id: str


@dataclass
class InventoryRecord:
    item_code: str
    item_name: str
    item_alternate_name: str
    item_type: str = "Material"

    def for_llm(self) -> dict:
        d: dict = {"item_name": self.item_name}
        if self.item_code:
            d["item_code"] = self.item_code
        if self.item_alternate_name:
            d["item_alternate_name"] = self.item_alternate_name
        return d


class ReferenceData:
    def __init__(self) -> None:
        self.vendors: list[VendorRecord] = []
        self.inventory: list[InventoryRecord] = []
        self._by_code: dict[str, InventoryRecord] = {}
        self._by_name: dict[str, InventoryRecord] = {}
        self._by_alt: dict[str, InventoryRecord] = {}

    def load(self) -> None:
        self._load_vendors()
        self._load_catalog()
        self._build_inventory_indexes()

    def _load_vendors(self) -> None:
        path = vendors_csv_path()
        if not path.is_file():
            raise FileNotFoundError(f"Vendors CSV not found: {path}")
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                active = str(row.get("Active", "")).strip().upper()
                if active in ("FALSE", "0", "NO"):
                    continue
                name = (row.get("VendorName") or "").strip()
                if not name:
                    continue
                vid = row.get("VendorID", "")
                try:
                    vendor_id = int(vid)
                except (TypeError, ValueError):
                    continue
                self.vendors.append(
                    VendorRecord(
                        vendor_id=vendor_id,
                        vendor_name=name,
                        accounting_vendor_id=str(
                            row.get("AccountingVendorID") or ""
                        ).strip(),
                    )
                )

    def _load_catalog(self) -> None:
        path = catalog_items_csv_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Catalog CSV not found: {path}. "
                "Run: py scripts/export_reference_data.py --out exports"
            )
        with path.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            type_filter = catalog_item_type_filter()
            for row in reader:
                active = str(row.get("Active", "")).strip().upper()
                if active in ("FALSE", "0", "NO"):
                    continue
                item_type = (row.get("ItemType") or "").strip()
                if (
                    type_filter
                    and item_type.lower() != type_filter.lower()
                ):
                    continue
                name = (row.get("ItemName") or "").strip()
                code = (row.get("ItemCode") or "").strip()
                alt = (row.get("ItemAlternateName") or "").strip()
                if not name and not code and not alt:
                    continue
                self.inventory.append(
                    InventoryRecord(
                        item_code=code,
                        item_name=name or code or alt,
                        item_alternate_name=alt,
                        item_type=item_type or type_filter or "Material",
                    )
                )

    def _build_inventory_indexes(self) -> None:
        self._codes_by_prefix: dict[str, list[InventoryRecord]] = {}
        for rec in self.inventory:
            if rec.item_code:
                key = _norm(rec.item_code)
                self._by_code[key] = rec
                prefix = re.sub(r"[^a-z0-9]", "", key)[:4]
                if len(prefix) >= 2:
                    self._codes_by_prefix.setdefault(prefix, []).append(rec)
            if rec.item_name:
                self._by_name[_norm(rec.item_name)] = rec
            if rec.item_alternate_name:
                alt_key = _norm(rec.item_alternate_name)
                if alt_key not in self._by_alt:
                    self._by_alt[alt_key] = rec

    def vendors_for_llm(self, limit: int | None = None) -> list[dict]:
        cap = limit or int(os.environ.get("IDP_VENDORS_LLM_LIMIT", "500"))
        out: list[dict] = []
        for v in self.vendors[:cap]:
            if exclude_vendor_from_llm_list(v.vendor_name):
                continue
            out.append({"vendor_id": v.vendor_id, "vendor_name": v.vendor_name})
        return out

    def inventory_for_llm(self, limit: int | None = None) -> list[dict]:
        cap = limit or int(os.environ.get("IDP_CATALOG_LLM_LIMIT", "2500"))
        return [r.for_llm() for r in self.inventory[:cap]]

    def lookup_vendor_record(self, vendor_name: str | None) -> VendorRecord | None:
        if not vendor_name:
            return None
        exact = {v.vendor_name: v for v in self.vendors}
        if vendor_name in exact:
            return exact[vendor_name]
        key = _norm(vendor_name)
        for v in self.vendors:
            if _norm(v.vendor_name) == key:
                return v
        return None

    def resolve_vendor_name(
        self,
        vendor_name: str | None,
        vendor_raw: str | None = None,
    ) -> VendorRecord | None:
        if is_hd_fowler_vendor(vendor_name) or is_hd_fowler_vendor(vendor_raw):
            return resolve_hd_fowler_vendor(self, vendor_name, vendor_raw)
        if is_idaho_sod_vendor(vendor_name) or is_idaho_sod_vendor(vendor_raw):
            return resolve_idaho_sod_vendor(self, vendor_name, vendor_raw)
        if vendor_name:
            return self.lookup_vendor_record(vendor_name)
        if vendor_raw:
            return self.lookup_vendor_record(vendor_raw)
        return None

    def resolve_inventory(
        self, item_code: str | None, item_name: str | None, item_alternate: str | None
    ) -> InventoryRecord | None:
        if item_code:
            rec = self._by_code.get(_norm(item_code))
            if rec:
                return rec
        for candidate in (item_name, item_alternate):
            if not candidate:
                continue
            key = _norm(candidate)
            if key in self._by_name:
                return self._by_name[key]
            if key in self._by_alt:
                return self._by_alt[key]
        return None

    def _score_catalog_record(
        self,
        desc: str,
        rec: InventoryRecord,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[float, int]:
        """Score one catalog row against invoice text (higher is better)."""
        name = (rec.item_name or "").strip()
        alt = (rec.item_alternate_name or "").strip()
        code = (rec.item_code or "").strip()
        if not name and not alt and not code:
            return 0.0, 0

        catalog_text = " ".join(p for p in (name, alt, code) if p)
        desc_n = _norm(desc)
        name_n = _norm(catalog_text)
        hint = _product_hint(desc)
        material = _material_hint(desc)
        desc_sizes = (
            set() if _skip_inch_size_overlap(desc) else _sizes_from_text(desc)
        )
        cat_sizes = _sizes_from_text(catalog_text)
        code_in_desc = bool(code and _code_appears_in_description(code, desc))

        if _consumable_blocks_catalog(desc_n, name_n):
            return 0.0, 0
        if _invoice_excludes_wire_nuts(desc_n, name_n):
            return 0.0, 0
        if _pipe_dope_blocks_catalog(desc_n, name_n):
            return 0.0, 0
        if _gray_pvc_conduit_blocks_catalog(
            desc, name_n, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return 0.0, 0
        if _pro_turf_sidr15_blocks_catalog(
            desc, name_n, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return 0.0, 0
        if _black_sidr15_poly_blocks_catalog(
            desc, name_n, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return 0.0, 0
        if _hdpe_sidr11_pipe_blocks_catalog(
            desc, name_n, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return 0.0, 0
        if _pvc_insert_tee_fipt_branch_blocks_catalog(desc, name_n):
            return 0.0, 0
        if _pvc_insert_elbow_ixfipt_blocks_catalog(desc, name_n):
            return 0.0, 0
        if _van_nozzle_blocks_catalog(desc, name_n):
            return 0.0, 0
        if _steel_lock_nut_blocks_catalog(desc, name_n):
            return 0.0, 0
        if hint and not _catalog_matches_product_hint(hint, name_n) and not code_in_desc:
            return 0.0, 0
        if material == "pvc" and "pvc" not in name_n:
            return 0.0, 0
        if material == "galv" and "galvanized" not in name_n:
            return 0.0, 0
        if material == "brass" and "brass" not in name_n:
            return 0.0, 0

        size_tie = 0
        if desc_sizes:
            if not cat_sizes:
                return 0.0, 0
            if not _sizes_match_for_desc(desc, desc_sizes, cat_sizes, hint=hint):
                return 0.0, 0

        score = 0.0
        if code_in_desc:
            score = max(score, 0.98)
        if name and _norm(name) in desc_n:
            score = max(score, 0.95)
        if alt and _norm(alt) in desc_n:
            score = max(score, 0.93)

        ratio = SequenceMatcher(None, desc_n, name_n).ratio()
        name_words = _name_words_for_score(name_n)
        token_score = 0.0
        if name_words:
            hits = sum(1 for w in name_words if w in desc_n)
            token_score = hits / len(name_words)
            if (
                len(name_words) == 1
                and name_words[0] in _COLOR_ONLY_WORDS
                and _is_tape_line(desc)
            ):
                token_score = 0.0
        score = max(score, ratio, token_score * 0.92)

        if desc_sizes and cat_sizes:
            size_bonus, size_tie = _size_match_score(desc_sizes, cat_sizes)
            score += size_bonus
        score += _pvc_insert_baseline(desc_n, name_n)
        if re.search(r"\btee\b", desc_n) and re.search(r"\btee\b", name_n):
            score += 0.20
        if re.search(r"\bplug\b", desc_n) and re.search(r"\bplug\b", name_n):
            score += 0.20
        if re.search(r"\bbushing\b", desc_n) and re.search(r"\bbushing\b", name_n):
            score += 0.20
        if re.search(r"\bunion\b", desc_n) and re.search(r"\bunion\b", name_n):
            score += 0.20
        if _is_pipe_dope_line(desc_n):
            if (
                "pipe dope" in name_n
                or "white seal" in name_n
                or "weld on" in name_n
                or "weld-on" in name_n
            ):
                score += 0.45
        rare = [
            w
            for w in re.findall(r"[a-z]{5,}", desc_n)
            if w not in _TOKEN_STOPWORDS
            and w not in _GENERIC_COMPACT_TOKENS
            and w not in _SCORING_STOPWORDS
        ]
        if len(rare) >= 2:
            hits = sum(1 for w in rare if w in name_n)
            if hits >= 2:
                score += 0.25 + 0.1 * hits
        if "eco" in desc_n and "indicator" in desc_n:
            if "eco" in name_n and "indicator" in name_n:
                score += 0.55
            elif "pop" in desc_n and "indicator" in name_n:
                score += 0.45
        code_blob = _compact_alnum(code) if code else ""
        name_blob = _compact_alnum(f"{name} {alt}")
        plain_hits = 0
        structured_hits = 0
        structured_score = 0.0
        for token in _BLOB_TOKEN_RE.findall(desc.upper()):
            tc = _compact_alnum(token)
            if len(tc) < 4 or tc in _GENERIC_COMPACT_TOKENS:
                continue
            in_code = bool(code_blob and tc in code_blob)
            in_name = bool(name_blob and tc in name_blob)
            if not in_code and not in_name:
                continue
            if _is_structured_blob_token(token):
                structured_hits += 1
                if in_code:
                    structured_score = max(structured_score, 0.98)
                else:
                    structured_score = max(structured_score, 0.90)
            else:
                plain_hits += 1
        score = max(score, structured_score, _plain_blob_score(plain_hits))
        tie_break = (
            size_tie + plain_hits + structured_hits + (10 if structured_score >= 0.98 else 0)
        )
        return score, tie_break

    def _match_by_code_in_description(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """Exact catalog ItemCode appearing in invoice line text (longest code wins)."""
        best: InventoryRecord | None = None
        best_code = ""
        for rec in self.inventory:
            code = (rec.item_code or "").strip()
            if not code or not _code_appears_in_description(code, desc):
                continue
            if len(code) > len(best_code):
                best_code = code
                best = rec
        if best:
            return best, 0.98, f"Item code {best_code!r} found in description"
        return None, 0.0, ""

    def _match_by_tokens(self, desc: str, tokens: list[str]) -> tuple[InventoryRecord | None, float, str]:
        for token in tokens:
            rec = self._by_code.get(_norm(token))
            if rec:
                return rec, 0.98, f"Exact item code {token!r}"
            rec, pscore = self._best_prefix_code_match(token, desc)
            if rec and pscore >= 0.35:
                conf = min(0.92, 0.72 + pscore * 0.25)
                return rec, conf, f"Prefix item code match for {token!r}"
        return None, 0.0, ""

    def _best_prefix_code_match(
        self, token: str, desc: str
    ) -> tuple[InventoryRecord | None, float]:
        key = _norm(token)
        desc_key = re.sub(r"[^a-z0-9]", "", key)
        if len(desc_key) < 4:
            return None, 0.0
        desc_sizes = (
            set()
            if _skip_inch_size_overlap(desc)
            else _sizes_from_text(desc)
        )
        best: InventoryRecord | None = None
        best_score = 0.0
        for rec in self.inventory:
            code = rec.item_code
            if not code:
                continue
            code_key = re.sub(r"[^a-z0-9]", "", _norm(code))
            if not code_key:
                continue
            if not (
                code_key.startswith(desc_key)
                or desc_key.startswith(code_key)
                or (
                    len(desc_key) >= 4
                    and _is_letter_sku_token(token)
                    and desc_key in code_key
                )
            ):
                continue
            overlap = min(len(code_key), len(desc_key))
            if overlap < 4:
                continue
            catalog_text = f"{rec.item_name} {rec.item_alternate_name}"
            if desc_sizes and not _size_matches(desc_sizes, catalog_text, desc=desc):
                continue
            score = overlap / max(len(code_key), len(desc_key))
            if desc_sizes:
                score += 0.3
            if score > best_score:
                best_score = score
                best = rec
        return best, best_score

    def _best_catalog_match(
        self,
        desc: str,
        supplier_item_code: str | None,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """Scan full catalog and return the highest-scoring row."""
        desc = desc.strip()
        if not desc:
            return None, 0.0, "No catalog match"

        key = _norm(desc)
        rec = self._by_name.get(key) or self._by_alt.get(key)
        if rec:
            return rec, 0.95, "Exact catalog name from description"

        if supplier_item_code:
            sup = str(supplier_item_code).strip()
            if sup:
                rec = self._by_code.get(_norm(sup))
                if rec:
                    return rec, 0.98, f"Exact supplier item code {sup!r}"
        if supplier_item_code and _use_supplier_code(supplier_item_code, desc):
            rec = self._by_code.get(_norm(supplier_item_code))
            if rec:
                return rec, 0.98, f"Exact item code {supplier_item_code!r}"

        rec, conf, note = self._match_van_nozzle_one_off(desc)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_by_code_in_description(desc)
        if rec:
            return rec, conf, note

        tokens = sorted(
            _code_tokens_from_text(desc, supplier_item_code),
            key=_token_priority,
            reverse=True,
        )
        rec, conf, note = self._match_by_tokens(desc, tokens)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_irrigation_staples_one_off(desc)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_worm_clamp_one_off(desc)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_steel_lock_nut_one_off(desc)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_fowler_gray_pvc_conduit_one_off(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        )
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_pro_turf_sidr15_poly_pipe_one_off(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        )
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_black_sidr15_poly_pipe_one_off(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        )
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_fowler_hdpe_sidr11_pipe_one_off(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        )
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_pvc_insert_tee_fipt_branch_one_off(desc)
        if rec:
            return rec, conf, note

        rec, conf, note = self._match_pvc_insert_elbow_ixfipt_one_off(desc)
        if rec:
            return rec, conf, note

        best: InventoryRecord | None = None
        best_score = 0.0
        best_tie = 0
        for rec in self.inventory:
            score, tie = self._score_catalog_record(
                desc,
                rec,
                vendor_name=vendor_name,
                vendor_raw=vendor_raw,
            )
            if score > best_score or (score == best_score and tie > best_tie):
                best_score = score
                best_tie = tie
                best = rec

        if best and best_score >= 0.48:
            conf = min(0.95, 0.58 + best_score * 0.38)
            return best, conf, f"Best catalog match ({best_score:.2f})"
        return None, 0.0, "No catalog match"

    def _match_irrigation_staples_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Fowler jute matting box line → Irrigation Staples catalog row."""
        if not is_irrigation_staples_invoice_line(desc):
            return None, 0.0, ""
        key = _norm(_IRRIGATION_STAPLES_ITEM_NAME)
        rec = self._by_name.get(key)
        if not rec:
            for row in self.inventory:
                if _norm(row.item_name or "") == key:
                    rec = row
                    break
        if rec:
            return (
                rec,
                0.92,
                "One-off: Fowler jute matting box → Irrigation Staples",
            )
        return None, 0.0, ""

    def _match_worm_clamp_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: worm drive hose clamp → Worm Clamp (size ignored)."""
        if not is_worm_clamp_invoice_line(desc):
            return None, 0.0, ""
        key = _norm(_WORM_CLAMP_ITEM_NAME)
        rec = self._by_name.get(key)
        if not rec:
            for row in self.inventory:
                if _norm(row.item_name or "") == key:
                    rec = row
                    break
        if rec:
            return (
                rec,
                0.92,
                "One-off: Worm drive hose clamp → Worm Clamp",
            )
        return None, 0.0, ""

    def _find_steel_lock_nut_by_size(self, desc: str) -> InventoryRecord | None:
        desc_sizes = _sizes_from_text(desc)
        if not desc_sizes:
            return None
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_steel_lock_nut(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if _steel_lock_nut_sizes_match(desc_sizes, cat_sizes):
                return rec
        return None

    def _match_steel_lock_nut_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: steel lock nut → Lock Nut, Steel - {size}."""
        if not is_steel_lock_nut_invoice_line(desc):
            return None, 0.0, ""
        rec = self._find_steel_lock_nut_by_size(desc)
        if rec:
            return (
                rec,
                0.92,
                f"One-off: Steel lock nut → {rec.item_name}",
            )
        return None, 0.0, ""

    def _match_van_nozzle_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Rain Bird VAN / Hunter adjustable arc nozzle (size/color ignored)."""
        if not is_van_nozzle_invoice_line(desc):
            return None, 0.0, ""
        key = _norm(_VAN_NOZZLE_ITEM_NAME)
        rec = self._by_name.get(key)
        if not rec:
            for row in self.inventory:
                if _norm(row.item_name or "") == key:
                    rec = row
                    break
        if rec:
            return (
                rec,
                0.92,
                "One-off: VAN / Hunter adjustable arc nozzle → "
                "Rain Bird (VAN) Nozzle - All (or Hunter)",
            )
        return None, 0.0, ""

    def _find_conduit_gray_by_size(self, desc: str) -> InventoryRecord | None:
        desc_sizes = _sizes_from_text(desc)
        if not desc_sizes:
            return None
        for rec in self.inventory:
            name = rec.item_name or ""
            if not _norm(name).startswith(_CONDUIT_GRAY_CATALOG_PREFIX):
                continue
            cat_sizes = _conduit_gray_sizes(name)
            if _conduit_gray_sizes_match(desc_sizes, cat_sizes):
                return rec
        return None

    def _match_fowler_gray_pvc_conduit_one_off(
        self,
        desc: str,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Fowler gray SCH 40 PVC conduit → Conduit Gray - {size}."""
        if not is_fowler_gray_pvc_conduit_invoice_line(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return None, 0.0, ""
        rec = self._find_conduit_gray_by_size(desc)
        if rec:
            return (
                rec,
                0.92,
                "One-off: Fowler gray PVC conduit → Conduit Gray",
            )
        return None, 0.0, ""

    def _find_green_poly_pipe_sidr15_by_size(self, desc: str) -> InventoryRecord | None:
        leading = _leading_pipe_size_from_desc(desc)
        if leading and leading in _PRO_TURF_GREEN_SIDR15_CATALOG_BY_SIZE:
            target = _norm(_PRO_TURF_GREEN_SIDR15_CATALOG_BY_SIZE[leading])
            rec = self._by_name.get(target)
            if rec:
                return rec
            for row in self.inventory:
                if _norm(row.item_name or "") == target:
                    return row

        desc_sizes = _sizes_from_text(desc)
        if not desc_sizes:
            return None
        best: InventoryRecord | None = None
        best_tie = -1
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_green_poly_pipe_sidr15(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if not _poly_pipe_sizes_match(desc_sizes, cat_sizes):
                continue
            tie = len(desc_sizes & cat_sizes) * 100
            if desc_sizes == cat_sizes:
                tie += 1000
            if len(cat_sizes) == 1:
                tie += len(next(iter(cat_sizes)))
            if tie > best_tie:
                best_tie = tie
                best = rec
        return best

    def _match_pro_turf_sidr15_poly_pipe_one_off(
        self,
        desc: str,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Fowler Pro Turf SIDR-15 poly pipe → Green Poly Pipe (SIDR 15)."""
        if not is_pro_turf_sidr15_poly_pipe_invoice_line(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return None, 0.0, ""
        rec = self._find_green_poly_pipe_sidr15_by_size(desc)
        if rec:
            return (
                rec,
                0.92,
                "One-off: Pro Turf SIDR-15 poly pipe → Green Poly Pipe (SIDR 15)",
            )
        return None, 0.0, ""

    def _find_poly_pipe_sidr15_non_green_by_size(self, desc: str) -> InventoryRecord | None:
        leading = _leading_pipe_size_from_desc(desc)
        if leading and leading in _BLACK_SIDR15_POLY_CATALOG_BY_SIZE:
            target = _norm(_BLACK_SIDR15_POLY_CATALOG_BY_SIZE[leading])
            rec = self._by_name.get(target)
            if rec:
                return rec
            for row in self.inventory:
                if _norm(row.item_name or "") == target:
                    return row

        desc_sizes = _sizes_from_text(desc)
        if not desc_sizes:
            return None
        best: InventoryRecord | None = None
        best_tie = -1
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_poly_pipe_sidr15_non_green(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if not _poly_pipe_sizes_match(desc_sizes, cat_sizes):
                continue
            tie = len(desc_sizes & cat_sizes) * 100
            if desc_sizes == cat_sizes:
                tie += 1000
            if len(cat_sizes) == 1:
                tie += len(next(iter(cat_sizes)))
            if tie > best_tie:
                best_tie = tie
                best = rec
        return best

    def _match_black_sidr15_poly_pipe_one_off(
        self,
        desc: str,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Fowler black SIDR-15 poly pipe → Poly Pipe (SIDR 15), non-green."""
        if not is_fowler_black_sidr15_poly_pipe_invoice_line(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return None, 0.0, ""
        rec = self._find_poly_pipe_sidr15_non_green_by_size(desc)
        if rec:
            return (
                rec,
                0.92,
                "One-off: Fowler black SIDR-15 poly pipe → Poly Pipe (SIDR 15)",
            )
        return None, 0.0, ""

    def _find_poly_pipe_sidr11_by_size(self, desc: str) -> InventoryRecord | None:
        leading = _leading_pipe_size_from_desc(desc)
        if leading and leading in _HDPE_SIDR11_PIPE_CATALOG_BY_SIZE:
            target = _norm(_HDPE_SIDR11_PIPE_CATALOG_BY_SIZE[leading])
            rec = self._by_name.get(target)
            if rec:
                return rec
            for row in self.inventory:
                if _norm(row.item_name or "") == target:
                    return row

        desc_sizes = _sizes_from_text(desc)
        if not desc_sizes:
            return None
        best: InventoryRecord | None = None
        best_tie = -1
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_poly_pipe_sidr11(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if not _poly_pipe_sizes_match(desc_sizes, cat_sizes):
                continue
            tie = len(desc_sizes & cat_sizes) * 100
            if desc_sizes == cat_sizes:
                tie += 1000
            if len(cat_sizes) == 1:
                tie += len(next(iter(cat_sizes)))
            if tie > best_tie:
                best_tie = tie
                best = rec
        return best

    def _match_fowler_hdpe_sidr11_pipe_one_off(
        self,
        desc: str,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: Fowler HDPE SDR/SIDR 11 mainline coil → Poly Pipe (SIDR 11)."""
        if not is_fowler_hdpe_sidr11_pipe_invoice_line(
            desc, vendor_name=vendor_name, vendor_raw=vendor_raw
        ):
            return None, 0.0, ""
        rec = self._find_poly_pipe_sidr11_by_size(desc)
        if rec:
            return (
                rec,
                0.92,
                "One-off: Fowler HDPE SIDR-11 mainline → Poly Pipe (SIDR 11)",
            )
        return None, 0.0, ""

    def _find_catalog_by_item_name(self, target_name: str) -> InventoryRecord | None:
        key = _norm(target_name)
        rec = self._by_name.get(key)
        if rec:
            return rec
        for row in self.inventory:
            if _norm(row.item_name or "") == key:
                return row
        return None

    def _find_pvc_insert_tee_ixixf_branch_by_size(self, desc: str) -> InventoryRecord | None:
        desc_sizes = _sizes_from_text(desc)

        if len(desc_sizes) >= 2:
            target_name = _PVC_INSERT_TEE_FIPT_REDUCING_CATALOG.get(
                frozenset(desc_sizes)
            )
            if target_name:
                rec = self._find_catalog_by_item_name(target_name)
                if rec:
                    return rec
            for rec in self.inventory:
                name_n = _norm(rec.item_name or "")
                if not _catalog_is_pvc_insert_tee_female_branch(name_n):
                    continue
                cat_sizes = _sizes_from_text(rec.item_name or "")
                if desc_sizes == cat_sizes:
                    return rec
            return None

        leading = _leading_pipe_size_from_desc(desc)
        if not leading:
            leading = next(iter(desc_sizes)) if len(desc_sizes) == 1 else None
        if leading and leading in _PVC_INSERT_TEE_FIPT_BRANCH_CATALOG_BY_SIZE:
            target = _PVC_INSERT_TEE_FIPT_BRANCH_CATALOG_BY_SIZE[leading]
            rec = self._find_catalog_by_item_name(target)
            if rec:
                return rec

        if not desc_sizes:
            return None
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_pvc_insert_tee_female_branch(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if desc_sizes == cat_sizes or (
                len(cat_sizes) == 1 and next(iter(desc_sizes)) in cat_sizes
            ):
                return rec
        return None

    def _match_pvc_insert_tee_fipt_branch_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: PVC insert tee IxIxFIPT → PVC Insert Tee x Female adapter."""
        if not is_pvc_insert_tee_fipt_branch_invoice_line(desc):
            return None, 0.0, ""
        rec = self._find_pvc_insert_tee_ixixf_branch_by_size(desc)
        if rec:
            sizes = _sizes_from_text(desc)
            label = "reducing " if len(sizes) >= 2 else ""
            return (
                rec,
                0.92,
                f"One-off: PVC insert tee IxIxFIPT → {label}Insert Tee x Female",
            )
        return None, 0.0, ""

    def _find_pvc_insert_elbow_ixf_by_size(self, desc: str) -> InventoryRecord | None:
        desc_sizes = _sizes_from_text(desc)
        if len(desc_sizes) >= 2:
            target_name = _PVC_INSERT_ELBOW_IXF_REDUCING_CATALOG.get(
                frozenset(desc_sizes)
            )
            if target_name:
                rec = self._find_catalog_by_item_name(target_name)
                if rec:
                    return rec
            for rec in self.inventory:
                name_n = _norm(rec.item_name or "")
                if not _catalog_is_pvc_insert_elbow_ixf(name_n):
                    continue
                cat_sizes = _sizes_from_text(rec.item_name or "")
                if desc_sizes == cat_sizes:
                    return rec
            return None

        if not desc_sizes:
            return None
        for rec in self.inventory:
            name_n = _norm(rec.item_name or "")
            if not _catalog_is_pvc_insert_elbow_ixf(name_n):
                continue
            cat_sizes = _sizes_from_text(rec.item_name or "")
            if desc_sizes == cat_sizes or (
                len(cat_sizes) == 1 and next(iter(desc_sizes)) in cat_sizes
            ):
                return rec
        return None

    def _match_pvc_insert_elbow_ixfipt_one_off(
        self, desc: str
    ) -> tuple[InventoryRecord | None, float, str]:
        """One-off: PVC insert 90° elbow IxFIPT → Insert Elbow (IxF)."""
        if not is_pvc_insert_elbow_ixfipt_line(desc):
            return None, 0.0, ""
        rec = self._find_pvc_insert_elbow_ixf_by_size(desc)
        if rec:
            sizes = _sizes_from_text(desc)
            label = "reducing " if len(sizes) >= 2 else ""
            return (
                rec,
                0.92,
                f"One-off: PVC insert elbow IxFIPT → {label}Insert Elbow (IxF)",
            )
        return None, 0.0, ""

    def match_line(
        self,
        description_raw: str,
        supplier_item_code: str | None,
        *,
        vendor_name: str | None = None,
        vendor_raw: str | None = None,
    ) -> tuple[InventoryRecord | None, float, str]:
        """Match invoice line text to catalog_items.csv (local, no LLM)."""
        return self._best_catalog_match(
            description_raw,
            supplier_item_code,
            vendor_name=vendor_name,
            vendor_raw=vendor_raw,
        )

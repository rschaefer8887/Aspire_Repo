"""Prompt and refresh Aspire catalog for MD Internal Vendor imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aspire_common import AspireClient
from aspire_lookups import LookupService
from idp_paths import ROOT
from idp_vendor_prefs import md_internal_vendor_id, md_internal_vendor_name


@dataclass
class MdInternalCatalogState:
    """Tracks catalog refresh choice across a multi-file import run."""

    decision: str | None = None  # None = not asked yet; "refresh" | "skip"


def prompt_md_internal_catalog_refresh() -> bool:
    """Ask whether to refresh catalog_items.csv before an MD Internal import."""
    vendor = md_internal_vendor_name()
    vid = md_internal_vendor_id()
    print(
        f"\n  MD Internal Vendor ({vendor}, ID {vid}) uses Item Code in column B only."
    )
    while True:
        reply = input(
            "  Refresh catalog_items.csv from Aspire before importing? [Y/N]: "
        ).strip().upper()
        if reply in ("Y", "YES"):
            return True
        if reply in ("N", "NO"):
            return False
        print("  Please enter Y or N.")


def refresh_catalog_for_md_internal_import(
    client: AspireClient,
    lookups: LookupService,
    *,
    out_dir: Path | None = None,
) -> int:
    """Export catalog_items.csv and reload import lookup indexes from Aspire."""
    import sys

    scripts_dir = ROOT / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from export_reference_data import export_catalog_items_with_client  # noqa: E402

    dest = export_catalog_items_with_client(client, out_dir or ROOT / "exports")
    count = lookups.refresh_catalog_indexes()
    print(f"  Catalog: reloaded {count} active item code(s) for import matching.")
    print(f"  Catalog: saved {dest.name}")
    return count


def maybe_refresh_catalog_for_md_internal(
    client: AspireClient,
    lookups: LookupService,
    *,
    vendor_id: int,
    state: MdInternalCatalogState,
    dry_run: bool,
    no_catalog_prompt: bool,
    yes_refresh_catalog: bool,
    no_refresh_catalog: bool,
) -> None:
    """
    For MD Internal Vendor (347), optionally refresh catalog before line matching.
    Prompts once per import run unless flags skip or force the decision.
    """
    if vendor_id != md_internal_vendor_id():
        return
    if state.decision == "refresh":
        return
    if state.decision == "skip":
        print("  Catalog: using cached Aspire catalog (refresh skipped earlier in this run).")
        return

    if no_catalog_prompt or no_refresh_catalog:
        state.decision = "skip"
        print("  Catalog: using cached Aspire catalog (--no-catalog-prompt / --no-refresh-catalog).")
        return

    do_refresh = yes_refresh_catalog
    if not do_refresh:
        if dry_run:
            print(
                "\n  [dry-run] Would prompt: Refresh catalog_items.csv from Aspire "
                "before MD Internal import? [Y/N]"
            )
            state.decision = "skip"
            return
        do_refresh = prompt_md_internal_catalog_refresh()

    if do_refresh:
        print("  Catalog: fetching latest items from Aspire...")
        refresh_catalog_for_md_internal_import(client, lookups)
        state.decision = "refresh"
    else:
        state.decision = "skip"
        print("  Catalog: using cached Aspire catalog.")

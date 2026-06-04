"""
Export Aspire reference lists to CSV for troubleshooting lookups.

Usage:
  python scripts/export_reference_data.py
  python scripts/export_reference_data.py --out exports
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aspire_common import AspireClient, require_credentials  # noqa: E402


CATALOG_ITEMS_EXPORT = (
    "catalog_items.csv",
    "/CatalogItems",
    [
        "CatalogItemID",
        "ItemCode",
        "ItemName",
        "ItemAlternateName",
        "ItemType",
        "Active",
    ],
    {
        "$select": "CatalogItemID,ItemCode,ItemName,ItemAlternateName,"
        "ItemType,Active"
    },
)


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fieldnames})


def export_catalog_items(out_dir: Path | str = "exports") -> Path:
    """Fetch catalog items from Aspire and write exports/catalog_items.csv."""
    out_dir = Path(out_dir)
    client_id, secret = require_credentials()
    client = AspireClient(client_id, secret)
    client.authenticate()

    filename, path, fields, params = CATALOG_ITEMS_EXPORT
    rows = client.fetch_all(path, extra_params=params)
    dest = out_dir / filename
    write_csv(dest, rows, fields)
    print(f"Wrote {len(rows)} rows to {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="exports", help="Output directory")
    parser.add_argument(
        "--catalog-only",
        action="store_true",
        help="Export only catalog_items.csv",
    )
    args = parser.parse_args()
    out_dir = Path(args.out)

    client_id, secret = require_credentials()
    client = AspireClient(client_id, secret)
    client.authenticate()

    exports = [
        (
            "branches.csv",
            "/Branches",
            ["BranchID", "BranchName", "BranchCode", "Active"],
            {"$select": "BranchID,BranchName,BranchCode,Active"},
        ),
        (
            "vendors.csv",
            "/Vendors",
            ["VendorID", "VendorName", "AccountingVendorID", "BranchID", "Active"],
            {
                "$select": "VendorID,VendorName,AccountingVendorID,BranchID,Active"
            },
        ),
        (
            "inventory_locations.csv",
            "/InventoryLocations",
            [
                "InventoryLocationID",
                "BranchID",
                "BranchName",
                "AddressLine1",
                "AddressLine2",
                "City",
                "Active",
            ],
            {
                "$select": "InventoryLocationID,BranchID,BranchName,"
                "AddressLine1,AddressLine2,City,Active"
            },
        ),
        (
            "catalog_items.csv",
            CATALOG_ITEMS_EXPORT[1],
            CATALOG_ITEMS_EXPORT[2],
            CATALOG_ITEMS_EXPORT[3],
        ),
    ]

    if args.catalog_only:
        export_catalog_items(out_dir)
        return

    for filename, path, fields, params in exports:
        rows = client.fetch_all(path, extra_params=params)
        dest = out_dir / filename
        write_csv(dest, rows, fields)
        print(f"Wrote {len(rows)} rows to {dest}")


if __name__ == "__main__":
    main()

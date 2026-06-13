"""Resolve Excel text to Aspire IDs (branches, vendors, catalog)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from aspire_common import AspireClient, inventory_location_id
from aspire_excel import ReceiptWorkbook, vendor_invoice_datetime_iso
from idp_vendor_prefs import (
    hd_fowler_preferred_vendor_name,
    is_hd_fowler_vendor,
    is_md_internal_vendor_id,
    normalize_vendor_key,
    pick_preferred_vendor_match,
)
from idp_vendor_profiles import vendor_profile_for


def _norm(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def _escape_odata_string(s: str) -> str:
    return s.replace("'", "''")


def _consolidate_receipt_items(items: list[dict]) -> list[dict]:
    """
    Aspire rejects duplicate CatalogItemID on one receipt.
    Merge lines with the same ID: sum qty, weighted-average unit cost (3 dp).
    """
    merged: dict[int, dict] = {}
    order: list[int] = []
    for item in items:
        cid = int(item["CatalogItemID"])
        if cid not in merged:
            merged[cid] = item
            order.append(cid)
            continue
        prev = merged[cid]
        q1 = float(prev["ItemQuantity"])
        q2 = float(item["ItemQuantity"])
        c1 = float(prev["ItemUnitCost"])
        c2 = float(item["ItemUnitCost"])
        total_qty = q1 + q2
        if total_qty <= 0:
            continue
        avg_cost = round((q1 * c1 + q2 * c2) / total_qty, 3)
        loc_id = prev["ItemAllocations"][0]["InventoryLocationID"]
        prev["ItemQuantity"] = total_qty
        prev["ItemUnitCost"] = avg_cost
        prev["ItemAllocations"] = [
            {"InventoryLocationID": loc_id, "ItemQuantity": total_qty}
        ]
    return [merged[cid] for cid in order]


def _has_duplicate_catalog_ids(items: list[dict]) -> bool:
    ids = [int(i["CatalogItemID"]) for i in items]
    return len(ids) != len(set(ids))


def _should_skip_consolidation(vendor_name: str, items: list[dict]) -> bool:
    if not _has_duplicate_catalog_ids(items):
        return False
    env = os.environ.get("IDP_SKIP_RECEIPT_CONSOLIDATION", "").strip().lower()
    if env in ("1", "true", "yes"):
        return True
    profile = vendor_profile_for(vendor_name)
    return profile.skip_receipt_item_consolidation


@dataclass
class CatalogItem:
    catalog_item_id: int
    item_name: str
    item_type: str


class LookupService:
    def __init__(self, client: AspireClient) -> None:
        self.client = client
        self._branches: list[dict] | None = None
        self._vendors: list[dict] | None = None
        self._catalog_by_code: dict[str, CatalogItem] | None = None
        self._catalog_by_name: dict[str, CatalogItem] | None = None

    def _branches_list(self) -> list[dict]:
        if self._branches is None:
            self._branches = self.client.fetch_all(
                "/Branches",
                extra_params={"$select": "BranchID,BranchName,BranchCode,Active"},
            )
        return self._branches

    def _vendors_list(self) -> list[dict]:
        if self._vendors is None:
            self._vendors = self.client.fetch_all(
                "/Vendors",
                extra_params={
                    "$select": "VendorID,VendorName,AccountingVendorID,BranchID,Active"
                },
            )
        return self._vendors

    def _build_catalog_indexes(self) -> None:
        if self._catalog_by_code is not None:
            return
        rows = self.client.fetch_all(
            "/CatalogItems",
            extra_params={
                "$select": "CatalogItemID,ItemCode,ItemName,ItemType,Active"
            },
        )
        by_code: dict[str, CatalogItem] = {}
        by_name: dict[str, CatalogItem] = {}
        for row in rows:
            if row.get("Active") is False:
                continue
            item_type = row.get("ItemType")
            if not item_type:
                continue
            cid = int(row["CatalogItemID"])
            name = str(row.get("ItemName") or "")
            cat = CatalogItem(
                catalog_item_id=cid,
                item_name=name or str(row.get("ItemCode") or cid),
                item_type=str(item_type),
            )
            code = row.get("ItemCode")
            if code:
                key = _norm(str(code))
                if key not in by_code:
                    by_code[key] = cat
            if name:
                nkey = _norm(name)
                if nkey not in by_name:
                    by_name[nkey] = cat
        self._catalog_by_code = by_code
        self._catalog_by_name = by_name

    def _catalog_from_api_code(self, item_code: str) -> CatalogItem | None:
        escaped = _escape_odata_string(item_code)
        filtered = self.client.get(
            "/CatalogItems",
            params={
                "$filter": f"ItemCode eq '{escaped}'",
                "$select": "CatalogItemID,ItemCode,ItemName,ItemType",
                "$top": "5",
            },
        )
        if isinstance(filtered, list) and filtered:
            return self._catalog_from_row(filtered[0], fallback_code=item_code)
        return None

    def _catalog_from_api_name(self, item_name: str) -> CatalogItem | None:
        escaped = _escape_odata_string(item_name)
        filtered = self.client.get(
            "/CatalogItems",
            params={
                "$filter": f"ItemName eq '{escaped}'",
                "$select": "CatalogItemID,ItemCode,ItemName,ItemType",
                "$top": "5",
            },
        )
        if isinstance(filtered, list) and filtered:
            return self._catalog_from_row(filtered[0], fallback_name=item_name)
        return None

    @staticmethod
    def _catalog_from_row(
        row0: dict,
        *,
        fallback_code: str = "",
        fallback_name: str = "",
    ) -> CatalogItem:
        name = row0.get("ItemName") or fallback_name or fallback_code
        item_type = row0.get("ItemType")
        if not item_type:
            raise ValueError("Catalog item has no ItemType in Aspire")
        return CatalogItem(
            catalog_item_id=int(row0["CatalogItemID"]),
            item_name=str(name),
            item_type=str(item_type),
        )

    def resolve_branch_id(self, text: str) -> tuple[int, str]:
        query = _norm(text)
        matches: list[tuple[int, str]] = []
        for b in self._branches_list():
            if b.get("Active") is False:
                continue
            bid = b.get("BranchID")
            if bid is None:
                continue
            name = _norm(b.get("BranchName") or "")
            code = _norm(b.get("BranchCode") or "")
            if query == name or query == code or query in name or name in query:
                matches.append((int(bid), str(b.get("BranchName") or text)))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"No branch matching {text!r}")
        ids = ", ".join(f"{m[0]} ({m[1]})" for m in matches)
        raise ValueError(f"Ambiguous branch {text!r}: {ids}")

    def _hd_fowler_turf_vendor(self) -> tuple[int, str] | None:
        pref_key = normalize_vendor_key(hd_fowler_preferred_vendor_name())
        for v in self._vendors_list():
            if v.get("Active") is False:
                continue
            vid = v.get("VendorID")
            if vid is None:
                continue
            name = str(v.get("VendorName") or "")
            if normalize_vendor_key(name) == pref_key:
                return int(vid), name
        return None

    def _finalize_vendor_matches(
        self,
        matches: list[tuple[int, str]],
        query: str,
        original_text: str,
        branch_id: int,
    ) -> tuple[int, str]:
        preferred = pick_preferred_vendor_match(matches, query)
        if preferred is not None:
            return preferred
        if is_hd_fowler_vendor(original_text) or any(
            is_hd_fowler_vendor(name) for _, name in matches
        ):
            turf = self._hd_fowler_turf_vendor()
            if turf is not None:
                if len(matches) == 1:
                    if normalize_vendor_key(matches[0][1]) != normalize_vendor_key(
                        turf[1]
                    ):
                        return turf
                elif all(is_hd_fowler_vendor(name) for _, name in matches):
                    return turf
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ValueError(f"No vendor matching {original_text!r} (branch ID {branch_id})")
        ids = ", ".join(f"{m[0]} ({m[1]})" for m in matches)
        raise ValueError(f"Ambiguous vendor {original_text!r}: {ids}")

    def resolve_vendor_id(self, text: str, branch_id: int) -> tuple[int, str]:
        query = _norm(text)
        matches: list[tuple[int, str]] = []
        for v in self._vendors_list():
            if v.get("Active") is False:
                continue
            vid = v.get("VendorID")
            if vid is None:
                continue
            vbranch = v.get("BranchID")
            if vbranch is not None and int(vbranch) != branch_id:
                continue
            name = _norm(v.get("VendorName") or "")
            acct = _norm(v.get("AccountingVendorID") or "")
            if query in (name, acct) or query in name or name in query:
                matches.append((int(vid), str(v.get("VendorName") or text)))
        if len(matches) == 1:
            return self._finalize_vendor_matches(matches, query, text, branch_id)
        if not matches:
            # Retry without branch filter
            for v in self._vendors_list():
                if v.get("Active") is False:
                    continue
                vid = v.get("VendorID")
                if vid is None:
                    continue
                name = _norm(v.get("VendorName") or "")
                acct = _norm(v.get("AccountingVendorID") or "")
                if query in (name, acct) or query in name or name in query:
                    matches.append(
                        (int(vid), str(v.get("VendorName") or text))
                    )
        return self._finalize_vendor_matches(matches, query, text, branch_id)

    def resolve_catalog_item(
        self, item_code: str, item_name: str, row: int
    ) -> CatalogItem:
        self._build_catalog_indexes()
        code_key = _norm(item_code) if item_code else ""
        name_key = _norm(item_name) if item_name else ""

        if code_key and self._catalog_by_code:
            item = self._catalog_by_code.get(code_key)
            if item:
                return item
            api = self._catalog_from_api_code(item_code)
            if api:
                return api

        if name_key and self._catalog_by_name:
            item = self._catalog_by_name.get(name_key)
            if item:
                return item
            api = self._catalog_from_api_name(item_name)
            if api:
                return api

        label = item_code or item_name or "(empty)"
        raise ValueError(
            f"Row {row}: unknown catalog item {label!r} in Aspire "
            "(no match by ItemCode or ItemName)"
        )

    def resolve_catalog_item_by_code_only(
        self, item_code: str, row: int, *, vendor_label: str
    ) -> CatalogItem:
        """
        Match catalog rows by ItemCode only (MD Internal / retail POS imports).
        Column C (item name) is ignored.
        """
        code = str(item_code or "").strip()
        if not code:
            raise ValueError(
                f"Row {row}: This invoice is for {vendor_label!r}. "
                f"Every line must have an Item Code in Excel column B. "
                f"Row {row} is missing an Item Code — add the Aspire catalog code "
                f"in column B and try again."
            )

        self._build_catalog_indexes()
        code_key = _norm(code)
        if code_key and self._catalog_by_code:
            item = self._catalog_by_code.get(code_key)
            if item:
                return item
        api = self._catalog_from_api_code(code)
        if api:
            return api

        raise ValueError(
            f"Row {row}: Item Code {code!r} in column B was not found in Aspire "
            f"for {vendor_label!r}. Check that the code matches your catalog exactly "
            f"(spelling, spaces, and punctuation). Item names in column C are not "
            f"used for this vendor."
        )

    def build_receipt_post(self, wb: ReceiptWorkbook) -> dict:
        branch_id, branch_label = self.resolve_branch_id(wb.branch)
        vendor_id, vendor_label = self.resolve_vendor_id(wb.vendor, branch_id)
        loc_id = inventory_location_id()
        code_only = is_md_internal_vendor_id(vendor_id)

        receipt_items = []
        for line in wb.lines:
            if code_only:
                cat = self.resolve_catalog_item_by_code_only(
                    line.item_code, line.row_number, vendor_label=vendor_label
                )
            else:
                cat = self.resolve_catalog_item(
                    line.item_code, line.item_name, line.row_number
                )
            receipt_items.append(
                {
                    "CatalogItemID": cat.catalog_item_id,
                    "ItemName": cat.item_name,
                    "ItemType": cat.item_type,
                    "ItemQuantity": line.quantity,
                    "ItemUnitCost": line.unit_cost,
                    "ItemAllocations": [
                        {
                            "InventoryLocationID": loc_id,
                            "ItemQuantity": line.quantity,
                        }
                    ],
                }
            )

        skip_consolidation = _should_skip_consolidation(vendor_label, receipt_items)
        if skip_consolidation:
            pass
        else:
            receipt_items = _consolidate_receipt_items(receipt_items)

        payload = {
            "BranchID": branch_id,
            "VendorID": vendor_id,
            "VendorInvoiceNum": wb.vendor_invoice_num,
            "VendorInvoiceDate": vendor_invoice_datetime_iso(wb.invoice_date),
            "InventoryLocationID": loc_id,
            "ReceiptItems": receipt_items,
        }
        if wb.receipt_note.strip():
            payload["ReceiptNote"] = wb.receipt_note.strip()
        payload["_resolved"] = {
            "branch": branch_label,
            "branch_id": branch_id,
            "vendor": vendor_label,
            "vendor_id": vendor_id,
            "inventory_location_id": loc_id,
            "inventory_location_fixed": True,
            "consolidation_skipped": skip_consolidation,
            "excel_line_count": len(wb.lines),
            "catalog_match_code_only": code_only,
        }
        return payload

    def find_existing_receipt(
        self, vendor_id: int, vendor_invoice_num: str
    ) -> dict | None:
        escaped = _escape_odata_string(vendor_invoice_num)
        rows = self.client.get(
            "/Receipts",
            params={
                "$filter": f"VendorID eq {vendor_id} and VendorInvoiceNum eq '{escaped}'",
                "$select": "ReceiptID,VendorInvoiceNum,ReceiptStatusName,"
                "ApprovedDate,ReceivedDate",
                "$top": "5",
            },
        )
        if isinstance(rows, list) and rows:
            return rows[0]
        return None

    def verify_receipt(self, receipt_id: int) -> dict:
        rows = self.client.get(
            "/Receipts",
            params={
                "$filter": f"ReceiptID eq {receipt_id}",
                "$select": "ReceiptID,ReceiptStatusName,ApprovedDate,ReceivedDate,"
                "VendorInvoiceNum",
                "$top": "1",
            },
        )
        if isinstance(rows, list) and rows:
            return rows[0]
        raise RuntimeError(f"Receipt {receipt_id} not found after create")

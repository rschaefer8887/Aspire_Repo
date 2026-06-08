"""Probe Aspire receipt + attachment API for a known receipt.

Writes a JSON snapshot to docs/attachment_probe_results.json for future reference.
Run: py scripts/probe_attachments.py [VendorInvoiceNum] [--try-upload]
"""
from __future__ import annotations

import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_common import AspireClient, require_credentials

RESULTS_PATH = ROOT / "docs" / "attachment_probe_results.json"


def _pp(data: Any) -> None:
    text = json.dumps(data, indent=2, default=str)
    print(text[:8000])


def _try_get(
    client: AspireClient,
    label: str,
    path: str,
    params: dict | None = None,
    *,
    results: dict[str, Any],
) -> Any:
    print(f"\n--- {label} ---")
    print(f"GET {path} params={params}")
    entry: dict[str, Any] = {"path": path, "params": params or {}}
    try:
        rows = client.get(path, params=params or {})
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        entry["error"] = str(exc)
        results[label] = entry
        return None
    entry["ok"] = True
    if isinstance(rows, list):
        entry["count"] = len(rows)
        print(f"count={len(rows)}")
        if rows:
            preview = rows[0] if len(rows) == 1 else rows[:3]
            display = preview
            if isinstance(preview, dict) and preview.get("FileData"):
                display = {**preview, "FileData": f"<base64 len={len(preview['FileData'])}>"}
            _pp(display)
            entry["preview"] = display
    else:
        display = rows
        if isinstance(rows, dict) and rows.get("FileData"):
            display = {**rows, "FileData": f"<base64 len={len(rows['FileData'])}>"}
        _pp(display)
        entry["response"] = display
    results[label] = entry
    return rows


def _try_post(
    client: AspireClient,
    label: str,
    path: str,
    body: dict,
    *,
    results: dict[str, Any],
) -> Any:
    print(f"\n--- {label} ---")
    print(f"POST {path}")
    entry: dict[str, Any] = {"path": path, "body_keys": list(body.keys())}
    try:
        resp = client.post(path, body)
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        entry["error"] = str(exc)
        results[label] = entry
        return None
    _pp(resp)
    entry["ok"] = True
    entry["response"] = resp
    results[label] = entry
    return resp


def find_receipt(client: AspireClient, vendor_inv: str) -> dict | None:
    escaped = vendor_inv.replace("'", "''")
    rows = client.get(
        "/Receipts",
        params={"$filter": f"VendorInvoiceNum eq '{escaped}'", "$top": "5"},
    )
    return rows[0] if isinstance(rows, list) and rows else None


def main() -> None:
    args = [a for a in sys.argv[1:] if a.startswith("-") is False]
    try_upload = "--try-upload" in sys.argv
    vendor_inv = (args[0] if args else "1314-INV").strip()
    client = AspireClient(*require_credentials())
    client.authenticate()

    results: dict[str, Any] = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "vendor_invoice_num": vendor_inv,
    }

    receipt = find_receipt(client, vendor_inv)
    if not receipt:
        print(f"No receipt for VendorInvoiceNum={vendor_inv!r}")
        sys.exit(1)

    rid = int(receipt["ReceiptID"])
    results["receipt"] = {
        "ReceiptID": rid,
        "VendorInvoiceNum": receipt.get("VendorInvoiceNum"),
        "PurchaseNumberWithBranchPrefix": receipt.get("PurchaseNumberWithBranchPrefix"),
        "ReceiptNumber": receipt.get("ReceiptNumber"),
    }
    print(f"ReceiptID={rid} VendorInvoiceNum={receipt.get('VendorInvoiceNum')!r}")
    print(f"PurchaseNumberWithBranchPrefix={receipt.get('PurchaseNumberWithBranchPrefix')!r}")
    print(f"ReceiptNumber={receipt.get('ReceiptNumber')!r}")

    attachment_rows = _try_get(
        client,
        "attachments_for_receipt",
        "/Attachments",
        {"$filter": f"ReceiptID eq {rid}", "$top": "10"},
        results=results,
    )
    attachment_id: int | None = None
    if isinstance(attachment_rows, list) and attachment_rows:
        attachment_id = int(attachment_rows[0]["AttachmentID"])

    _try_get(client, "attachments_top_3", "/Attachments", {"$top": "3"}, results=results)

    if attachment_id is not None:
        _try_get(
            client,
            "attachment_file_data",
            "/Attachments/AttachmentFileData",
            {"$filter": f"AttachmentID eq {attachment_id}"},
            results=results,
        )
        entry = results.get("attachment_file_data", {})
        preview = entry.get("preview")
        if isinstance(preview, dict) and preview.get("FileData"):
            fd = preview["FileData"]
            entry["preview"] = {
                **preview,
                "FileData": f"<base64 len={len(fd)}>",
            }

    _try_get(client, "attachment_types", "/AttachmentTypes", {"$top": "50"}, results=results)

    for link in ("new", "upload", str(attachment_id or "")):
        _try_get(
            client,
            f"new_link_{link or 'empty'}",
            "/Attachments/NewLink",
            {"link": link} if link else {},
            results=results,
        )

    # Validation-only POST probes (no real file upload unless --try-upload).
    probe_bodies: list[tuple[str, dict]] = [
        (
            "post_attachments_validation_missing_filedata",
            {"ObjectId": rid, "ObjectCode": "Receipt", "FileName": "probe-test.pdf"},
        ),
        (
            "post_attachments_validation_missing_filedata_with_type",
            {
                "ObjectId": rid,
                "ObjectCode": "Receipt",
                "FileName": "probe-test.pdf",
                "AttachmentTypeId": 10,
            },
        ),
    ]
    if try_upload:
        probe_bodies.append(
            (
                "post_attachments_with_tiny_pdf",
                {
                    "ObjectId": rid,
                    "ObjectCode": "Receipt",
                    "FileName": "probe-test.pdf",
                    "AttachmentTypeId": 10,
                    "FileData": base64.b64encode(b"%PDF-1.4 probe").decode("ascii"),
                },
            )
        )
    for label, body in probe_bodies:
        _try_post(client, label, "/Attachments", body, results=results)

    post_upload = _try_get(
        client,
        "attachments_for_receipt_after_probes",
        "/Attachments",
        {"$filter": f"ReceiptID eq {rid}", "$top": "20"},
        results=results,
    )
    if isinstance(post_upload, list):
        results["attachment_count_after_probes"] = len(post_upload)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()

"""Receive purchase receipts in Aspire (POST /Receipts/Receive only — not approve)."""

from __future__ import annotations

from datetime import date

from aspire_common import AspireClient


def receive_date_label(when: date | None = None) -> str:
    """Human-readable label for the receive date shown in prompts."""
    d = when or date.today()
    return d.strftime("%m/%d/%Y")


def receipt_is_received(receipt: dict) -> bool:
    """True when Aspire already has a receive timestamp or received status."""
    if receipt.get("ReceivedDate"):
        return True
    status = str(receipt.get("ReceiptStatusName") or "").strip().casefold()
    return "received" in status


def prompt_receive_receipt(
    receipt_id: int,
    *,
    vendor_invoice_num: str,
    receive_date: date | None = None,
) -> bool:
    label = receive_date_label(receive_date)
    inv = vendor_invoice_num.strip() or "(unknown)"
    while True:
        reply = input(
            f"Mark receipt {receipt_id} ({inv}) as received "
            f"(receive date: {label})? [Y/N]: "
        ).strip().upper()
        if reply in ("Y", "YES"):
            return True
        if reply in ("N", "NO"):
            return False
        print("Please enter Y or N.")


def prompt_batch_receive_receipts(
    receipt_count: int,
    *,
    receive_date: date | None = None,
) -> bool:
    """Ask once whether to receive every receipt in a bulk import."""
    label = receive_date_label(receive_date)
    while True:
        reply = input(
            f"Mark all {receipt_count} receipts in this run as received "
            f"(receive date: {label})? [Y/N]: "
        ).strip().upper()
        if reply in ("Y", "YES"):
            return True
        if reply in ("N", "NO"):
            return False
        print("Please enter Y or N.")


def resolve_batch_receive_decision(
    file_count: int,
    *,
    dry_run: bool,
    yes: bool,
    no: bool,
    bulk_mode: bool,
) -> bool | None:
    """
    Return receive decision for an import run.

    None  — prompt per receipt (single-file default).
    True  — receive without prompting.
    False — skip receive without prompting.
    """
    if yes:
        return True
    if no:
        return False
    if not bulk_mode:
        return None
    if dry_run:
        label = receive_date_label()
        print(
            f"\n[dry-run] Would prompt: Mark all {file_count} receipts as received "
            f"(date {label})? [Y/N]"
        )
        return True
    decision = prompt_batch_receive_receipts(file_count)
    if decision:
        print(
            f"  Receive: enabled for all {file_count} receipts in this run "
            f"(date {receive_date_label()})."
        )
    else:
        print("  Receive: declined for all receipts in this run.")
    return decision


def receive_receipt(client: AspireClient, receipt_id: int) -> None:
    """POST /Receipts/Receive — sets ReceivedDate server-side (typically today)."""
    client.post("/Receipts/Receive", {"ReceiptID": int(receipt_id)})

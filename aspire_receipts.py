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


def receive_receipt(client: AspireClient, receipt_id: int) -> None:
    """POST /Receipts/Receive — sets ReceivedDate server-side (typically today)."""
    client.post("/Receipts/Receive", {"ReceiptID": int(receipt_id)})

"""One-off: print Receipt note-like fields from Aspire API."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_common import AspireClient, require_credentials

def main() -> None:
    client = AspireClient(*require_credentials())
    client.authenticate()
    rid = int(sys.argv[1]) if len(sys.argv) > 1 else 1123
    rows = client.get(
        "/Receipts",
        params={
            "$filter": f"ReceiptID eq {rid}",
            "$top": "1",
        },
    )
    if not rows:
        print("No receipt found")
        return
    row = rows[0]
    for k in sorted(row.keys()):
        if any(x in k.lower() for x in ("note", "comment", "memo", "desc")):
            print(f"{k}: {row[k]!r}")

if __name__ == "__main__":
    main()

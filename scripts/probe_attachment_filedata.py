"""One-off: list receipt attachments and download AttachmentFileData."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aspire_common import AspireClient, require_credentials


def main() -> None:
    rid = int(sys.argv[1] if len(sys.argv) > 1 else "1214")
    aid = int(sys.argv[2] if len(sys.argv) > 2 else "11390")
    client = AspireClient(*require_credentials())
    client.authenticate()

    rows = client.get(
        "/Attachments",
        params={"$filter": f"ReceiptID eq {rid}", "$top": "20"},
    )
    print(f"ReceiptID {rid}: {len(rows)} attachment(s)")
    for row in rows:
        print(
            f"  AttachmentID={row['AttachmentID']} "
            f"OriginalFileName={row.get('OriginalFileName')!r} "
            f"DateUploaded={row.get('DateUploaded')}"
        )

    print(f"\nGET /Attachments/AttachmentFileData $filter=AttachmentID eq {aid}")
    try:
        data = client.get(
            "/Attachments/AttachmentFileData",
            params={"$filter": f"AttachmentID eq {aid}"},
        )
    except RuntimeError as exc:
        print(f"FAILED: {exc}")
        return

    if isinstance(data, list) and data:
        row = data[0]
        fd = row.get("FileData", "")
        print(json.dumps({**row, "FileData": f"<base64 len={len(fd)}>"}, indent=2))
    else:
        print(json.dumps(data, indent=2, default=str)[:4000])


if __name__ == "__main__":
    main()

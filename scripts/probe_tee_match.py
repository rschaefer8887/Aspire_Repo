"""Probe catalog match for IXIXFIPT PVC insert tee line."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import ReferenceData

LINES = [
    ('1-1/2" x 1" PVC Insert Tee IXIXFIPT', None),
    ('1-1/2" x 1" PVC INSERT TEE IXI', None),
    ('1-1/2" PVC Insert Tee IXIXFIPT', None),
    ('1-9/16" - 2-1/2" SS WORM DRIVE HOSE CLAMP', None),
]


def main() -> None:
    refs = ReferenceData()
    refs.load()
    print(f"Catalog rows: {len(refs.inventory)}")
    for desc, code in LINES:
        rec, conf, note = refs.match_line(desc, code)
        name = rec.item_name if rec else None
        alt = rec.item_alternate_name if rec else None
        icode = rec.item_code if rec else None
        print(f"\n--- {desc!r} ---")
        print(f"  Match: {name!r}")
        print(f"  Alt:   {alt!r}")
        print(f"  Code:  {icode!r}")
        print(f"  Conf:  {conf:.3f}")
        if note:
            safe = note.encode("ascii", errors="replace").decode("ascii")
            print(f"  Note:  {safe[:120]}")


if __name__ == "__main__":
    main()

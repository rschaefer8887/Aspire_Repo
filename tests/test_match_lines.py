"""Quick manual check of IDP catalog matching for HD Fowler invoice lines."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from idp_reference import ReferenceData

LINES = [
    ('XQ 1/4" X 100\' DRIP TUBE.170 X.250 RAIN BIRD', "2142"),
    ('1" MANIFOLD END CAP 18000 ACTION', None),
    ('PGV-101G 1" GLOBE VALVE W/FLOW CONTROL HUNTER', None),
    ('ECO-INDICATOR 1/2" FIPT YELLOW POP-UP STEM HUNTER', None),
    ('SBE-075 3/4" MIP X BARB ELBOW (50-BAG) SOLD BY THE EACH RAIN BIRD', None),
    ('SBE-050 1/2" MIP X BARB ELBOW (50-BAG) SOLD BY THE EACH RAIN BIRD', None),
    ('1-1/4" PVC INSERT COUPLING IXI', None),
    ('1 1/4" PVC INSERT 90 ELBOW IXI', None),
    ('1-1/4" X 1" PVC INSERT MALE ADAPTER IXMIPT', None),
    ('2" PVC INSERT COUPLING IXI', None),
    ('1-1/2" PVC INSERT 90 ELBOW IXI', None),
    ('1" BRASS BALL VALVE THREADED', None),
    ('3M RED/YELLOW WIRE NUT BAG QTY 100 270308', None),
    ('STAKING FLAG, BLUE', None),
    ('1" SCH 40 GALVANIZED MALE INSERT ADAPTER IMPORT', None),
    ('1-1/4" X 1" SCH 40 GALVANIZED MALE INSERT ADAPTER IMPORT', None),
    ('XFDE 17MM.6 GPH 12" SPACING 500\' ROLL EMITTER TUBING RAIN BIRD', None),
    ('XFFCOUP 17MM COUPLING BARB FITTING RAIN BIRD', None),
    ('XFFTEE 17MM TEE BARB FITTING RAIN BIRD', None),
    ('NO HUB TORQUE WRENCH', None),
]

if __name__ == "__main__":
    refs = ReferenceData()
    refs.load()
    th = 0.85
    for desc, sup in LINES:
        rec, conf, note = refs.match_line(desc, sup)
        flag = "LOW" if conf < th else "OK"
        code = rec.item_code if rec else ""
        name = (rec.item_name[:55] if rec else note) or ""
        print(f"{flag} {conf:.2f} {code!r:12} {name}")

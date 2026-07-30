import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))

from bb import KNOWN, build_bb
from search import fingerprint, screen


def test_screen_can_skip_existing_fingerprints():
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    fp = fingerprint(HX, HZ)

    recs = screen(
        [({"family": "bb", "id": 1}, HX, HZ)],
        min_k=2,
        min_d=2,
        trials=10,
        seed=0,
        skip_fingerprints={fp},
    )

    assert recs == []

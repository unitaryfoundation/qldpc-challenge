"""Regression tests for the optional accelerated research backend."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

import surrogate
from bb import KNOWN, build_bb
from search import sample_bb, screen
from surrogate import distance_rand

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def raises(exc, fn, *args, **kwargs):
    """Return whether calling ``fn`` raises ``exc``."""
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    return False


def main():
    print("research/ optional fast-backend test:")
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    n = HX.shape[1]

    check("NumPy backend finds distance 6", distance_rand(HX, HZ, trials=100, seed=0, backend="numpy") == 6)
    check("auto backend finds distance 6", distance_rand(HX, HZ, trials=100, seed=0, backend="auto") == 6)
    check("invalid backend is rejected", raises(ValueError, distance_rand, HX, HZ, trials=1, backend="invalid"))
    check("sentinel maps to infinity", surrogate._weight_or_inf(n + 1, n) == float("inf"))

    if surrogate._fast is not None:
        check(
            "fast backend finds distance 6", distance_rand(HX, HZ, trials=100, seed=0, backend="fast", threads=2) == 6
        )
        records = screen(sample_bb(4, seed=1), min_k=2, min_d=2, trials=20, backend="fast", threads=2)
        check("fast screening produced candidates", bool(records))
    else:
        check("missing fast backend is reported", raises(ImportError, distance_rand, HX, HZ, trials=1, backend="fast"))

    print("PASS" if not _fail else "FAIL: " + ", ".join(_fail))
    return 0 if not _fail else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Rebuild a CSS code from a `{constructor, params}` recipe and print its fingerprint.

    python research/kit/rebuild.py --constructor bb.build_bb \
        --params '{"l": 12, "m": 6, "A_terms": [[3,0],[0,2],[0,1]], "B_terms": [[2,0],[1,0],[0,3]]}'
    fingerprint=37b3cbe42450eeba

`constructor` is `<module>.<function>` under research/kit; `params` are its
keyword arguments; it must return (HX, HZ). The fingerprint is
qldpc_verify.css_fingerprint, which `qldpc reproduce --construction`
compares against the entry (#2220, #2955 item 3).
"""
import argparse
import importlib
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for p in (_HERE, os.path.join(_ROOT, "verify")):
    if p not in sys.path:
        sys.path.insert(0, p)


def rebuild(constructor, params):
    """Call ``<module>.<function>(**params)`` from research/kit; return (HX, HZ)."""
    if "." not in constructor:
        raise ValueError("constructor must be '<module>.<function>'")
    mod_name, fn_name = constructor.rsplit(".", 1)
    if not mod_name.replace("_", "").isalnum() or not os.path.exists(os.path.join(_HERE, mod_name + ".py")):
        raise ValueError(f"constructor module {mod_name!r} is not a module under research/kit")
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        raise ValueError(f"{mod_name} has no function {fn_name}")
    HX, HZ = fn(**params)
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    if HX.ndim != 2 or HZ.ndim != 2 or HX.shape[1] != HZ.shape[1]:
        raise ValueError("constructor did not return two check matrices on the same qubits")
    if ((HX.astype(np.int64) @ HZ.T) % 2).any():
        raise ValueError("constructor returned non-commuting checks")
    return HX, HZ


def fingerprint_of(HX, HZ):
    from qldpc_verify import css_fingerprint
    return css_fingerprint(HX, HZ)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--constructor", required=True, help="<module>.<function> under research/kit")
    ap.add_argument("--params", default="{}", help="JSON object of keyword arguments")
    ap.add_argument("--recipe", default=None,
                    help="JSON file holding {constructor, params}; overrides the two flags")
    args = ap.parse_args(argv)
    if args.recipe:
        with open(args.recipe, encoding="utf-8") as f:
            rec = json.load(f)
        constructor, params = rec["constructor"], rec.get("params", {})
    else:
        constructor, params = args.constructor, json.loads(args.params)
    HX, HZ = rebuild(constructor, params)
    print(f"n={HX.shape[1]} rows_x={HX.shape[0]} rows_z={HZ.shape[0]}")
    print(f"fingerprint={fingerprint_of(HX, HZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

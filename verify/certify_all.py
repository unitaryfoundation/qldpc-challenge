"""Run exact certification over codes/ and write a cert per code that closes.
A cert file certs/<slug>.json (d_exact=true) is what upgrades a code's
displayed tier to d=. Codes that do not close in budget simply get no cert
and stay at the self-certified upper bound. 2 workers, modest per-solve cap.
"""

import glob
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(__file__))
from certify import certify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "certs")
TLIM = 120


def run(path):
    slug = os.path.splitext(os.path.basename(path))[0]
    with open(path) as f:
        doc = json.load(f)
    try:
        res = certify(doc, tlim=TLIM)
    except Exception as e:
        return slug, f"error: {e}"
    if res.get("d_exact"):
        res["solver"] = "scipy/HiGHS cutoff IP"
        res["tlim_per_solve"] = TLIM
        # Every certificate declares what it is worth. A solver verdict with no
        # proof object is level "solver", which is what this writer produces;
        # verify/check_certs.py requires the block and refuses a stronger level
        # without an artifact to back it.
        res["verification"] = {"level": "solver"}
        os.makedirs(CERTS, exist_ok=True)
        with open(os.path.join(CERTS, slug + ".json"), "w") as f:
            json.dump(res, f, indent=1)
        return slug, f"CERTIFIED d={res['d']}"
    return slug, "not closed (stays upper bound)"


if __name__ == "__main__":
    paths = sorted(glob.glob(os.path.join(ROOT, "codes", "*.json")))
    with ProcessPoolExecutor(max_workers=2) as ex:
        for slug, msg in ex.map(run, paths):
            print(f"{slug}: {msg}", flush=True)
    print("CERTIFY_ALL DONE", flush=True)

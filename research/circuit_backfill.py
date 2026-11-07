"""Build and verify circuit tiers for board entries that have none.

Issue #1026. `qldpc submit` has built every new submission's circuit tier
with research/circuit_autogen.py since #1859, and nothing runs it over the
entries that were already on the board, so 48 of 1,832 entries carry a
circuit. This runs the same path over a slug list: generate (or take a
directory of submitter circuits per slug), run verify/circuit_verify.py on
the result exactly as the CLI does, and only then write circuits/<slug>/ and
the circuit block on codes/<slug>.json, with contributed_by naming who
built it. A code whose circuits do not verify is reported and left alone.

    python research/circuit_backfill.py 144-16-12 144-10-16 144-18-9 --by @vprusso
    python research/circuit_backfill.py 144-16-12 --circuits-root /tmp/sched --rounds 3

With --circuits-root, <root>/<slug>/memory_x.stim and memory_z.stim are read
as a submitter's own circuits (the from_files path), so a schedule found
elsewhere, such as the SAT-built interleaved ones of the 2026-09-19
comparison, can be committed through the same verifier.
"""
import argparse
import datetime
import json
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for p in ("cli", "verify", "research"):
    sys.path.insert(0, os.path.join(_ROOT, p))

import qldpc  # noqa: E402  (the CLI module; attach_circuit_tier is its path)


def backfill_one(slug, *, by, method, circuits_root=None, rounds=None,
                 seed=0, seconds=180.0, candidates=6, write=True):
    """Build, verify, and (if asked) write the circuit tier for one entry."""
    code_path = os.path.join(_ROOT, "codes", f"{slug}.json")
    with open(code_path, encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("circuit"):
        return {"slug": slug, "status": "has_circuit"}
    coords = (doc.get("locality") or {}).get("coordinates")
    args = types.SimpleNamespace(
        circuits=os.path.join(circuits_root, slug) if circuits_root else None,
        circuit_rounds=rounds, circuit_seed=seed, circuit_seconds=seconds,
        circuit_candidates=candidates, _coords=coords)
    try:
        files = qldpc.attach_circuit_tier(doc, args)
    except SystemExit as e:                      # a --circuits dir that failed
        return {"slug": slug, "status": "failed", "detail": str(e)}
    if files is None:
        return {"slug": slug, "status": "unavailable"}
    doc["circuit"]["contributed_by"] = {
        "by": list(by), "date": datetime.date.today().isoformat(),
        "method": method}
    rec = {"slug": slug, "status": "verified",
           "d_circ": {b: doc["circuit"]["d_circ"][b]["value"] for b in ("X", "Z")},
           "rounds": doc["circuit"]["rounds"]}
    if write:
        cdir = os.path.join(_ROOT, "circuits", slug)
        os.makedirs(cdir, exist_ok=True)
        for name, text in files.items():
            with open(os.path.join(cdir, name), "w", encoding="utf-8",
                      newline="\n") as f:
                f.write(text)
        with open(code_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
        rec["wrote"] = [os.path.relpath(code_path, _ROOT),
                        os.path.relpath(cdir, _ROOT)]
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--by", nargs="+", required=True,
                    help="@handles credited on the circuit block")
    ap.add_argument("--method", default=None,
                    help="how the schedule was built; defaults to the "
                         "generator's own description")
    ap.add_argument("--circuits-root", default=None,
                    help="directory with <slug>/memory_{x,z}.stim to commit "
                         "instead of generating")
    ap.add_argument("--rounds", type=int, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=180.0,
                    help="RIS budget per basis for the d_circ witness")
    ap.add_argument("--candidates", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and verify, write nothing")
    a = ap.parse_args(argv)
    method = a.method or ("circuit_autogen schedule search (two-block "
                          "interleaved, then layout, then generic), verified "
                          "by verify/circuit_verify.py before writing")
    out = []
    for slug in a.slugs:
        print(f"== {slug}", flush=True)
        rec = backfill_one(slug, by=a.by, method=method,
                           circuits_root=a.circuits_root, rounds=a.rounds,
                           seed=a.seed, seconds=a.seconds,
                           candidates=a.candidates, write=not a.dry_run)
        print(json.dumps(rec), flush=True)
        out.append(rec)
    bad = [r for r in out if r["status"] not in ("verified", "has_circuit")]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

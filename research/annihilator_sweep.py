"""Sweep the board's uncertified block-shaped entries with the annihilator attack.

The continuation issue #2706 asks for: every uncertified block-shaped entry
carries a recorded verdict from this attack at a stated budget, and the record
of who was run at what budget is committed so the next sweep can skip what
already held.

Selection is explicit rather than implied. An entry is a target when it has no
exact certificate and its blocklength is even, since an odd blocklength has no
two equal blocks for the attack to split. Entries already covered by a
committed audit are skipped unless --all is given, and the audit this run
writes lists them so the next one can do the same.

    python research/annihilator_sweep.py --out research/audits/<name>.json
    python research/annihilator_sweep.py --limit 20 --workers 6
"""

import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

from annihilator import attack  # noqa: E402

AUDITS = os.path.join(_ROOT, "research", "audits")


def already_run(paths):
    """Slugs a committed audit already records a verdict for."""
    seen = set()
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                a = json.load(f)
        except (OSError, ValueError):
            continue
        seen |= set(a.get("seconds_per_target") or {})
        seen |= {r["slug"] for r in (a.get("results") or []) if r.get("slug")}
        for e in a.get("errors") or []:
            seen.add(e if isinstance(e, str) else e.get("slug"))
    return {s for s in seen if s}


def targets(skip, include_all=False):
    """Uncertified even-blocklength entries, hardest cell first by size."""
    certified = set()
    for p in glob.glob(os.path.join(_ROOT, "certs", "*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                if json.load(f).get("d_exact"):
                    certified.add(os.path.splitext(os.path.basename(p))[0])
        except (OSError, ValueError):
            continue
    out = []
    for p in sorted(glob.glob(os.path.join(_ROOT, "codes", "*.json"))):
        slug = os.path.splitext(os.path.basename(p))[0]
        if slug in certified or (not include_all and slug in skip):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if doc["n"] % 2:
            continue
        out.append((doc["n"], slug, p))
    out.sort(reverse=True)
    return out


def one(job):
    """Attack one entry and return its record."""
    n, slug, path, trials, seed = job
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    try:
        rec = attack(doc, trials=trials, seed=seed)
    except Exception as e:  # noqa: BLE001
        return {"slug": slug, "n": n, "verdict": "error", "detail": str(e)[:300]}
    rec["slug"] = slug
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--trials",
        type=int,
        default=40_000,
        help="information sets inside each subspace (default "
        "40000, the budget the filed revisions were "
        "re-measured at)",
    )
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="re-run entries a committed audit already covers")
    ap.add_argument("--out", default=os.path.join(AUDITS, "annihilator-sweep-remainder.json"))
    a = ap.parse_args(argv)

    # Never read the file this run is about to write: a re-run would see
    # its own previous output as coverage, skip every target, and then
    # overwrite the record with an empty one.
    prior = [
        p for p in glob.glob(os.path.join(AUDITS, "annihilator-*.json")) if os.path.abspath(p) != os.path.abspath(a.out)
    ]
    skip = already_run(prior)
    todo = targets(skip, include_all=a.all)
    if a.limit:
        todo = todo[: a.limit]
    jobs = [(n, slug, p, a.trials, a.seed) for n, slug, p in todo]
    print(f"{len(jobs)} targets ({len(skip)} already covered by a committed audit)")

    results, t0 = [], time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for i, rec in enumerate(pool.map(one, jobs), 1):
            results.append(rec)
            if rec["verdict"] in ("refuted", "tightened", "error"):
                print(f"  {rec['slug']}: {rec['verdict']} {rec.get('lightest') or rec.get('detail') or ''}")
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  {round(time.time() - t0)}s")

    counts = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    audit = {
        "issue": 2706,
        "parent_issue": 1851,
        "dates": time.strftime("%Y-%m-%d"),
        "attack": (
            "single-block annihilator: kernel of one block of "
            "H = [A | B], information-set decoding inside the "
            "subspace; a vector in the subspace is a logical of the "
            "opposite type unless it lies in the row space of its "
            "own side"
        ),
        "tool": "research/kit/annihilator.py",
        "selection": (
            "every uncertified entry of even blocklength not already covered by a committed annihilator audit"
        ),
        "budget": {
            "trials_per_subspace": a.trials,
            "seed": a.seed,
            "core_hours": round(sum(r.get("secs") or 0 for r in results) / 3600, 2),
        },
        "targets_run": len(results),
        "counts": counts,
        "results": results,
        "seconds_per_target": {r["slug"]: r.get("secs") for r in results},
    }
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(audit, f, indent=2, sort_keys=True)
        f.write("\n")
    print(json.dumps(counts, sort_keys=True))
    print(f"wrote {os.path.relpath(a.out, _ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

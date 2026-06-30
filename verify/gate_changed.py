"""Distance-refutation gate for the codes changed in a PR (CI).

Runs two independent bounded, fixed-seed refutation searches -- RIS
(heuristic_distance) and the syndrome decoder (decode/distance, needs ldpc) --
only on the code/example submissions changed in this PR, and exits non-zero if
EITHER finds a logical lighter than the claimed distance (an over-claim). The
syndrome-decoder cross-check is skipped if ldpc is unavailable (RIS-only). Bulk
re-verification of the whole board stays cheap -- only new/changed files pay the
search cost (~10 s per method).

Usage:
  python verify/gate_changed.py [BASE] [files...]
    BASE     git ref to diff against (default origin/main); ignored if files given
    files    explicit code JSONs to gate (otherwise computed from the diff)
"""
import glob
import json
import os
import secrets
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heuristic_distance as H

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_syndrome():
    """The syndrome-decoder cross-check (decode/distance.py); needs ldpc. Returns
    the module or None so the gate degrades to RIS-only without it."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "decode"))
        import distance as sd
        return sd
    except Exception:
        return None


def changed_codes(base):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD", "--", "codes", "verify/fixtures"],
            cwd=ROOT, text=True)
    except Exception as e:
        print(f"(could not compute diff vs {base}: {e}); gating nothing")
        return []
    return [f for f in out.split() if f.endswith(".json")]


def board_record_slugs():
    """Slugs on the board's global (n, k, d, w) Pareto frontier. A code that
    claims to advance the frontier gets deeper refutation than a dominated one,
    so over-claims pay extra scrutiny exactly where gaming would matter."""
    rows = []
    for p in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        try:
            d = json.load(open(p))
            ck = d.get("checks", {})
            w = max((len(s) for s in ck.get("X", []) + ck.get("Z", [])), default=0)
            rows.append((os.path.splitext(os.path.basename(p))[0],
                         d["n"], d["k"], d["distance"]["d"], w))
        except Exception:
            continue
    rec = set()
    for i, a in enumerate(rows):
        dominated = any(
            j != i and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3] and b[4] <= a[4]
            and (b[1] < a[1] or b[2] > a[2] or b[3] > a[3] or b[4] < a[4])
            for j, b in enumerate(rows))
        if not dominated:
            rec.add(a[0])
    return rec


def main(argv):
    rest = [a for a in argv if not a.endswith(".json")]
    seed = None
    if "--seed" in rest:
        i = rest.index("--seed")
        seed = int(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    files = [a for a in argv if a.endswith(".json")]
    base = next((a for a in rest), "origin/main")
    if not files:
        files = changed_codes(base)
    if not files:
        print("no changed code submissions to gate")
        return 0

    # Random seed by design: a re-run draws a new search, so an over-claim cannot
    # reliably evade one fixed seed. The trade-off is that re-running can change the
    # verdict (a merge can fail later) -- the seed is printed so any run reproduces.
    if seed is None:
        seed = secrets.randbelow(2**31)
    print(f"refutation seed = {seed}  "
          f"(reproduce: python verify/gate_changed.py --seed {seed} <files>)\n")

    SD = _load_syndrome()
    if SD is None:
        print("note: syndrome-decoder cross-check unavailable (ldpc missing); "
              "running RIS only\n")

    refuted = 0
    records = board_record_slugs()
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        if not os.path.exists(p):                 # deleted/renamed away
            continue
        doc = json.load(open(p))
        if "distance" not in doc or "d" not in doc.get("distance", {}):
            continue
        # A code that advances the frontier is checked harder: several independent
        # RIS seeds, not one, so an over-claim cannot lean on a single search
        # missing the lighter logical. Dominated codes pay only the standard pass.
        slug = os.path.splitext(os.path.basename(f))[0]
        deep = slug in records
        seeds = [seed, seed + 2, seed + 3, seed + 5] if deep else [seed]
        # two independent mechanisms; a hit from EITHER (any seed) refutes.
        results = {}
        for si, s in enumerate(seeds):
            results[f"RIS#{si}"] = H.refute_check(doc, seed=s)
        if SD is not None:
            results["syndrome-decoder"] = SD.refute_check(doc, seed=seed + 1)
        hits = {m: (dh, wit) for m, (ref, dh, wit, _) in results.items() if ref}
        tag = f"deep, {len(seeds)} RIS seeds" if deep else "standard"
        if hits:
            refuted += 1
            for m, (dh, wit) in hits.items():
                print(f"REFUTED  {f} [{m}]: weight-{dh} logical < claimed distance "
                      f"{doc['distance']['d']}\n         witness = {wit}")
        else:
            print(f"ok       {f} ({tag}): no logical lighter than "
                  f"{doc['distance']['d']}")
    if refuted:
        print(f"\n{refuted} submission(s) refuted: claimed distance is not supported "
              f"by an independent search. See witnesses above.")
    return 1 if refuted else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

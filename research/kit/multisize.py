#!/usr/bin/env python3
"""Run an entry's stored recipe at neighboring sizes and report the cheap structural verdicts (issue #4031).

A board entry is an artifact. Since #2955 a promoted candidate may also carry
a recipe, the ``{constructor, params}`` the construction stage of
``repro/<slug>.json`` replays through ``research/kit/rebuild.py``. Nothing ran
a recipe at a second size, which is the test arXiv:2610.31352 uses to tell a
general construction from a lookup table. This module does, display-only:

* for every manifest whose construction stage is applicable, the recipe is
  rebuilt at its own parameters (and the fingerprint compared with the entry,
  as the construction stage does) and then at neighboring sizes under a
  per-constructor lift rule: ``bb.build_bb`` at (l +- 1, m) and (l, m +- 1)
  with the same monomials, which the constructor reduces modulo the new
  torus; ``gf2poly.cyclic_gb`` at m +- 1 with the same exponent supports. A
  constructor without a rule (a group-algebra code whose parameters are
  element indices into one GAP table) is reported as not liftable, and a
  manifest whose constructor module is not in the kit as not rebuildable;
* per lifted instance the verifier's cheap exact structural checks, the ones
  that need no distance search: the checks commute, the code encodes
  (k >= 1), its Tanner graph is connected, and n and the check weight stay
  within the board's caps. Each is a pass or fail with the numbers behind it.

The result is ``research/repro/multisize.json``, which the code page shows
under "Recipe at other sizes". No distance is searched or claimed at any
size, no ranking reads this, and no tier changes: like the layout
diagnostics (TRACKS.md), it is evidence shown beside the code. A recipe that
reproduces at neighboring sizes is evidence the entry is a construction
rather than a tuned artifact; one that does not is a fact about the recipe,
not a verdict on the entry.

    uv run --extra research python research/kit/multisize.py run      # writes the table
    uv run --extra research python research/kit/multisize.py check    # exit 1 on drift from the committed table
"""
import argparse
import datetime
import glob
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import gf2  # noqa: E402
import numpy as np  # noqa: E402
import rebuild  # noqa: E402
from qldpc_verify import (  # noqa: E402
    BASE_MAX_N,
    EXT_MAX_CHECK_WEIGHT,
    MAX_CHECK_WEIGHT,
    MAX_N,
    _matrix,
    _tanner_component_count,
    css_fingerprint,
)

REPRO = os.path.join(_ROOT, "repro")
CODES = os.path.join(_ROOT, "codes")
TABLE = os.path.join(_ROOT, "research", "repro", "multisize.json")
CHECKS = ("commutes", "encodes", "connected", "within_caps")


def lift_bb(params):
    """Neighbors of a torus: each side +- 1, and each side halved or doubled.

    The +- 1 sizes ask whether the monomials encode off their tuned torus;
    the halvings and doublings ask whether they define a family, which is
    how the [[72,12,6]] and [[144,12,12]] gross codes relate (same monomials,
    l doubled).
    """
    l, m = int(params["l"]), int(params["m"])  # noqa: E741
    sizes = [(l - 1, m), (l + 1, m), (l, m - 1), (l, m + 1), (2 * l, m), (l, 2 * m)]
    if l % 2 == 0:
        sizes.append((l // 2, m))
    if m % 2 == 0:
        sizes.append((l, m // 2))
    out, seen = [], set()
    for l2, m2 in sizes:
        if l2 < 2 or m2 < 2 or (l2, m2) in seen or (l2, m2) == (l, m):
            continue
        seen.add((l2, m2))
        out.append((f"l={l2}, m={m2}", dict(params, l=l2, m=m2)))
    return out


def lift_cyclic_gb(params):
    m = int(params["m"])
    return [(f"m={m2}", dict(params, m=m2)) for m2 in (m - 1, m + 1) if m2 >= 3]


LIFTS = {"bb.build_bb": ("l +- 1, m +- 1, and each side halved or doubled, same monomials "
                         "(reduced modulo the new torus)", lift_bb),
         "gf2poly.cyclic_gb": ("m +- 1, same exponent supports (reduced modulo the new m)", lift_cyclic_gb)}
NO_LIFT = {"group_algebra.build_2bga_small_group": "parameters are element indices into one GAP table; no size lift",
           "coset.build_coset": "parameters name subgroup elements of one group; no size lift",
           "products.hypergraph_product": "parameters are explicit matrices; no size lift"}


def recipe_of(manifest):
    """Return (constructor, params) from a manifest's construction stage, or None."""
    st = (manifest.get("stages") or {}).get("construction") or {}
    args = st.get("args") or []
    if st.get("status") != "applicable" or "--constructor" not in args or "--params" not in args:
        return None
    return args[args.index("--constructor") + 1], json.loads(args[args.index("--params") + 1])


def structural(HX, HZ):
    """Run the verifier's cheap exact checks at one size, with the numbers behind them."""
    n = HX.shape[1]
    rX, rZ = int(gf2.rank(HX)), int(gf2.rank(HZ))
    k = n - rX - rZ
    w = int(max(HX.sum(axis=1).max(), HZ.sum(axis=1).max()))
    supports = {"X": [list(map(int, np.flatnonzero(r))) for r in HX],
                "Z": [list(map(int, np.flatnonzero(r))) for r in HZ]}
    components = _tanner_component_count(supports, n)
    commutes = not ((HX.astype(np.int64) @ HZ.T) % 2).any()
    caps = n <= MAX_N and w <= MAX_CHECK_WEIGHT and (n <= BASE_MAX_N or w <= EXT_MAX_CHECK_WEIGHT)
    checks = {"commutes": commutes, "encodes": k >= 1, "connected": components == 1, "within_caps": caps}
    return {"n": n, "k": k, "w": w, "rank_X": rX, "rank_Z": rZ, "components": components,
            "checks": checks, "pass": all(checks.values())}


def instance(constructor, params):
    """Rebuild one instance and run the structural checks; a failing rebuild is a failing commute."""
    try:
        HX, HZ = rebuild.rebuild(constructor, params)
    except Exception as e:  # noqa: BLE001  (the constructor is replayed code; any failure is the verdict)
        return {"params": params, "error": f"{type(e).__name__}: {e}", "pass": False,
                "checks": {c: False for c in CHECKS}}
    rec = structural(HX, HZ)
    rec["params"] = params
    rec["fingerprint"] = css_fingerprint(HX, HZ)
    return rec


def entry_fingerprint(slug):
    with open(os.path.join(CODES, slug + ".json"), encoding="utf-8") as f:
        doc = json.load(f)
    n = doc["n"]
    return css_fingerprint(_matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n))


def analyze(slug, manifest):
    """One manifest's multi-size record."""
    recipe = recipe_of(manifest)
    if recipe is None:
        st = (manifest.get("stages") or {}).get("construction") or {}
        return {"status": "no_recipe", "reason": st.get("reason") or "construction stage not applicable"}
    constructor, params = recipe
    rec = {"constructor": constructor, "params": params}
    mod = constructor.rsplit(".", 1)[0]
    if not os.path.exists(os.path.join(_HERE, mod + ".py")):
        rec.update(status="constructor_missing",
                   reason=f"research/kit/{mod}.py is not in the kit, so the recipe cannot be replayed here")
        return rec
    own = instance(constructor, params)
    rec["own"] = own
    rec["reproduces_entry"] = (own.get("fingerprint") == entry_fingerprint(slug)
                               if os.path.exists(os.path.join(CODES, slug + ".json")) else None)
    if constructor in LIFTS:
        rule, lift = LIFTS[constructor]
        sizes = [dict(instance(constructor, p), label=label) for label, p in lift(params)]
        rec.update(status="lifted", rule=rule, sizes=sizes,
                   passed=sum(s["pass"] for s in sizes), tried=len(sizes))
    else:
        rec.update(status="no_lift_rule",
                   reason=NO_LIFT.get(constructor, "no size-lift rule is defined for this constructor"))
    return rec


def build_table():
    entries = {}
    for path in sorted(glob.glob(os.path.join(REPRO, "*.json"))):
        with open(path, encoding="utf-8") as f:
            manifest = json.load(f)
        slug = manifest.get("slug") or os.path.splitext(os.path.basename(path))[0]
        entries[slug] = analyze(slug, manifest)
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    counts = {"manifests": len(entries)}
    for s in ("lifted", "no_lift_rule", "constructor_missing", "no_recipe"):
        counts[s] = sum(1 for e in entries.values() if e.get("status") == s)
    counts["sizes_tried"] = sum(e.get("tried", 0) for e in entries.values())
    counts["sizes_passed"] = sum(e.get("passed", 0) for e in entries.values())
    return {"multisize_version": 1, "issue": 4031,
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(), "head": head,
            "method": ("each recipe rebuilt by research/kit/rebuild.py at its own parameters and at the "
                       "sizes its constructor's lift rule names; per size the verifier's cheap exact "
                       "checks: commutation, k >= 1, a connected Tanner graph, n and check weight within "
                       "the caps; no distance search at any size"),
            "caveat": ("display-only: a pass is a structural fact about the recipe at that size, not a "
                       "distance claim and not a novelty claim; nothing here ranks or tiers"),
            "lifts": {c: rule for c, (rule, _) in LIFTS.items()},
            "counts": counts, "entries": entries}


def verdicts(table):
    """Reduce a table to its comparable part: per slug, status and per-size pass flags."""
    return {s: (e.get("status"), [x["pass"] for x in e.get("sizes", [])], e.get("reproduces_entry"))
            for s, e in table["entries"].items()}


def write(table, path=TABLE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, indent=1, sort_keys=True)
        f.write("\n")


def summary(table):
    c = table["counts"]
    lines = [f"{c['manifests']} manifests: {c['lifted']} lifted ({c['sizes_passed']} of {c['sizes_tried']} "
             f"sizes pass), {c['no_lift_rule']} without a lift rule, {c['constructor_missing']} with a "
             f"constructor not in the kit, {c['no_recipe']} without a recipe"]
    for slug, e in table["entries"].items():
        if e.get("status") == "lifted":
            sizes = ", ".join(f"{s['label']}: " + (f"[[{s['n']},{s['k']}]] w={s['w']} "
                                                   f"{'pass' if s['pass'] else 'FAIL'}" if "n" in s
                                                   else f"FAIL ({s.get('error')})") for s in e["sizes"])
            lines.append(f"  {slug} ({e['constructor']}; reproduces the entry: {e['reproduces_entry']}): {sizes}")
        else:
            lines.append(f"  {slug}: {e['status']}" + (f" ({e.get('reason')})" if e.get("reason") else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="rebuild every recipe at its sizes and write the table")
    r.add_argument("--out", default=TABLE)
    c = sub.add_parser("check", help="recompute and compare with the committed table; exit 1 on drift")
    c.add_argument("--table", default=TABLE)
    a = ap.parse_args(argv)
    table = build_table()
    if a.cmd == "run":
        write(table, a.out)
        print(f"wrote {os.path.relpath(a.out, _ROOT)}")
        print(summary(table))
        return 0
    try:
        with open(a.table, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        print("no committed multi-size table")
        return 1
    new, was = verdicts(table), verdicts(old)
    drift = {s for s in set(new) | set(was) if new.get(s) != was.get(s)}
    if drift:
        print("multi-size verdicts drifted for: " + " ".join(sorted(drift)))
        print(summary(table))
        return 1
    print(f"ok: the committed multi-size table matches {len(new)} manifest(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

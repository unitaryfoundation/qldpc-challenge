#!/usr/bin/env python3
"""Build the certification queue: every upper-bound entry, what certifying it needs, in order (issue #4027).

1,600-odd board entries carry a distance that is a witnessed upper bound and
no certificate. Which of them a sane budget could close is not written down
anywhere, so exact-distance work (#3629 and its like) runs off hand-picked
lists. This script writes ``todo.json`` from ``codes/`` and ``certs/``:

* who is in it: every entry whose distance tier is an upper bound, decided the
  way the site decides it (``site/build.py``: an entry is exact only when
  ``certs/<slug>.json`` says ``d_exact`` and agrees with the entry's current
  distance and side values). An honored certificate removes an entry; a
  distance change re-lists it at the new value, because the queue is
  regenerated, never edited;
* what each needs: n, k, d, w, the cells it competes in, whether it is a record
  (on a cell frontier or the global one, ``compute_records``), and per side the
  inputs ``verify/certify.py`` decides with: the number of logical generators
  (one MILP each, k per side), and the LP size (n + rank + 1 variables,
  rank + 2 constraints, the rank being that of the side's kernel matrix);
* a difficulty band, from the SAT-tier certificates already on main: the
  honored solver and proof_log certificates record seconds per side, so an
  entry's peers (certified entries within 25% of its n and within 2 of its d)
  give a median cost and a count. A: at least three peers, median under ten
  minutes. B: a peer under an hour, or n <= 400 and d <= 16, the region the
  October 2026 Perlmutter run closed at 2,400 s per solve. C: n <= 700 and
  d <= 24, beyond any peer but inside what the tier has reached (largest
  certified d is 19). D: everything else, which no certificate on main
  resembles. P: a stabilizer code, for which no certifier exists yet.
  research/cost/cost_table.json, when present, is cross-checked: the nearest
  measured shape's certification status rides along;
* the order: records first, then by band, then cheapest first (peer median,
  then n), then slug. A cheap certificate on an entry no frontier needs buys
  less than a dear one on a record, so value enters before cost.

Nothing here is a distance claim: every d in the queue stays an upper bound
until a certificate says otherwise, and the queue certifies nothing.

    uv run python research/certs/certification_queue.py            # writes todo.json
    uv run python research/certs/certification_queue.py --check    # is the committed queue current?
"""
import argparse
import datetime
import glob
import importlib.util
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
CODES = os.path.join(ROOT, "codes")
CERTS = os.path.join(ROOT, "certs")
TODO = os.path.join(HERE, "todo.json")
COST = os.path.join(ROOT, "research", "cost", "cost_table.json")

BANDS = {
    "A": "at least three certified peers (within 25% of n, within 2 of d) with a median "
         "side time under 600 s",
    "B": "a certified peer under 3,600 s, or n <= 400 and d <= 16 (the region the October "
         "2026 Perlmutter run closed at 2,400 s per solve)",
    "C": "n <= 700 and d <= 24: beyond any certified peer, inside what the SAT tier has "
         "reached (largest certified d is 19)",
    "D": "n > 700 or d > 24: nothing certified on main resembles it",
    "P": "stabilizer code: no Pauli-weight certifier exists yet",
}
BAND_ORDER = {b: i for i, b in enumerate("ABCDP")}
RULE = ("records first (on a cell frontier or the global one), then band A to D (P last), then "
        "cheapest first by the peers' median side seconds and then by n, then slug; regenerated "
        "from codes/ and certs/, so an honored certificate removes an entry and a changed distance "
        "re-lists it at the new value")


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_queue", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def honored_certs(build):
    """{slug: cert} for every certificate the site honors, with the entry's n and d."""
    out = {}
    for path in glob.glob(os.path.join(CERTS, "*.json")):
        slug = os.path.splitext(os.path.basename(path))[0]
        cpath = os.path.join(CODES, slug + ".json")
        if not os.path.exists(cpath):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                cert = json.load(f)
            with open(cpath, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if cert.get("d_exact") and build.cert_consistent(cert, doc):
            out[slug] = (cert, doc)
    return out


def peer_costs(honored):
    """(n, d, seconds) for every honored certificate that records per-side seconds."""
    rows = []
    for slug, (cert, doc) in honored.items():
        secs = [v.get("secs") for v in (cert.get("sides") or {}).values() if isinstance(v, dict)]
        if secs and all(isinstance(s, (int, float)) for s in secs):
            rows.append((doc["n"], doc["distance"]["d"], max(secs), slug))
    return rows


def peers_for(n, d, rows):
    near = [s for pn, pd, s, _ in rows if 0.75 * n <= pn <= 1.25 * n and abs(pd - d) <= 2]
    return (round(statistics.median(near), 1), len(near)) if near else (None, 0)


def band_for(code_type, n, d, median, count):
    if code_type == "stabilizer":
        return "P"
    if count >= 3 and median is not None and median <= 600:
        return "A"
    if (count >= 1 and median is not None and median <= 3600) or (n <= 400 and d <= 16):
        return "B"
    if n <= 700 and d <= 24:
        return "C"
    return "D"


def cost_table_shapes():
    """(n, w, code_type) -> certify statuses from the measured cost table, when it exists."""
    try:
        with open(COST, encoding="utf-8") as f:
            table = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for e in table.get("entries", []):
        c = e.get("certify") or {}
        status = {s: c[s].get("status") for s in ("X", "Z") if isinstance(c.get(s), dict)} \
            or {"P": c.get("status")}
        out.append((e["n"], e["w"], e["code_type"], e["slug"], status))
    return out


def nearest_measured(n, w, code_type, shapes):
    cands = [s for s in shapes if s[2] == code_type]
    if not cands:
        return None
    best = min(cands, key=lambda s: (abs(s[0] - n) / max(n, 1) + abs(s[1] - w) / max(w, 1)))
    return {"slug": best[3], "n": best[0], "w": best[1], "certify": best[4]}


def build_queue(build, entries, records):
    import gf2
    import qldpc_verify as V
    honored = honored_certs(build)
    rows = peer_costs(honored)
    shapes = cost_table_shapes()
    queue = []
    for i, e in enumerate(entries):
        if e["tier"] == "exact":
            continue
        slug = e["slug"]
        with open(os.path.join(CODES, slug + ".json"), encoding="utf-8") as f:
            doc = json.load(f)
        stab = doc.get("code_type") == "stabilizer"
        n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
        rec = {"slug": slug, "code_type": "stabilizer" if stab else "CSS", "n": n, "k": k, "d": d,
               "w": e["w"], "record": i in records,
               "cells": [f"{L}~{W}" for (L, W) in build.cells(e)], "sides": {}}
        if stab:
            rec["sides"]["P"] = {"value": (doc["distance"].get("P") or {}).get("value", d),
                                 "note": "Pauli weight; no certifier"}
        else:
            HX = V._matrix(doc["checks"]["X"], n)
            HZ = V._matrix(doc["checks"]["Z"], n)
            rX, rZ = int(gf2.rank(HX)), int(gf2.rank(HZ))
            gens = n - rX - rZ
            for side, rank_kernel in (("X", rZ), ("Z", rX)):
                claim = doc["distance"].get(side)
                if not claim:
                    continue
                rec["sides"][side] = {"value": claim["value"], "generators": gens,
                                      "lp_vars": n + rank_kernel + 1,
                                      "lp_constraints": rank_kernel + 2,
                                      "milps_at_most": gens}
        median, count = peers_for(n, d, rows) if not stab else (None, 0)
        rec["peers"] = {"median_side_secs": median, "count": count}
        rec["band"] = band_for(rec["code_type"], n, d, median, count)
        near = nearest_measured(n, e["w"], rec["code_type"], shapes)
        if near:
            rec["measured_shape"] = near
        queue.append(rec)
    queue.sort(key=lambda r: (0 if r["record"] else 1, BAND_ORDER[r["band"]],
                              r["peers"]["median_side_secs"] if r["peers"]["median_side_secs"] is not None
                              else float("inf"), r["n"], r["slug"]))
    for pos, r in enumerate(queue, 1):
        r["position"] = pos
    return queue, len(honored), len(rows)


def payload(build, entries, records):
    queue, n_honored, n_timed = build_queue(build, entries, records)
    counts = {"upper_bound": len(queue), "records": sum(r["record"] for r in queue),
              "by_band": {b: sum(r["band"] == b for r in queue) for b in BANDS},
              "exact": n_honored, "entries": len(entries),
              "certificates_with_seconds": n_timed}
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    return {"queue_version": 1, "issue": 4027,
            "date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(), "head": head,
            "rule": RULE, "bands": BANDS,
            "caveat": ("every d here is a witnessed upper bound until a certificate says otherwise; "
                       "the band is an estimate from other entries' certificates on other machines, "
                       "not a promise"),
            "counts": counts, "next_ten": [r["slug"] for r in queue[:10]], "entries": queue}


def write(p, path=TODO):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(p, f, indent=1, sort_keys=True)
        f.write("\n")


def summary(p):
    c = p["counts"]
    lines = [f"{c['upper_bound']} upper-bound entries ({c['records']} records) of {c['entries']}; "
             f"{c['exact']} exact; bands " + ", ".join(f"{b} {n}" for b, n in c["by_band"].items()),
             "next ten: " + " ".join(p["next_ten"])]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=TODO)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when the committed queue's membership differs from today's board")
    a = ap.parse_args(argv)
    build = load_site_build()
    entries = build.load_entries()
    records = build.compute_records(entries)
    p = payload(build, entries, records)
    if a.check:
        try:
            with open(a.out, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            print("no committed queue")
            return 1
        want = {(r["slug"], r["d"]) for r in p["entries"]}
        have = {(r["slug"], r["d"]) for r in old["entries"]}
        if want != have:
            print(f"queue is stale: {len(want - have)} to add, {len(have - want)} to drop")
            return 1
        print("ok: the committed queue matches today's board")
        return 0
    write(p, a.out)
    print(f"wrote {os.path.relpath(a.out, ROOT)}")
    print(summary(p))
    return 0


if __name__ == "__main__":
    sys.exit(main())

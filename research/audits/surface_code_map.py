#!/usr/bin/env python3
"""Level 1 finite-size map of the verified board against the surface-code baseline (issue #4601).

Issue #4601 asks first for a structural map: for k logical qubits, which
verified codes encode them in fewer data qubits than the surface code at the
same distance, in which locality and check-weight cell, and with what
verification status. This script reads the board through site/build.py's
loader (the verifier's own structural pass) and, for each k target, each
track (2D single-layer, 2D bilayer, unrestricted) and each check-weight cap,
finds at every distance d the smallest-n entry with at least k logical qubits
and a distance bound of at least d. The baseline is k independent rotated
surface-code patches, n = k d^2 data qubits at exact distance d, weight 4,
one layer; the board's own weight-4 single-layer topological entries
(rotated, dense-packed, and holey surface codes, and toric codes) are
reported beside it where one covers the (k, d) point.

The comparison is structural only: data qubits, no syndrome ancillas. The
operational comparison in #4601 (total qubits at matched logical error rate)
is Level 2 and is not computed here. A board distance is a witness-backed
upper bound unless the entry carries an exact certificate (tier "exact"),
while the baseline distance is exact, so a row at tier "ub" beats the surface
code only if its bound is tight. The per-side distances of each entry are
carried so a reader can see when one side is the weak one.

    uv run python research/audits/surface_code_map.py --markdown
    uv run python research/audits/surface_code_map.py --out research/audits/surface_code_map-<date>.json
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

LOCALITY_ORDER = {"local-2d-single": 0, "local-2d-bilayer": 1, "unrestricted": 2}
TRACKS = (("local-2d-single", "2D single-layer"),
          ("local-2d-bilayer", "2D bilayer"),
          ("unrestricted", "unrestricted"))
WEIGHT_CAPS = (4, 6, 8, None)
K_TARGETS = (1, 10, 25, 50, 100)
D_MIN = 3
SCHEMA = "qldpc-surface-code-map/1"


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_surface_map", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _w(e):
    w = e.get("w")
    return w if isinstance(w, int) else 10 ** 6


def eligible(e, locality, weight_cap, code_type="CSS"):
    """Return whether entry e belongs to the (locality, weight cap) pool.

    Locality classes nest: a single-layer code is also a bilayer code and an
    unrestricted one. A weight cap of None admits every check weight.
    """
    return (e.get("code_type", "CSS") == code_type
            and LOCALITY_ORDER.get(e.get("locality_class"), 9) <= LOCALITY_ORDER[locality]
            and (weight_cap is None or _w(e) <= weight_cap))


def is_board_surface(e):
    """Return whether e is one of the board's own surface-code family entries.

    These are the weight-4 single-layer 2D entries tagged topological: rotated,
    dense-packed, and holey surface codes, and toric codes.
    """
    return (e.get("family") == "topological" and e.get("locality_class") == "local-2d-single"
            and _w(e) <= 4)


def best_entry(pool, k, d):
    """Return the smallest-n entry of the pool with k' >= k and d' >= d.

    Ties go to an exact distance, then more logical qubits, then lower check
    weight, then slug. None when nothing in the pool covers (k, d).
    """
    cands = [e for e in pool if e["k"] >= k and e["d"] >= d]
    if not cands:
        return None
    return min(cands, key=lambda e: (e["n"], 0 if e.get("tier") == "exact" else 1,
                                     -e["k"], _w(e), e["slug"]))


def _summary(e):
    return {"n": e["n"], "k": e["k"], "d": e["d"], "d_X": e.get("d_X"), "d_Z": e.get("d_Z"),
            "w": e.get("w"), "tier": e.get("tier"), "locality_class": e.get("locality_class"),
            "family": e.get("family")}


def finite_size_map(entries, k_targets=K_TARGETS, tracks=TRACKS, weight_caps=WEIGHT_CAPS,
                    d_min=D_MIN, code_type="CSS", per_k_max=100):
    """Build the map from a list of board entries.

    Per (track, weight cap, k target): the best entry at each d against k d^2.
    Per k target: the price of locality at any weight. Per k from 1 to
    per_k_max: the best factor over d in each track. Entries named anywhere are
    collected once under "entries", keyed by slug.
    """
    named = {}

    def name(e):
        if e is None:
            return None
        named.setdefault(e["slug"], _summary(e))
        return e["slug"]

    surface = [e for e in entries if e.get("code_type", "CSS") == code_type and is_board_surface(e)]
    out = {"code_type": code_type, "k_targets": list(k_targets), "d_min": d_min,
           "baseline": "k independent rotated surface-code patches: n = k d^2 data qubits, "
                       "exact distance d, max check weight 4, one layer",
           "cells": [], "board_surface": [], "locality_price": [], "per_k": []}
    pools = {(loc, cap): [e for e in entries if eligible(e, loc, cap, code_type)]
             for loc, _ in tracks for cap in weight_caps}
    for loc, label in tracks:
        for cap in weight_caps:
            pool = pools[(loc, cap)]
            for k in k_targets:
                d_max = max((e["d"] for e in pool if e["k"] >= k), default=0)
                rows = []
                for d in range(d_min, d_max + 1):
                    b = best_entry(pool, k, d)
                    if b is None:
                        continue
                    n_sc = k * d * d
                    rows.append({"d": d, "n_patches": n_sc, "best": name(b),
                                 "ratio": round(n_sc / b["n"], 3), "beats": b["n"] < n_sc})
                beats = [r for r in rows if r["beats"]]
                top = max(beats, key=lambda r: r["ratio"]) if beats else None
                out["cells"].append({
                    "track": loc, "label": label, "weight_cap": cap, "k": k,
                    "entries_in_pool": len(pool), "rows": rows,
                    "first_d_beating": beats[0]["d"] if beats else None,
                    "last_d_beating": beats[-1]["d"] if beats else None,
                    "d_beating_count": len(beats),
                    "best": {"d": top["d"], "ratio": top["ratio"], "slug": top["best"]} if top else None})
    for k in k_targets:
        unres, bil, sing = (pools[("unrestricted", None)], pools[("local-2d-bilayer", None)],
                            pools[("local-2d-single", None)])
        d_max = max((e["d"] for e in unres if e["k"] >= k), default=0)
        for d in range(d_min, d_max + 1):
            s = best_entry(surface, k, d)
            if s is not None:
                out["board_surface"].append({"k": k, "d": d, "slug": name(s)})
            bu = best_entry(unres, k, d)
            if bu is None:
                continue
            bb, bs = best_entry(bil, k, d), best_entry(sing, k, d)
            out["locality_price"].append({
                "k": k, "d": d, "n_patches": k * d * d,
                "unrestricted": name(bu), "bilayer": name(bb), "single": name(bs),
                "bilayer_over_unrestricted": round(bb["n"] / bu["n"], 3) if bb else None,
                "single_over_unrestricted": round(bs["n"] / bu["n"], 3) if bs else None})
    for k in range(1, per_k_max + 1):
        rec = {"k": k}
        for loc, _ in tracks:
            pool = [e for e in pools[(loc, None)] if e["k"] >= k]
            best = None
            for d in range(d_min, max((e["d"] for e in pool), default=0) + 1):
                b = best_entry(pool, k, d)
                if b is None:
                    continue
                ratio = k * d * d / b["n"]
                if best is None or ratio > best["ratio"]:
                    best = {"d_target": d, "ratio": round(ratio, 3), "slug": name(b)}
            rec[loc] = best
        out["per_k"].append(rec)
    out["entries"] = dict(sorted(named.items()))
    return out


def record(entries, **kw):
    """Wrap the map with the provenance a committed record carries."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    rec = {"schema": SCHEMA, "generated": today, "head": _head(),
           "entries_considered": len(entries),
           "note": ("Structural comparison on data qubits only; board distances at tier ub are "
                    "witness-backed upper bounds and beat the exact-distance baseline only if tight. "
                    "An entry with k' >= k stands in for k logical qubits (spare logicals are wasted).")}
    rec.update(finite_size_map(entries, **kw))
    return rec


def _cellname(loc, cap):
    return f"{loc} / w<={cap}" if cap else f"{loc} / any w"


def markdown(rec):
    """Render the map as the tables a fieldnote quotes."""
    E = rec["entries"]

    def fmt(r):
        if r is None:
            return "none"
        b = E[r["best"]]
        return f"{r['best']} (n={b['n']}, x{r['ratio']}, {b['tier']})"

    lines = [f"# Finite-size map against the surface code ({rec['generated']}, head {str(rec['head'])[:9]}, "
             f"{rec['entries_considered']} entries)", ""]
    cells = {(c["track"], c["weight_cap"], c["k"]): c for c in rec["cells"]}
    surface = {(s["k"], s["d"]): s["slug"] for s in rec["board_surface"]}
    cols = [("local-2d-single", None), ("local-2d-bilayer", None), ("unrestricted", 8), ("unrestricted", None)]
    for k in rec["k_targets"]:
        lines += [f"## k = {k}", "",
                  "| d | k d^2 | board surface | " + " | ".join(_cellname(*c) for c in cols) + " |",
                  "|---:|---:|---|" + "---|" * len(cols)]
        ds = sorted({r["d"] for c in cols for r in cells[(c[0], c[1], k)]["rows"]})
        for d in ds:
            cells_d = []
            for c in cols:
                rr = [r for r in cells[(c[0], c[1], k)]["rows"] if r["d"] == d]
                cells_d.append(fmt(rr[0]) if rr else "none")
            s = surface.get((k, d))
            surf = f"{s} (n={E[s]['n']})" if s else "none"
            lines.append(f"| {d} | {k * d * d} | {surf} | " + " | ".join(cells_d) + " |")
        lines.append("")
        for c in cols:
            cell = cells[(c[0], c[1], k)]
            if cell["best"]:
                b = cell["best"]
                lines.append(f"- {_cellname(*c)}: beats k d^2 first at d = {cell['first_d_beating']}, last at "
                             f"d = {cell['last_d_beating']} ({cell['d_beating_count']} distances in all); best "
                             f"factor x{b['ratio']} at d = {b['d']} ({b['slug']}, n = {E[b['slug']]['n']}, "
                             f"{E[b['slug']]['tier']})")
            else:
                lines.append(f"- {_cellname(*c)}: nothing beats k d^2 at any d")
        lines.append("")
    lines += ["## Price of 2D locality (any weight; n of the best 2D entry over n of the best unrestricted entry)",
              "", "| k | d | unrestricted | bilayer | single |", "|---:|---:|---|---|---|"]
    for p in rec["locality_price"]:
        def _s(key, ratio):
            s = p[key]
            return f"{s} n={E[s]['n']} (x{p[ratio]})" if s else "none"
        u = p["unrestricted"]
        lines.append(f"| {p['k']} | {p['d']} | {u} n={E[u]['n']} | "
                     f"{_s('bilayer', 'bilayer_over_unrestricted')} | {_s('single', 'single_over_unrestricted')} |")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    ap.add_argument("--out", default=os.path.join(HERE, f"surface_code_map-{today}.json"))
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--code-type", default="CSS", choices=("CSS", "stabilizer"))
    ap.add_argument("--k", type=int, nargs="*", default=list(K_TARGETS))
    ap.add_argument("--d-min", type=int, default=D_MIN)
    a = ap.parse_args(argv)
    build = load_site_build()
    entries = build.load_entries()
    rec = record(entries, k_targets=tuple(a.k), d_min=a.d_min, code_type=a.code_type)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, indent=1, sort_keys=True)
        f.write("\n")
    print(f"wrote {os.path.relpath(a.out, ROOT)}")
    print(markdown(rec) if a.markdown else markdown(rec).splitlines()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Campaign 3 of issue #6242: a proximity ranking of two-block schedules against the RIS screen.

For each bivariate-bicycle entry with a circuit tier, the same pool of
interleaved two-block schedules (research/circuit_autogen.two_block_candidates,
flagged as the generator files them) is ranked two ways:

* ris: what the generator does today, the first schedule whose two-round RIS
  screen finds nothing below d (research/circuit_autogen.screen);
* proximity: the schedule with the best proximity profile
  (research/kit/proximity.py, after arXiv:2611.19715) at the committed round
  count, P_min then P_mean over the mechanisms of its RIS witnesses.

Each pick is then finished exactly as a submission is (deep RIS, verifier), and
its per-round logical error rate is measured beside the committed circuits
with verify/ler_measure.py at the rates given. One JSON record per entry under
--out, a summary.json, and a table; nothing is written to codes/ or
circuits/. The decision gate the plan sets (proximity wins on at least 7 of
10) is read off the summary.

    uv run --extra research python research/kit/proxima_bakeoff.py 72-12-6 60-8-6 \
        --pool 12 --seconds 60 --ler-p 0.005 0.002 --ler-shots 20000 40000
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "verify"), os.path.join(_ROOT, "research"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import circuit_autogen as ca  # noqa: E402
import circuit_search as cs  # noqa: E402
import circuit_tools as ct  # noqa: E402
import numpy as np  # noqa: E402
import proximity as px  # noqa: E402
from circuit_verify import SIDE_FILES  # noqa: E402


def _write(path, obj):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(obj, indent=1, sort_keys=True) + "\n")


def pool_of(HX, HZ, rounds, seed, size):
    got = ca.two_block_candidates(HX, HZ, np.random.default_rng(seed), rounds)
    if got is None:
        return None, []
    label, it = got
    out = []
    for notes, layers in it:
        out.append((notes, layers))
        if len(out) >= size:
            break
    return label, out


def profile_candidate(HX, HZ, rounds, layers, size, seeds, seed_seconds, wits, hook_limit):
    """Per-basis proximity profiles at the committed round count.

    None when a basis is not deterministic or over the mechanism cap. Besides
    the RIS seeds, each basis is seeded with the final-readout flips along the
    code's own logical of the opposite type (circuit_autogen.readout_witness),
    a weight-d undetected logical fault set every schedule of the code has.
    """
    out = {}
    for basis in ("Z", "X"):
        _, dem = ca._dem_of(HX, HZ, rounds, basis, layers)
        if dem is None or dem.num_errors > ca.MAX_DEM_MECHANISMS:
            return None
        fast = ct._GF is not None and hasattr(ct._GF, "dem_rand_witness")
        trials, _ = ca._circuit_budget(dem.num_errors, fast)
        opp = "X" if basis == "Z" else "Z"
        extra = []
        support = wits.get(opp)
        if support:
            ro = ca.readout_witness(dem, HX, HZ, rounds, basis, support, getattr(layers, "flags", None))
            if ro is not None:
                extra.append(ro)
        out[basis] = px.dem_profile(dem, trials, size=size, seeds=seeds, max_seconds=seed_seconds,
                                    extra_witnesses=extra, hook_limit=hook_limit)
        out[basis]["mechanisms"] = dem.num_errors
        out[basis]["readout_seeded"] = bool(extra)
    return out


def ler_of(files, n, rounds, rates, shots, seed):
    out = {}
    for p, s in zip(rates, shots):
        out[str(p)] = cs.measure_ler(files, n, rounds, p, seed, s)
    return out


def ler_total(ler, p):
    vals = [v for v in (ler.get(str(p)) or {}).values() if v is not None]
    return sum(vals) if len(vals) == 2 else None


def run_entry(slug, *, pool, seed, seconds, seed_seconds, size, seeds, rates, shots, out_dir, rank_only=False,
              hook_limit=px.DEFAULT_HOOK_LIMIT, log=print):
    doc, circuits_dir = cs.load_entry(slug)
    HX, HZ = cs.matrices(doc)
    n, d = doc["n"], doc["distance"]["d"]
    base = cs.baseline(doc, circuits_dir)
    rounds = max(int(base["rounds"]), d)
    wits = {s: doc["distance"][s]["witness"] for s in ("X", "Z") if s in doc["distance"]}
    rec = {"slug": slug, "n": n, "k": doc["k"], "d": d, "rounds": rounds, "committed": base,
           "pool": [], "picks": {}, "arms": {}}
    label, cands = pool_of(HX, HZ, rounds, seed, pool)
    if not cands:
        rec["skipped"] = "not a two-block code the generator can decompose"
        log(f"{slug}: {rec['skipped']}")
        return rec
    rec["family"] = label
    log(f"{slug}: [[{n},{doc['k']},{d}]] rounds {rounds}, pool of {len(cands)} ({label})")
    ris_pick = None
    best_screen = None
    for i, (notes, layers) in enumerate(cands):
        t0 = time.perf_counter()
        screen = cs.screen_candidate(HX, HZ, layers, seed)
        prof = profile_candidate(HX, HZ, rounds, layers, size, seeds, seed_seconds, wits, hook_limit)
        row = {"index": i, "schedule": notes, "screen": screen,
               "profiles": prof, "key": list(px.schedule_key(prof)) if prof else None,
               "seconds": round(time.perf_counter() - t0, 1)}
        rec["pool"].append(row)
        if screen is not None:
            found = [v for v in screen.values() if v is not None]
            passes = not found or min(found) >= d
            score = min(found) if found else d
            if ris_pick is None and passes:
                ris_pick = i
            if best_screen is None or score > best_screen[0]:
                best_screen = (score, i)
        log(f"  cand {i}: screen {screen}, proximity {row['key']}, {row['seconds']} s")
    if ris_pick is None and best_screen is not None:
        ris_pick = best_screen[1]
    scored = [r for r in rec["pool"] if r["key"] is not None]
    prox_pick = max(scored, key=lambda r: tuple(r["key"]))["index"] if scored else None
    rec["picks"] = {"ris": ris_pick, "proximity": prox_pick}
    log(f"  picks: ris {ris_pick}, proximity {prox_pick}")
    if rank_only:
        rec["verdict"] = "rank only"
        os.makedirs(os.path.join(out_dir, slug), exist_ok=True)
        _write(os.path.join(out_dir, slug, "record.json"), rec)
        return rec
    run_dir = os.path.join(out_dir, slug)
    os.makedirs(run_dir, exist_ok=True)
    # committed circuits
    committed_files = {}
    for b in ("X", "Z"):
        with open(os.path.join(circuits_dir, SIDE_FILES[b] + ".stim"), encoding="utf-8") as f:
            committed_files[SIDE_FILES[b] + ".stim"] = f.read()
    rec["arms"]["committed"] = {"d_circ": base["d_circ"],
                                "ler": ler_of(committed_files, n, base["rounds"], rates, shots, seed)}
    log(f"  committed: d_circ {base['d_circ']}, LER {rec['arms']['committed']['ler']}")
    done = {}
    for arm, idx in (("ris", ris_pick), ("proximity", prox_pick)):
        if idx is None:
            rec["arms"][arm] = {"skipped": "no candidate"}
            continue
        if idx in done:
            rec["arms"][arm] = dict(done[idx], same_as=[a for a, j in rec["picks"].items() if j == idx and a != arm][0])
            continue
        notes, layers = cands[idx]
        try:
            block, files = ca.finish(notes, layers, HX, HZ, d, rounds, wits, seed, seconds, log=lambda s: None)
        except ca.CircuitUnavailable as e:
            rec["arms"][arm] = {"index": idx, "failed": str(e)}
            log(f"  {arm} (cand {idx}): {e}")
            continue
        block["notes"] = notes + f"; {arm} pick of research/kit/proxima_bakeoff.py (seed {seed})"
        adir, verdict = cs.stage_attempt(run_dir, idx, doc, block, files,
                                         f"# {slug} candidate {idx}: {arm} pick\n\n{notes}\n")
        res = {"index": idx, "d_circ": {b: block["d_circ"][b]["value"] for b in ("X", "Z")},
               "verdict_ok": bool(verdict["ok"]), "staged": os.path.relpath(adir, _ROOT),
               "ler": ler_of(files, n, rounds, rates, shots, seed)}
        rec["arms"][arm] = res
        done[idx] = res
        log(f"  {arm} (cand {idx}): d_circ {res['d_circ']}, gate {'ok' if res['verdict_ok'] else 'FAILED'}, "
            f"LER {res['ler']}")
    low = min(rates)
    tot = {arm: ler_total(a.get("ler") or {}, low) for arm, a in rec["arms"].items() if "ler" in a}
    rec["ler_total_at_lowest_rate"] = tot
    pr, ri = tot.get("proximity"), tot.get("ris")
    if pr is None or ri is None:
        rec["verdict"] = "incomplete"
    elif ris_pick == prox_pick:
        rec["verdict"] = "same pick"
    else:
        rec["verdict"] = "proximity" if pr < ri else ("ris" if ri < pr else "tie")
    _write(os.path.join(run_dir, "record.json"), rec)
    log(f"  verdict at p={low}: {rec['verdict']} (totals {tot})")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--pool", type=int, default=12, help="schedules drawn from the two-block family")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=60.0, help="deep RIS wall cap per basis")
    ap.add_argument("--seed-seconds", type=float, default=10.0,
                    help="RIS wall cap per basis for the witness sets that seed a profile")
    ap.add_argument("--size", type=int, default=px.DEFAULT_HOOD, help="neighborhood size around the witness")
    ap.add_argument("--seeds", type=int, default=0,
                    help="RIS witness sets added to the readout seeds (0: readout seeds only, which is "
                         "cheap on large models and the same seeds for every candidate)")
    ap.add_argument("--ler-p", type=float, nargs="+", default=[0.005, 0.002])
    ap.add_argument("--ler-shots", type=int, nargs="+", default=[20000, 40000])
    ap.add_argument("--hook-limit", type=int, default=16, help="hook-like seeds per basis")
    ap.add_argument("--rank-only", action="store_true", help="rank the pool and stop (no deep search, no LER)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if len(a.ler_shots) != len(a.ler_p):
        ap.error("--ler-shots needs one value per --ler-p")
    out = a.out or os.path.join(_ROOT, "research", "candidates",
                                f"proxima-bakeoff-{datetime.datetime.now(datetime.timezone.utc):%Y%m%d}")
    os.makedirs(out, exist_ok=True)
    summary = {"date": datetime.datetime.now(datetime.timezone.utc).isoformat(), "head": cs._head(),
               "pool": a.pool, "seconds": a.seconds, "seed_seconds": a.seed_seconds, "size": a.size, "seeds": a.seeds,
               "hook_limit": a.hook_limit,
               "rates": a.ler_p, "shots": a.ler_shots, "entries": []}
    for slug in a.slugs:
        try:
            rec = run_entry(slug, pool=a.pool, seed=a.seed, seconds=a.seconds, seed_seconds=a.seed_seconds,
                            size=a.size, seeds=a.seeds, rank_only=a.rank_only, hook_limit=a.hook_limit,
                            rates=a.ler_p, shots=a.ler_shots, out_dir=out)
        except Exception as e:  # noqa: BLE001
            rec = {"slug": slug, "error": repr(e)}
            print(f"{slug}: error {e!r}", flush=True)
        summary["entries"].append(rec)
        _write(os.path.join(out, "summary.json"), summary)
    wins = sum(1 for r in summary["entries"] if r.get("verdict") == "proximity")
    losses = sum(1 for r in summary["entries"] if r.get("verdict") == "ris")
    print(f"\nproximity {wins}, ris {losses}, other {len(summary['entries']) - wins - losses}; summary at {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

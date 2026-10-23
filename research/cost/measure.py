#!/usr/bin/env python3
"""Measure what the gate, a refutation rung, exact certification, and the submit search cost by shape (issue #4026).

Confirmation is the bottleneck (fieldnotes/2026-07-01-confirmation-is-the-bottleneck.md)
and the repository has priced it by intuition. This script measures it: for a fixed
grid of board entries chosen to cover the cap corners (BASE_MAX_N 700, MAX_N 1000,
check weight 8 and 12/16/24/32, distance 40) and both code types, it records the
wall time of

* the gate, ``verify/validate_candidate.py``, end to end, split into the structural
  verifier pass, the gate's own refutation (``heuristic_distance.refute_check``, a
  10 s cap on n-scaled RIS trials), and the board dedup and novelty label, which is
  what remains;
* one refutation rung at fixed trial counts: the pure-Python RIS search at 20,000
  trials per side (the ``qldpc submit`` default) up to n = 300 and at 2,000 trials
  per side above it, where a trial costs seconds, with the per-trial rate recorded
  so the 20,000-trial figure is still comparable (marked as implied); and the C++
  accelerator at 200,000 and 2,000,000 trials (the submit default), 8 threads;
* exact certification, ``verify/certify.py``, per side, with the MILP time limit
  the entry would get and a wall cap on the whole side, recording a side that hit
  either limit as such;
* the witness search ``qldpc submit`` performs before packaging, which is the RIS
  pass on each side plus the 2,000,000-trial accelerator pass, so it is the sum of
  rungs already measured rather than a second run.

The result is ``cost_table.json`` (every number, the environment, the parameters)
and ``cost_table.md`` (the table). A time is what this machine took on that day;
CI runners are not this machine, and nothing here is a guarantee or a gate input.
Nothing under verify/ is changed or read beyond calling it.

    uv run --extra certify python research/cost/measure.py run            # the grid
    uv run --extra certify python research/cost/measure.py run --only 96-16-6 --resume
    uv run python research/cost/measure.py render                          # the table only
"""
import argparse
import datetime
import hashlib
import json
import os
import platform
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
CODES = os.path.join(ROOT, "codes")
TABLE = os.path.join(HERE, "cost_table.json")
TABLE_MD = os.path.join(HERE, "cost_table.md")

# The grid: board entries, so a clean checkout can re-measure them. Rule: for each
# (code type, check weight, blocklength band) a representative entry, the cap
# corners included; the slug is what pins it, the blob hash records which bytes.
GRID = [
    # CSS, by check weight and n band
    ("100-2-10", "w<=4, n~100"),
    ("96-16-6", "w=6, n~100"),
    ("96-2-14", "w=8, n~100"),
    ("294-10-14", "w=6, n~300"),
    ("294-12-14", "w=8, n~300"),
    ("682-20-22", "w=6, n~700"),
    ("684-12-45", "w=8, n~700"),
    ("700-2-25", "BASE_MAX_N corner, w=4"),
    ("700-140-22", "BASE_MAX_N corner, w=9, large k"),
    ("700-20-60", "BASE_MAX_N corner, w=16"),
    ("696-352-10", "w=12, k=352"),
    ("682-132-64", "w=24"),
    ("682-142-54", "w=32"),
    ("960-24-40", "EXT_MAX_D corner (d=40), w=6, n=960"),
    ("968-18-31", "w=8, n~1000"),
    ("1000-406-6", "MAX_N corner, w=8, k=406"),
    # stabilizer (non-CSS): no certifier yet, Pauli-weight RIS
    ("90-21-10", "stabilizer, n~100"),
    ("672-28-30", "stabilizer, w=24, n~700"),
    ("761-1-39", "stabilizer, n>700, w=4"),
    ("662-122-95", "stabilizer, w=32, large k"),
]
CERTIFY_STATUSES = ("exact", "refuted", "milp_tlim", "wall_cap", "not_available", "error")


def _blob(path):
    with open(path, "rb") as f:
        data = f.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _doc(slug):
    with open(os.path.join(CODES, slug + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _check_weight(doc, hd):
    if doc.get("code_type") == "stabilizer":
        import numpy as np
        A, B = hd.stabilizer_matrices(doc)
        return int(max(((np.asarray(A) != 0) | (np.asarray(B) != 0)).sum(axis=1)))
    return max(max((len(set(r)) for r in doc["checks"]["X"]), default=0),
               max((len(set(r)) for r in doc["checks"]["Z"]), default=0))


def _timed(fn, *a, **kw):
    t0 = time.perf_counter()
    out = fn(*a, **kw)
    return round(time.perf_counter() - t0, 2), out


def environment(hd):
    import numpy
    try:
        import scipy
        scipy_v = scipy.__version__
    except ImportError:
        scipy_v = None
    cpu = platform.processor() or None
    if sys.platform == "darwin":
        try:
            cpu = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"],
                                          text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        head = None
    return {"date": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
            "head": head, "platform": platform.platform(), "cpu": cpu,
            "cores": os.cpu_count(), "python": platform.python_version(),
            "numpy": numpy.__version__, "scipy": scipy_v,
            "accelerator": hd._fast is not None}


def certify_side(slug, side, tlim):
    """Worker: one side of verify/certify.py's question, as JSON on stdout."""
    import certify
    import gf2
    import qldpc_verify as V
    doc = _doc(slug)
    n = doc["n"]
    HX = V._matrix(doc["checks"]["X"], n)
    HZ = V._matrix(doc["checks"]["Z"], n)
    H, LZ = (HZ, gf2.logical_basis(HX, HZ)) if side == "X" else (HX, gf2.logical_basis(HZ, HX))
    val = doc["distance"][side]["value"]
    t0 = time.perf_counter()
    lighter = certify._exists_lighter(H, LZ, val - 1, tlim)
    status = {True: "refuted", False: "exact", None: "milp_tlim"}[lighter]
    print(json.dumps({"status": status, "secs": round(time.perf_counter() - t0, 2),
                      "generators": int(LZ.shape[0]), "value": val}))


def measure_certify(slug, doc, tlim, wall):
    """Both sides, each in its own process under the wall cap."""
    if doc.get("code_type") == "stabilizer":
        return {"status": "not_available",
                "note": "verify/certify.py has no Pauli-weight formulation yet"}
    out = {"milp_tlim_s": tlim, "wall_cap_s": wall}
    for side in ("X", "Z"):
        if side not in doc["distance"]:
            out[side] = {"status": "not_available", "note": "no claim on this side"}
            continue
        t0 = time.perf_counter()
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "certify-side",
                                slug, side, str(tlim)], capture_output=True, text=True,
                               timeout=wall, check=False)
            secs = round(time.perf_counter() - t0, 2)
            if r.returncode != 0:
                out[side] = {"status": "error", "secs": secs,
                             "detail": (r.stderr or "").strip()[-300:]}
            else:
                rec = json.loads(r.stdout.strip().splitlines()[-1])
                rec["secs"] = secs
                out[side] = rec
        except subprocess.TimeoutExpired:
            out[side] = {"status": "wall_cap", "secs": round(time.perf_counter() - t0, 2),
                         "detail": f"killed at the {wall} s wall cap"}
    return out


def measure(slug, role, *, seed, ris_trials, fast_trials, tlim, wall, log=print,
            ris_trials_large=2000, ris_large_n=300):
    import heuristic_distance as hd
    import qldpc_verify as V
    import validate_candidate as VC
    doc = _doc(slug)
    n = doc["n"]
    stab = doc.get("code_type") == "stabilizer"
    rec = {"slug": slug, "role": role, "code_type": "stabilizer" if stab else "CSS",
           "n": n, "k": doc["k"], "d": doc["distance"]["d"], "w": _check_weight(doc, hd),
           "blob": _blob(os.path.join(CODES, slug + ".json")), "gate": {}, "rungs": {}}
    g = rec["gate"]
    g["verify_structural_s"], _ = _timed(V.verify, doc, refute=False)
    t, (refuted, _, _, trials) = _timed(hd.refute_check, doc, seed=seed)
    g["refute_s"], g["refute_trials"], g["refute_cap_s"] = t, int(trials), 10.0
    g["refute_found_lighter"] = bool(refuted)
    g["gate_total_s"], _ = _timed(VC.validate_candidate, doc, seed=seed)
    g["dedup_novelty_s_derived"] = round(
        max(0.0, g["gate_total_s"] - g["verify_structural_s"] - g["refute_s"]), 2)
    log(f"  gate {g['gate_total_s']} s (structural {g['verify_structural_s']}, refute {g['refute_s']})")

    r = rec["rungs"]
    # The Python RIS rung costs seconds per trial at n ~ 700 to 1,000, so above
    # ris_large_n it runs at a smaller fixed count and the per-trial rate gives
    # the implied cost at the default count, marked as implied in the table.
    trials = ris_trials if n <= ris_large_n else ris_trials_large
    r["ris_trials"] = trials
    sides = ("P",) if stab else ("X", "Z")
    if stab:
        A, B = hd.stabilizer_matrices(doc)
        t, (dP, _) = _timed(hd.ris_min_pauli_logical, A, B, trials, seed)
        r[f"ris_{trials}_P_s"] = t
        r[f"ris_{trials}_P_found"] = dP
        HXf, HZf = hd.doubled_matrices(A, B)
    else:
        HX = V._matrix(doc["checks"]["X"], n)
        HZ = V._matrix(doc["checks"]["Z"], n)
        for side, a, b in (("X", HX, HZ), ("Z", HZ, HX)):
            t, (dw, _) = _timed(hd.ris_min_logical, a, b, trials, seed)
            r[f"ris_{trials}_{side}_s"] = t
            r[f"ris_{trials}_{side}_found"] = dw
        HXf, HZf = HX, HZ
    for s in sides:
        r[f"ris_per_trial_{s}_s"] = round(r[f"ris_{trials}_{s}_s"] / trials, 5)
        if trials != ris_trials:
            r[f"ris_{ris_trials}_{s}_implied_s"] = round(r[f"ris_per_trial_{s}_s"] * ris_trials, 1)
    log(f"  RIS {trials}: " + ", ".join(f"{k}={v}" for k, v in r.items() if k.endswith("_s") and k.startswith("ris_")))
    if hd._fast is not None:
        for ft in fast_trials:
            t, (wf, _, _) = _timed(hd._fast.distance_rand_witness, HXf, HZf, ft, seed, 8, 8)
            r[f"fast_{ft}_s"] = t
            r[f"fast_{ft}_found"] = wf
            log(f"  fast {ft}: {t} s (weight {wf})")
        r["fast_threads"] = 8
    ris_default = [r.get(f"ris_{ris_trials}_{s}_s", r.get(f"ris_{ris_trials}_{s}_implied_s")) for s in sides]
    r["submit_search_s"] = round(sum(ris_default) + r.get(f"fast_{max(fast_trials)}_s", 0), 2)
    r["submit_search_extrapolated"] = trials != ris_trials
    rec["certify"] = measure_certify(slug, doc, tlim, wall)
    log("  certify: " + ", ".join(f"{s}={rec['certify'][s]['status']} {rec['certify'][s].get('secs')} s"
                                  for s in ("X", "Z") if s in rec["certify"]))
    return rec


def _fmt_s(v):
    return "-" if v is None else (f"{v:.1f} s" if v < 100 else f"{v:,.0f} s")


def _fmt_cert(c, side):
    if side not in c:
        return "n/a" if c.get("status") == "not_available" else "-"
    s = c[side]
    st = s["status"]
    if st == "exact":
        return f"exact, {_fmt_s(s['secs'])}"
    if st == "refuted":
        return f"refuted, {_fmt_s(s['secs'])}"
    if st == "milp_tlim":
        return f"MILP limit, {_fmt_s(s['secs'])} ({s.get('generators')} generators)"
    if st == "wall_cap":
        return f"wall cap, {_fmt_s(s['secs'])}"
    return st


def render(table):
    p = table["parameters"]
    ris, fast = p["ris_trials"], p["fast_trials"]
    env = table["environment"]
    lines = [f"Measured {env['date']} on {env['cpu']} ({env['cores']} cores), Python "
             f"{env['python']}, numpy {env['numpy']}, scipy {env['scipy']}, accelerator "
             f"{'built' if env['accelerator'] else 'absent'}; board at {str(env['head'])[:9]}. "
             f"Cold board pass before the first gate call: {_fmt_s(table.get('board_pass_cold_s'))}. "
             f"Certification: MILP time limit {p['certify_tlim_s']} s per generator, wall cap "
             f"{p['certify_wall_s']} s per side. Times are this machine's, not a guarantee.",
             "",
             f"| entry | type | n | k | d | w | gate | of which refute | RIS {ris:,}/side (measured, or "
             f"implied from a smaller count) | fast {fast[0]:,} | fast {fast[-1]:,} | submit search | "
             "certify X | certify Z |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in table["entries"]:
        g, r, c = e["gate"], e["rungs"], e["certify"]
        sides = ("P",) if e["code_type"] == "stabilizer" else ("X", "Z")
        tr = r.get("ris_trials", ris)
        ris_s = " / ".join(_fmt_s(r.get(f"ris_{ris}_{s}_s")) if tr == ris else
                           f"~{_fmt_s(r.get(f'ris_{ris}_{s}_implied_s'))} (from {tr:,} trials in "
                           f"{_fmt_s(r.get(f'ris_{tr}_{s}_s'))})" for s in sides)
        lines.append(f"| {e['slug']} | {e['code_type']} | {e['n']} | {e['k']} | {e['d']} | {e['w']} | "
                     f"{_fmt_s(g['gate_total_s'])} | {_fmt_s(g['refute_s'])} | {ris_s} | "
                     f"{_fmt_s(r.get(f'fast_{fast[0]}_s'))} | {_fmt_s(r.get(f'fast_{fast[-1]}_s'))} | "
                     f"{'~' if r.get('submit_search_extrapolated') else ''}{_fmt_s(r['submit_search_s'])} | "
                     f"{_fmt_cert(c, 'X')} | {_fmt_cert(c, 'Z')} |")
    return "\n".join(lines) + "\n"


def run(a):
    import heuristic_distance as hd
    import qldpc_verify as V
    table = {"cost_version": 1, "issue": 4026, "entries": []}
    if a.resume and os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            table = json.load(f)
    done = {e["slug"] for e in table["entries"]}
    table["parameters"] = {"seed": a.seed, "ris_trials": a.ris_trials, "fast_trials": a.fast_trials,
                           "ris_trials_large": a.ris_trials_large, "ris_large_n": a.ris_large_n,
                           "certify_tlim_s": a.certify_tlim, "certify_wall_s": a.certify_wall}
    table["environment"] = environment(hd)
    if "board_pass_cold_s" not in table:
        print("board pass (dedup needs every entry's report; cold the first time) ...", flush=True)
        table["board_pass_cold_s"], _ = _timed(lambda: list(V.board_reports(CODES)))
        print(f"  {table['board_pass_cold_s']} s", flush=True)
    grid = [(s, role) for s, role in GRID if (not a.only or s in a.only)]
    for slug, role in grid:
        if slug in done:
            continue
        if not os.path.exists(os.path.join(CODES, slug + ".json")):
            print(f"{slug}: not on the board; skipped", flush=True)
            continue
        print(f"{slug} ({role})", flush=True)
        rec = measure(slug, role, seed=a.seed, ris_trials=a.ris_trials, fast_trials=a.fast_trials,
                      tlim=a.certify_tlim, wall=a.certify_wall, log=lambda m: print(m, flush=True),
                      ris_trials_large=a.ris_trials_large, ris_large_n=a.ris_large_n)
        table["entries"] = [e for e in table["entries"] if e["slug"] != slug] + [rec]
        order = {s: i for i, (s, _) in enumerate(GRID)}
        table["entries"].sort(key=lambda e: order.get(e["slug"], 999))
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(table, f, indent=1, sort_keys=True)
            f.write("\n")
    with open(a.out.replace(".json", ".md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(render(table))
    print(f"wrote {os.path.relpath(a.out, ROOT)} and the .md table: {len(table['entries'])} entries")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="measure the grid (hours for the full grid)")
    r.add_argument("--out", default=TABLE)
    r.add_argument("--only", nargs="*", default=None, help="slugs to measure (default: the grid)")
    r.add_argument("--resume", action="store_true", help="keep entries already in --out")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--ris-trials", type=int, default=20000)
    r.add_argument("--ris-trials-large", type=int, default=2000,
                   help="RIS trials per side above --ris-large-n (the default count is implied from the rate)")
    r.add_argument("--ris-large-n", type=int, default=300)
    r.add_argument("--fast-trials", type=int, nargs="+", default=[200_000, 2_000_000])
    r.add_argument("--certify-tlim", type=float, default=60.0, help="MILP time limit per generator")
    r.add_argument("--certify-wall", type=float, default=120.0, help="wall cap per side")
    d = sub.add_parser("render", help="rewrite cost_table.md from cost_table.json")
    d.add_argument("--table", default=TABLE)
    c = sub.add_parser("certify-side")
    c.add_argument("slug")
    c.add_argument("side")
    c.add_argument("tlim", type=float)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        return run(a)
    if a.cmd == "render":
        with open(a.table, encoding="utf-8") as f:
            table = json.load(f)
        with open(a.table.replace(".json", ".md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(render(table))
        return 0
    certify_side(a.slug, a.side, a.tlim)
    return 0


if __name__ == "__main__":
    sys.exit(main())

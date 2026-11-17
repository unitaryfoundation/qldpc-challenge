r"""Run one rung of the 2D-local SAT ladder and record how it ended.

Issue #2703. A rung is one (grid, G, w, t, radius, layers) instance of
``local_sat.build_local_cnf`` and ends in exactly one of three states:

    SAT      a model passed the post-check and reached --k-min; the code
             is written out for the gate (nothing here files it);
    UNSAT    the solver proved the remaining formula empty, which with the
             exact post-check is a closure of the cell at these parameters
             (with --k-min: no model at this G has that many logical
             qubits, since every model with fewer was enumerated);
    walled   a conflict or wall-clock budget ended the last solve. A wall
             is a statement about one solver build at one budget, so both
             are recorded with it, along with peak memory.

Every model has k >= n - 2G, so the rung that asks for k >= k_min is
G = floor((n - k_min) / 2) per side. Above that G a model with k >= k_min
needs dependent rows, which the encoding cannot ask for, and the run is an
enumeration of lower-k models until the budget ends; --k-min records how
many were seen and the best k among them.

The record is one JSON object per rung, appended to a JSONL log, and the
fieldnote is written from the log rather than from memory.

    python research/sat_rungs.py --side 5 --G 16 --w 6 --t 3 \\
        --solver cadical195 --conflicts 20000000 --wall-hours 3
    python research/sat_rungs.py --side 7 --G 28 --w 6 --t 2 --layers 2 \\
        --radius 3.5 --solver cadical195 --conflicts 20000000 --wall-hours 3
"""
import argparse
import json
import os
import platform
import resource
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

import local_sat  # noqa: E402
from search import compute_k  # noqa: E402

RUNG_LOG = os.path.join(_ROOT, "research", "audits", "sat-rungs.jsonl")


def _peak_rss_gb():
    """Return this process's peak resident set in GB."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is bytes on macOS and kilobytes on Linux.
    return round(rss / (1024 ** 3 if platform.system() == "Darwin"
                        else 1024 ** 2), 2)


def _solver_version(name):
    """Return the CaDiCaL version behind a python-sat solver key, if known."""
    return {"cadical": "1.5.3", "cadical153": "1.5.3", "cadical195": "1.9.5",
            "cadical300": "3.0.0"}.get(name, name)


CONF_CHUNK = 250_000   # conflicts per solve call; the wall is checked between


def run_rung(side, G, w, t, radius, *, layers=1, solver="cadical195",
             conflicts=None, wall_hours=None, k_min=0, max_models=None,
             out_dir=None, exact_on_reject=True, nonempty_rows=True,
             verbose=True):
    """Run one rung and return its record.

    ``conflicts`` caps the conflicts spent on one formula (one model's
    search) and ``wall_hours`` caps the whole run. Neither can interrupt
    CaDiCaL from outside, since python-sat's ``interrupt`` raises
    NotImplementedError for it, so each solve call gets a chunk of
    ``CONF_CHUNK`` conflicts and both caps are checked between chunks; a
    wall overrun is bounded by one chunk, not by one solve.
    """
    t0 = time.time()
    stats = {}
    interrupted = {"wall": False}
    spent = {"base": 0, "conflicts": 0}

    def budget_check(acc):
        total = acc.get("conflicts", 0)
        spent["conflicts"] = total
        if wall_hours and time.time() - t0 >= wall_hours * 3600:
            interrupted["wall"] = True
            return False
        if conflicts is not None and total - spent["base"] >= conflicts:
            return False
        return True

    chunk = CONF_CHUNK if conflicts is None else min(conflicts, CONF_CHUNK)
    gen = local_sat.enumerate_local_sat_codes(
        side, G, w, t, radius, solver=solver, layers=layers,
        conf_budget=chunk, stream=True, shared_t3=(t >= 2),
        max_codes=max_models, nonempty_rows=nonempty_rows,
        exact_on_reject=exact_on_reject, stats=stats,
        budget_check=budget_check)
    found, seen, best_k = [], 0, None
    try:
        for spec, HX, HZ in gen:
            sites = spec.get("sites")
            ax = spec.get("anchors_x")
            az = spec.get("anchors_z")
            # A new model starts a new formula's conflict count.
            spent["base"] = spent["conflicts"]
            seen += 1
            k = int(compute_k(HX, HZ))
            best_k = k if best_k is None else max(best_k, k)
            if verbose and (seen <= 5 or seen % 100 == 0 or k >= k_min):
                print(f"  model {seen} k={k} at {round(time.time() - t0)}s",
                      flush=True)
            if k >= k_min:
                found.append((spec, HX, HZ, sites, ax, az, k))
                break
            if wall_hours and time.time() - t0 >= wall_hours * 3600:
                interrupted["wall"] = True
                stats["final"] = "budget"
                break
    finally:
        pass
    secs = round(time.time() - t0, 1)

    if found:
        status = "SAT"
    elif stats.get("final") == "UNSAT":
        status = "UNSAT"
    else:
        status = "walled"
    rec = {
        "rung": f"{side}x{side}{'x2' if layers == 2 else ''} G={G} w{w} t={t}",
        "side": side, "layers": layers, "n": side * side * layers, "G": G,
        "w": w, "t": t, "radius": radius, "status": status,
        "solver": f"CaDiCaL {_solver_version(solver)} via python-sat",
        "conflict_cap": conflicts, "wall_cap_hours": wall_hours,
        "wall_hit": interrupted["wall"], "secs": secs,
        "k_min": k_min, "models_seen": seen, "best_k_seen": best_k,
        "conflicts_total": stats.get("conflicts"),
        "peak_rss_gb": _peak_rss_gb(), "rounds": stats.get("rounds"),
        "rejected": stats.get("rejected"), "final": stats.get("final"),
        "date": time.strftime("%Y-%m-%d"),
        "host": platform.node(),
    }
    if found:
        spec, HX, HZ, sites, ax, az, k = found[0]
        rec["k"] = k
        rec["max_row_weight"] = int(max(HX.sum(1).max(), HZ.sum(1).max()))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, rec["rung"].replace(" ", "_")
                                .replace("=", "") + ".json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"spec": spec, "HX": HX.tolist(),
                           "HZ": HZ.tolist(), "sites": sites,
                           "anchors_x": ax, "anchors_z": az, "k": k},
                          f)
            rec["model_path"] = os.path.relpath(path, _ROOT)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--side", type=int, required=True)
    ap.add_argument("--G", type=int, required=True)
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--t", type=int, required=True)
    ap.add_argument("--radius", type=float, default=2.0,
                    help="anchor radius (default 2.0, interaction radius "
                         "4.0; the bilayer rungs used 3.5)")
    ap.add_argument("--layers", type=int, default=1)
    ap.add_argument("--solver", default="cadical195")
    ap.add_argument("--conflicts", type=int, default=None)
    ap.add_argument("--wall-hours", type=float, default=None)
    ap.add_argument("--k-min", type=int, default=0,
                    help="enumerate until a model has at least this many "
                         "logical qubits (default 0: the first model)")
    ap.add_argument("--max-models", type=int, default=None,
                    help="stop after this many models even if none reached "
                         "--k-min")
    ap.add_argument("--out-dir", default=None,
                    help="where a found model is written (not filed)")
    ap.add_argument("--log", default=RUNG_LOG)
    ap.add_argument("--block-on-reject", action="store_true",
                    help="block the whole model on a post-check rejection "
                         "(the pre-#2703 behavior) instead of adding the "
                         "exact detection constraint")
    a = ap.parse_args(argv)

    rec = run_rung(a.side, a.G, a.w, a.t, a.radius, layers=a.layers,
                   solver=a.solver, conflicts=a.conflicts,
                   wall_hours=a.wall_hours, k_min=a.k_min,
                   max_models=a.max_models,
                   out_dir=a.out_dir, exact_on_reject=not a.block_on_reject)
    os.makedirs(os.path.dirname(a.log), exist_ok=True)
    with open(a.log, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")
    print(json.dumps(rec, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Circuit-tier search: look for a better extraction schedule for an entry that has one (issue #4032).

The circuit tier (TRACKS.md) records ``d_circ`` per basis for the committed
memory circuits under ``circuits/<slug>/``: the size of an exhibited set of
error mechanisms that no detector sees and that flips a logical observable, a
witness-backed upper bound clamped to ``<= d``. The schedule is the
submitter's degree of freedom and the one the committed circuits never
searched: #1026 backfilled the standard schedules, and the two papers the
issue cites (arXiv:2610.23832, arXiv:2610.31352) found that standard
schedules are far from what a search against a frozen evaluator reaches.

This module is that search, symmetric with the code-search loop:

* **fixed**: the entry's H_X and H_Z, its layout, the noise recipe
  (``verify/circuit_tools.py``, read-only), the round count the committed
  circuits perform, and the evaluator, ``verify/circuit_verify.py``, which
  is called and never edited;
* **searched**: the schedule. Candidates come from the families
  ``research/circuit_autogen.py`` knows (interleaved two-block slot
  assignments, layout zigzag pattern pairs, edge-coloring orders of the
  generic sequential schedule), every applicable family rather than the
  first, over as many seeds as the budget allows;
* **scored**: ``d_circ`` per basis, read off the same RIS search of the
  detector error model the generator and the gate use, at twice the gate's
  trial budget; the lower basis first, then the sum. The bound is what the
  search found, so a schedule scores higher when the search finds nothing
  lighter at that budget, and the gate's own refutation search is what a
  promoted schedule still has to survive. The clamp means a schedule can
  lower what the board shows and never raise it above ``d``;
* **staged**: every attempt, improving or not, under
  ``research/candidates/<run>/circuit-search/<slug>/attempt-NN/`` with the
  four circuit files, the circuit block, the entry with the block in place,
  the verifier's verdict, and ``notes.md`` saying what the schedule was, what
  the screen and the deep search read, and how it compares with the
  committed circuits. The run's ``ledger.jsonl`` has one line per attempt and
  ``summary.json`` the baseline, the ranking, and the survivors, so a later
  session builds on this one's lineage instead of starting fresh.

A survivor is an attempt the verifier accepted whose score beats the
committed circuits. It is staged for a human; promotion stays the
contributor-driven workflow (CONTRIBUTING.md): the entry's ``circuit`` block
and ``circuits/<slug>/`` are replaced in one PR, with
``circuit.contributed_by.by`` naming the schedule's author so
``verify/check_authorship.py`` binds the change. Nothing here changes a cell,
a frontier, or a score beyond ``d_circ`` and, when measured, LER points.

    uv run --extra research python research/kit/circuit_search.py 72-12-6 --attempts 12 --seconds 60
    uv run --extra research python research/kit/circuit_search.py 12-2-3 --attempts 3 --seconds 5 --ler
"""
import argparse
import copy
import datetime
import json
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "verify"), os.path.join(_ROOT, "research"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import circuit_autogen as ca  # noqa: E402
import circuit_tools as ct  # noqa: E402
import coordination  # noqa: E402
import numpy as np  # noqa: E402
import stim  # noqa: E402
from circuit_verify import SIDE_FILES, verify_circuit  # noqa: E402

CODES = os.path.join(_ROOT, "codes")
CIRCUITS = os.path.join(_ROOT, "circuits")
FAMILIES = ("two-block", "layout", "generic")


def load_entry(slug):
    """(doc, circuits directory) for a board entry that carries a circuit tier."""
    path = os.path.join(CODES, slug + ".json")
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if not doc.get("circuit"):
        raise SystemExit(f"{slug}: no circuit tier to improve on; qldpc submit --circuits "
                         "or research/circuit_autogen.py adds a first one")
    if doc.get("code_type") == "stabilizer":
        raise SystemExit(f"{slug}: the schedule search covers CSS memory experiments only")
    return doc, os.path.join(CIRCUITS, slug)


def matrices(doc):
    n = doc["n"]
    return ca._matrix(doc["checks"]["X"], n), ca._matrix(doc["checks"]["Z"], n)


def coords_of(doc):
    """Layout coordinates when the entry carries them, else None."""
    loc = doc.get("locality") or {}
    pts = loc.get("coords") or loc.get("coordinates")
    if isinstance(pts, list) and pts and isinstance(pts[0], (list, tuple)):
        return [tuple(map(float, p[:2])) for p in pts]
    return None


def score_of(dc):
    """(lower basis, sum): higher is better; the comparison the ranking uses."""
    vals = [dc[b]["value"] for b in ("X", "Z")]
    return (min(vals), sum(vals))


def baseline(doc, circuits_dir):
    """Read what the committed circuits claim and how big their models are."""
    cb = doc["circuit"]
    out = {"d_circ": {b: cb["d_circ"][b]["value"] for b in ("X", "Z")},
           "rounds": cb["rounds"], "notes": cb.get("notes", ""), "mechanisms": {}}
    for b in ("X", "Z"):
        p = os.path.join(circuits_dir, SIDE_FILES[b] + ".dem")
        try:
            with open(p, encoding="utf-8") as f:
                out["mechanisms"][b] = stim.DetectorErrorModel(f.read()).num_errors
        except (OSError, ValueError):
            out["mechanisms"][b] = None
    out["score"] = list(score_of(cb["d_circ"]))
    return out


def families(HX, HZ, coords, seed, only=FAMILIES):
    """Every applicable schedule family as (name, label, candidate iterator)."""
    rng = np.random.default_rng(seed)
    out = []
    if "two-block" in only:
        got = ca.two_block_candidates(HX, HZ, rng)
        if got is not None:
            out.append(("two-block", got[0], got[1]))
    if "layout" in only:
        got = ca.layout_candidates(HX, HZ, coords)
        if got is not None:
            out.append(("layout", got[0], got[1]))
    if "generic" in only:
        label, it = ca.generic_candidates(HX, HZ, rng)
        out.append(("generic", label, it))
    return out


def screen_candidate(HX, HZ, layers, seed, rounds=ca.SCREEN_ROUNDS, trials=ca.SCREEN_TRIALS,
                     seconds=ca.SCREEN_SECONDS):
    """Quick RIS bounds at few rounds, per basis; None when a detector is not deterministic.

    Fewer rounds can only overestimate d_circ, so a bound found here is a
    bound on the full circuit too: a candidate the screen already reads below
    the committed d_circ cannot beat it and is not evaluated further.
    """
    bounds = {}
    for basis in ("Z", "X"):
        _, dem = ca._dem_of(HX, HZ, rounds, basis, layers)
        if dem is None:
            return None
        H, L = ct.dem_matrices(dem)
        w, _ = ct.ris_dem(H, L, trials=trials, seed=seed, max_seconds=seconds)
        bounds[basis] = int(w) if w is not None else None
    return bounds


def _head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def stage_attempt(run_dir, k, doc, block, files, notes):
    """Write one attempt and gate it with the unchanged verifier."""
    adir = os.path.join(run_dir, f"attempt-{k:02d}")
    os.makedirs(adir, exist_ok=True)
    for name, text in files.items():
        _write(os.path.join(adir, name), text)
    cand = copy.deepcopy(doc)
    cand["circuit"] = block
    _write(os.path.join(adir, "candidate.json"), json.dumps(cand, indent=1, sort_keys=True) + "\n")
    _write(os.path.join(adir, "block.json"), json.dumps(block, indent=1, sort_keys=True) + "\n")
    verdict = verify_circuit(cand, adir)
    _write(os.path.join(adir, "verdict.json"), json.dumps(verdict, indent=1, sort_keys=True) + "\n")
    _write(os.path.join(adir, "notes.md"), notes)
    return adir, verdict


def measure_ler(files, n, rounds, p, seed, shots):
    """Measure the per-round logical error rate of a staged schedule at one rate, per basis."""
    import ler_measure as lm
    out = {}
    for basis in ("X", "Z"):
        circuit = stim.Circuit(files[SIDE_FILES[basis] + ".stim"])
        pt = lm.measure_point(circuit, n, rounds, p, seed, shots=shots, log=lambda s: None)
        out[basis] = pt["ler_per_round"] if pt else None
    return out


def search(slug, *, attempts=8, seed=0, seconds=60.0, screen=True, rounds=None, only=FAMILIES,
           out=None, ler=False, ler_p=0.01, ler_shots=20000, log=print):
    """Run the search for one entry; returns the summary (also written to the run directory)."""
    doc, circuits_dir = load_entry(slug)
    HX, HZ = matrices(doc)
    n, d = doc["n"], doc["distance"]["d"]
    base = baseline(doc, circuits_dir)
    rounds = max(int(rounds or base["rounds"]), d)
    wits = {s: doc["distance"][s]["witness"] for s in ("X", "Z") if s in doc["distance"]}
    run_dir = out or os.path.join(coordination.staging_dir(), "circuit-search",
                                  f"{slug}-{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}")
    os.makedirs(run_dir, exist_ok=True)
    ledger = os.path.join(run_dir, "ledger.jsonl")
    log(f"{slug}: committed d_circ X {base['d_circ']['X']}, Z {base['d_circ']['Z']} at rounds "
        f"{base['rounds']}; searching {attempts} schedules at rounds {rounds}, {seconds:g} s per basis")
    fams = families(HX, HZ, coords_of(doc), seed, only)
    log("  families: " + ", ".join(f"{name} ({label})" for name, label, _ in fams))
    if ler:
        committed = {}
        for b in ("X", "Z"):
            with open(os.path.join(circuits_dir, SIDE_FILES[b] + ".stim"), encoding="utf-8") as f:
                committed[SIDE_FILES[b] + ".stim"] = f.read()
        base["ler"] = measure_ler(committed, n, base["rounds"], ler_p, seed, ler_shots)
        log(f"  committed LER per round at p={ler_p}: {base['ler']}")
    rows = []
    k = 0
    per_family = max(1, -(-attempts // len(fams)))
    for name, label, cands in fams:
        taken = 0
        for notes_text, layers in cands:
            if taken >= per_family or k >= attempts:
                break
            taken += 1
            k += 1
            t0 = time.perf_counter()
            row = {"attempt": k, "family": name, "schedule": notes_text, "seed": seed,
                   "screen": None, "d_circ": None, "score": None, "verdict_ok": None,
                   "improving": False, "staged": None, "reason": None}
            if screen:
                bounds = screen_candidate(HX, HZ, layers, seed)
                row["screen"] = bounds
                if bounds is None:
                    row["reason"] = "detectors not deterministic at the screen"
                    rows.append(row)
                    _append(ledger, row)
                    log(f"  attempt {k} ({name}): not deterministic, skipped")
                    continue
                found = [v for v in bounds.values() if v is not None]
                if found and min(found) < base["score"][0]:
                    row["reason"] = (f"screen at {ca.SCREEN_ROUNDS} rounds found a weight-{min(found)} "
                                     f"fault set, below the committed {base['score'][0]}")
                    rows.append(row)
                    _append(ledger, row)
                    log(f"  attempt {k} ({name}): screen {bounds}, cannot beat the baseline")
                    continue
            try:
                block, files = ca.finish(notes_text, layers, HX, HZ, d, rounds, wits, seed, seconds,
                                         log=lambda s: None)
            except ca.CircuitUnavailable as e:
                row["reason"] = f"deep search: {e}"
                rows.append(row)
                _append(ledger, row)
                log(f"  attempt {k} ({name}): {e}")
                continue
            block["notes"] = (notes_text + f"; found by research/kit/circuit_search.py (seed {seed}, "
                              f"{seconds:g} s per basis) over the committed schedule of {slug}")
            dc = {b: block["d_circ"][b]["value"] for b in ("X", "Z")}
            row["d_circ"], row["score"] = dc, list(score_of(block["d_circ"]))
            row["mechanisms"] = {b: stim.DetectorErrorModel(files[SIDE_FILES[b] + ".dem"]).num_errors
                                 for b in ("X", "Z")}
            row["improving"] = tuple(row["score"]) > tuple(base["score"])
            if ler:
                row["ler"] = measure_ler(files, n, rounds, ler_p, seed, ler_shots)
            notes_md = (f"# {slug} attempt {k}: {name}\n\n{notes_text}\n\n"
                        f"Screen at {ca.SCREEN_ROUNDS} rounds: {row['screen']}. Deep RIS at rounds {rounds}, "
                        f"{seconds:g} s per basis: d_circ X {dc['X']}, Z {dc['Z']} "
                        f"(committed X {base['d_circ']['X']}, Z {base['d_circ']['Z']}); mechanisms "
                        f"{row['mechanisms']}; {'improving' if row['improving'] else 'not improving'}.\n"
                        + (f"LER per round at p={ler_p}: {row.get('ler')} (committed {base.get('ler')}).\n"
                           if ler else "")
                        + "\nEvery value is a witness-backed upper bound clamped to <= d; the gate's own "
                        "refutation search decides what a promoted schedule keeps.\n")
            adir, verdict = stage_attempt(run_dir, k, doc, block, files, notes_md)
            row["verdict_ok"], row["staged"] = bool(verdict["ok"]), os.path.relpath(adir, _ROOT)
            row["seconds"] = round(time.perf_counter() - t0, 1)
            rows.append(row)
            _append(ledger, row)
            log(f"  attempt {k} ({name}): d_circ X {dc['X']}, Z {dc['Z']}; gate "
                f"{'ok' if verdict['ok'] else 'FAILED'}; {'improving' if row['improving'] else 'not improving'}"
                f" ({row['seconds']} s)")
    ranked = sorted((r for r in rows if r["score"]), key=lambda r: tuple(r["score"]), reverse=True)
    survivors = [r for r in ranked if r["improving"] and r["verdict_ok"]]
    summary = {"slug": slug, "head": _head(), "date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "rounds": rounds, "seconds_per_basis": seconds, "attempts": rows, "baseline": base,
               "ranking": [r["attempt"] for r in ranked], "survivors": [r["attempt"] for r in survivors],
               "authority": ("staged for human review; a survivor is promoted by replacing the entry's "
                             "circuit block and circuits/<slug>/ in a PR with circuit.contributed_by.by "
                             "naming the schedule's author; d_circ stays a witness-backed upper bound "
                             "and the gate's refutation search is the evaluator")}
    _write(os.path.join(run_dir, "summary.json"), json.dumps(summary, indent=1, sort_keys=True) + "\n")
    log(f"  {len(rows)} attempts, {len(ranked)} evaluated, {len(survivors)} survivor(s); run at "
        f"{os.path.relpath(run_dir, _ROOT)}")
    if survivors:
        best = survivors[0]
        log(f"  best: attempt {best['attempt']} ({best['family']}) d_circ X {best['d_circ']['X']}, "
            f"Z {best['d_circ']['Z']} vs committed X {base['d_circ']['X']}, Z {base['d_circ']['Z']}")
    return summary


def _append(path, row):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", help="a board entry with a circuit tier")
    ap.add_argument("--attempts", type=int, default=8, help="schedules to try across the families")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seconds", type=float, default=60.0, help="deep RIS wall cap per basis")
    ap.add_argument("--rounds", type=int, default=None, help="extraction rounds (default: committed)")
    ap.add_argument("--no-screen", action="store_true", help="skip the two-round screen")
    ap.add_argument("--families", nargs="+", choices=FAMILIES, default=list(FAMILIES))
    ap.add_argument("--out", default=None, help="run directory (default: under coordination.staging_dir())")
    ap.add_argument("--ler", action="store_true",
                    help="also measure LER per round for the baseline and each evaluated schedule")
    ap.add_argument("--ler-p", type=float, default=0.01)
    ap.add_argument("--ler-shots", type=int, default=20000)
    a = ap.parse_args(argv)
    search(a.slug, attempts=a.attempts, seed=a.seed, seconds=a.seconds, screen=not a.no_screen,
           rounds=a.rounds, only=tuple(a.families), out=a.out, ler=a.ler, ler_p=a.ler_p,
           ler_shots=a.ler_shots)
    return 0


if __name__ == "__main__":
    sys.exit(main())

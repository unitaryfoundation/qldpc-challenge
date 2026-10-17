"""Weekly whole-board distance refutation (CI cron).

Re-runs the bounded RIS refutation over EVERY codes/ entry, using a
fresh RANDOM seed each run. The per-PR gate (gate_changed.py) uses a fixed seed
so it is reproducible and non-flaky; this job does the opposite on purpose --
because the seed varies week to week, each run tries different random information
sets, so over time the board accumulates search coverage and an over-claim that
any single fixed-seed run missed can finally surface.

This is the safety net for distance claims that never paid the per-PR gate
(seeded baselines, direct commits, pre-gate codes) and for the back-catalogue as
the refuter improves.

FAILS CLOSED: a code whose refuter ERRORS is reported as a failure (manual review
needed), never silently skipped -- a broken check must not read as "all clear".
A run that does not reach every entry it was given is a failure too (issue
#2896): the summary line and the JSON report say which entries went unchecked,
so partial coverage is loud instead of ending in a runner timeout annotation.

The sweep covers the board's cell records by default (``--scope records``):
the entries undominated on (n, k, d, w) within their track cell, the same set
``gate_changed.board_record_slugs`` gives the deep battery at PR time, 1,195
of 1,956 entries on 2026-10-12. An over-claim on a dominated entry moves no
record, so the weekly budget goes where a wrong distance changes the board;
``--scope all`` sweeps every entry.

The entries are walked largest n first, so when a budget binds the ones it
drops are the small ones that carry exact certificates. ``--shard I/K`` takes
every K-th entry of that order starting at I, which puts an equal share of
the large entries in each shard; the workflow runs K shards in parallel and a
summary job over their reports.

With ``--recapture PATH`` every checked entry also appends one JSON line to
PATH as it completes (``recapture.py``, issue #2897): the run and file seed,
trials, wall time, battery, and every logical the search found at weight <=
the claimed distance, as an operator id and a class id with its weight. That
is the search coverage the docstring above promises, written down, and a
cancelled run keeps the lines it wrote. Nothing reads it back here; the
estimator over the accumulated records is ``research/audits/recapture.py``.

Exit 0 only if nothing was refuted, nothing errored, and every entry was reached.

Usage:
  python verify/refute_board.py [--seed N] [--scope records|all] [--shard I/K] [--max-minutes M]
                                [--report PATH] [--recapture PATH]
  python verify/refute_board.py --summarize REPORT... [--expect K]
"""
import argparse
import glob
import hashlib
import json
import os
import secrets
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heuristic_distance as H
import recapture as RC
from qldpc_verify import file_size_error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Stopped(Exception):
    """Raised from the SIGTERM/SIGINT handler so a cancelled run still writes its report."""


def entry_n(path):
    """Block length read off the slug ``<n>-<k>-<d>...json``; 0 when the name does not parse."""
    try:
        return int(os.path.basename(path).split("-")[0])
    except ValueError:
        return 0


def board_paths(root=ROOT):
    """Every entry under ``codes/``, largest n first, ties by name."""
    paths = sorted(glob.glob(os.path.join(root, "codes", "*.json")))
    return sorted(paths, key=lambda p: (-entry_n(p), p))


def shard_paths(paths, shard):
    """Entries ``I::K`` of the ordered list for ``shard="I/K"``; the K shards partition the list."""
    if shard is None:
        return list(paths)
    try:
        i, k = (int(x) for x in shard.split("/"))
    except ValueError:
        raise ValueError(f"bad shard {shard!r}: want I/K") from None
    if k < 1 or not 0 <= i < k:
        raise ValueError(f"bad shard {shard!r}: want 0 <= I < K")
    return list(paths)[i::k]


def scope_paths(paths, scope, root=ROOT, records=None):
    """``paths`` kept to the board's cell records for ``scope="records"``, all of them for ``"all"``.

    ``records`` is the function that names the record slugs; the default is
    ``gate_changed.board_record_slugs``, the implementation the PR gate uses.
    """
    if scope == "all":
        return list(paths)
    if scope != "records":
        raise ValueError(f"bad scope {scope!r}: want records or all")
    if records is None:
        import gate_changed as G
        records = G.board_record_slugs
    keep = set(records(root))
    return [p for p in paths if os.path.splitext(os.path.basename(p))[0] in keep]


def file_seed(seed, rel):
    """Per-file seed from the run seed and a STABLE hash of the path (Python's hash() is salted per process).

    Depends on nothing else, so one run seed reproduces an entry's search whatever
    the shard or order it was reached in.
    """
    rel_hash = int.from_bytes(hashlib.sha256(rel.encode()).digest()[:4], "big")
    return (seed + rel_hash) % (2**31)


def refute_paths(paths, seed, max_seconds=None, root=ROOT, refute=H.refute_check, clock=time.time, out=print,
                 recapture=None):
    """Run the refuter over ``paths`` and return the report.

    No new entry is opened once ``max_seconds`` of wall clock have passed; the
    rest are listed under ``unreached``. A SIGTERM or SIGINT raised as ``_Stopped``
    mid-entry also ends the loop with that entry and its successors unreached.

    With ``recapture`` (a path), each checked entry's search runs with a
    ``recapture.Capture`` at the claimed distance and its record is appended
    to that file before the next entry is opened; ``rep["recorded"]`` counts
    the lines written. The refuter is then called with ``capture=``, so a
    stand-in refuter must accept it.
    """
    t0 = clock()
    rep = {"seed": seed, "total": len(paths), "checked": 0, "skipped": [], "refuted": [], "errored": [],
           "unreached": [], "stopped_by": None, "complete": False, "seconds": 0.0,
           "recapture": recapture, "recorded": 0}
    idx = 0
    try:
        for idx, p in enumerate(paths):
            rel = os.path.relpath(p, root)
            if max_seconds is not None and clock() - t0 >= max_seconds:
                rep["stopped_by"] = "budget"
                break
            ferr = file_size_error(p)
            if ferr:
                rep["errored"].append([rel, f"file_size_within_limit: {ferr}"])
                out(f"ERROR    {rel}: file_size_within_limit: {ferr} -- fails closed, manual review")
                continue
            doc = json.load(open(p))
            if "distance" not in doc or "d" not in doc.get("distance", {}):
                rep["skipped"].append(rel)
                continue
            fs = file_seed(seed, rel)
            cap = RC.Capture(threshold=int(doc["distance"]["d"])) if recapture else None
            t_entry = time.monotonic()
            try:
                if cap is None:
                    is_refuted, d_found, wit, trials = refute(doc, seed=fs)
                else:
                    is_refuted, d_found, wit, trials = refute(doc, seed=fs, capture=cap)
            except _Stopped:
                raise
            except Exception as e:                 # FAIL CLOSED
                rep["errored"].append([rel, f"{type(e).__name__}: {e}"])
                out(f"ERROR    {rel}: refuter failed ({type(e).__name__}: {e}) -- fails closed, manual review")
                continue
            rep["checked"] += 1
            if cap is not None:
                slug = os.path.splitext(os.path.basename(p))[0]
                RC.append_record(recapture, RC.entry_record(
                    doc, slug, run_seed=seed, file_seed=fs, capture=cap,
                    seconds=time.monotonic() - t_entry, refuted=is_refuted, d_found=d_found,
                    trials=trials, battery=RC.battery_of(cap)))
                rep["recorded"] += 1
            if is_refuted:
                rep["refuted"].append([rel, d_found, doc["distance"]["d"], wit])
                out(f"REFUTED  {rel}: found weight-{d_found} logical < claimed {doc['distance']['d']}\n"
                    f"         witness = {wit}")
            else:
                out(f"ok       {rel}: no logical lighter than {doc['distance']['d']} ({trials} RIS trials)")
        else:
            idx = len(paths)
    except _Stopped as e:
        rep["stopped_by"] = str(e)
    rep["unreached"] = [os.path.relpath(p, root) for p in paths[idx:]]
    rep["complete"] = not rep["unreached"]
    rep["seconds"] = round(clock() - t0, 1)
    return rep


def summary_line(rep):
    """One line of counts, printed whether or not the run completed."""
    tag = f" (shard {rep['shard']})" if rep.get("shard") else ""
    return (f"{rep['checked']}/{rep['total']} codes checked{tag}; {len(rep['refuted'])} refuted, "
            f"{len(rep['errored'])} errored, {len(rep['unreached'])} unreached.")


def verdict(rep):
    """Exit code and closing line for one report."""
    if rep["refuted"] or rep["errored"]:
        return 1, "FAIL: distance claims need review (see REFUTED/ERROR above)."
    if rep["unreached"]:
        return 1, (f"FAIL: incomplete coverage (stopped by {rep['stopped_by']}): {len(rep['unreached'])} entries "
                   f"not reached; raise the shard count or the budget.")
    return 0, "PASS: no over-claim found this run."


def summarize(report_globs, expect=None, out=print):
    """Combine shard reports into one table; exit 0 only if every expected shard completed clean."""
    files = sorted({f for g in report_globs for f in glob.glob(g)})
    reps = [json.load(open(f)) for f in files]
    lines = []
    if reps:
        lines.append("scope: " + ", ".join(sorted({str(r.get("scope", "all")) for r in reps})) + "\n")
    lines += ["| shard | seed | checked | refuted | errored | unreached | minutes | status |",
              "|---|---|---|---|---|---|---|---|"]
    tot = {"total": 0, "checked": 0, "refuted": 0, "errored": 0, "unreached": 0}
    for rep in sorted(reps, key=lambda r: str(r.get("shard"))):
        status = "complete" if rep["complete"] else f"stopped by {rep['stopped_by']}"
        if rep["refuted"] or rep["errored"]:
            status += ", needs review"
        lines.append(f"| {rep.get('shard') or 'all'} | {rep['seed']} | {rep['checked']}/{rep['total']} | "
                     f"{len(rep['refuted'])} | {len(rep['errored'])} | {len(rep['unreached'])} | "
                     f"{rep['seconds'] / 60:.0f} | {status} |")
        tot["total"] += rep["total"]
        tot["checked"] += rep["checked"]
        for key in ("refuted", "errored", "unreached"):
            tot[key] += len(rep[key])
    lines.append(f"| all | | {tot['checked']}/{tot['total']} | {tot['refuted']} | {tot['errored']} | "
                 f"{tot['unreached']} | | {len(reps)} report(s) |")
    for rep in reps:
        for rel, d_found, d_claim, _wit in rep["refuted"]:
            lines.append(f"- REFUTED {rel}: weight-{d_found} logical < claimed {d_claim} (shard {rep.get('shard')})")
        for rel, why in rep["errored"]:
            lines.append(f"- ERROR {rel}: {why}")
    problems = []
    if expect is not None and len(reps) != expect:
        problems.append(f"{expect} shard reports expected, {len(reps)} found (a shard died before writing one)")
    if tot["refuted"] or tot["errored"]:
        problems.append("distance claims need review")
    if tot["unreached"]:
        problems.append(f"{tot['unreached']} entries unreached")
    lines.append("")
    lines.append("FAIL: " + "; ".join(problems) if problems else "PASS: every shard completed with no over-claim.")
    text = "\n".join(lines)
    out(text)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write("## refute-weekly coverage\n\n" + text + "\n")
    return 1 if problems else 0


def _install_stop_handlers():
    def _raise(signum, _frame):
        raise _Stopped(signal.Signals(signum).name)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _raise)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, help="run seed; only to reproduce a run (random otherwise)")
    ap.add_argument("--scope", choices=("records", "all"), default="records",
                    help="records: the board's cell records (default); all: every entry")
    ap.add_argument("--shard", help="I/K: take every K-th entry of the board (largest n first) starting at I")
    ap.add_argument("--max-minutes", type=float, help="open no new entry after this much wall clock; "
                    "the rest are reported unreached and the run fails")
    ap.add_argument("--report", help="write the JSON report here")
    ap.add_argument("--recapture", metavar="PATH",
                    help="append one JSON line per checked entry here as the run goes: seeds, trials, "
                         "and every logical found at weight <= the claimed distance (issue #2897)")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--deep", action="store_true",
                    help="completion pass: longer per-entry budgets (50k trials, 300s, 50k fold trials) with nauty/SAT fold when available")
    ap.add_argument("--summarize", nargs="+", metavar="REPORT", help="combine shard reports instead of searching")
    ap.add_argument("--expect", type=int, help="with --summarize: the number of shard reports there must be")
    args = ap.parse_args(argv)
    if args.summarize:
        return summarize(args.summarize, expect=args.expect)

    seed = args.seed if args.seed is not None else secrets.randbelow(2**31)   # fresh each run
    shard_flag = f" --shard {args.shard}" if args.shard else ""
    print(f"weekly board refutation -- random seed = {seed}")
    print(f"(reproduce this run with: python verify/refute_board.py --seed {seed} --scope {args.scope}{shard_flag})\n")
    board = board_paths(args.root)
    scoped = scope_paths(board, args.scope, args.root)
    paths = shard_paths(scoped, args.shard)
    print(f"scope {args.scope}: {len(scoped)} of {len(board)} entries"
          + (f"; shard {args.shard}: {len(paths)} entries" if args.shard else "") + ", largest n first\n")
    if args.deep:
        def refute(doc, seed=0, capture=None):
            # Deep completion pass: bounded + SAT fold first (sound refutation),
            # then a long RIS pass.  The fold runs at the deep budget with nauty
            # and the SAT fold enabled; RIS covers what the fold cannot see.
            sref, sd, swit, _sp = H.orbit_fold_refute(
                doc, seed=seed + 97, trials=50000, max_seconds=300.0)
            if sref:
                return True, sd, swit, 50000
            return H.refute_check(doc, seed=seed, trials=50000,
                                 max_seconds=300.0, fold_trials=0,
                                 capture=capture)
    else:
        refute = H.refute_check
    _install_stop_handlers()
    rep = refute_paths(paths, seed, max_seconds=None if args.max_minutes is None else 60 * args.max_minutes,
                       root=args.root, refute=refute, recapture=args.recapture)
    rep["shard"] = args.shard
    rep["scope"] = args.scope
    if args.report:
        with open(args.report, "w") as f:
            json.dump(rep, f, indent=1)
    code, line = verdict(rep)
    print(f"\n{summary_line(rep)}")
    if args.recapture:
        print(f"recapture: {rep['recorded']} entry record(s) appended to {args.recapture}")
    if rep["unreached"]:
        print("unreached: " + ", ".join(rep["unreached"][:20]) + (" ..." if len(rep["unreached"]) > 20 else ""))
    print(line)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

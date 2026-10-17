"""Recapture census over the weekly refutation sweep's records (issue #2897, phase 2).

``verify/refute_board.py --recapture`` appends one record per entry per run:
which logicals the search found at weight <= the claimed distance, each as an
operator id and a class id with its weight. Over several runs (fresh seed each
week) the same logical is found again or not, and that recapture pattern is
what this tool reads. Runs are the sampling units, stratified by battery (a
standard-budget run and a deep run are not the same sample), per entry, per
side, per weight class that has captures.

Two forms of input. The raw records are one JSON line per entry per run and
weigh about 13 MB per sweep of the board's records (measured on a 40-entry
sample, 2026-10-17), so they are kept as workflow artifacts and not committed.
What the repository keeps is the incidence table, ``incidence.json`` in this
directory: per entry, side, battery, and weight, how many runs each logical
was found in, plus the runs, trials, and seeds behind it. ``fold`` adds a
sweep's records to the table (the same run folded twice counts once), and the
census reads the table; ``census(records)`` on raw records is the same
computation through a throwaway table.

For each weight class with captures the census reports ``S_obs`` (distinct
logicals seen), ``f1`` (seen in exactly one run), ``f2`` (seen in exactly
two), and a bias-corrected Chao estimate of how many there are with a 95%
interval. The estimator is the incidence form (Chao2, since the unit is
"found in a run", and a logical found five times inside one run counts once
there); the issue calls it Chao1, which it equals as the number of runs
grows. Where a weight class has no captures the report gives the cumulative
budget only: runs, trials, seeds, and "nothing at weight <= d". An abundance
estimate over zero captures is circular, and the honest statement stays the
one the board already makes.

Calibration (``test_recapture_census.py``, 2026-10-17). On the 5 x 5 toric
code, whose ten weight-5 X operators and two classes are enumerated, twenty
censuses of the real RIS search cover the truth 20 of 20 times once each
observed operator has been recaptured about five times on average (50 runs
at one trial, 30 at two, 20 at three). Below that the interval fails in
both directions: a complete census with singletons is read as incomplete
(interval above the truth), and a census missing one operator whose bias
correction vanishes is read as complete (a width-zero interval below the
truth). ``MIN_MEAN_INCIDENCE`` is the threshold that separated the two
regimes there; a class under it is reported with its numbers but marked
sparse, and a width-zero interval is a statement about the sample, not a
proof that the census is complete.

What it answers. After a refutation at weight w: is w the floor or the tip?
``f1`` and ``f2`` at w say how much more sits there, so the re-claim has a
number behind "searched deep enough" instead of one fresh-seed pass. Without
a refutation: how complete is the census of the minimum-weight class, that
is, how much of L is known.

What it is not. Never a gate input: ``verify/`` does not read the records,
the table, or this report, no entry carries any of them, and no pass/fail
decision consults them. Nothing here is shown on the board; whether it ever
is (a Layer-3 diagnostic, the pair-audit report, or only this directory) is
a decision for after the calibration above has held up on more than one
small code.

Usage:
  uv run python research/audits/recapture.py report [--table T] [--slug S ...] [--unit op|cls] [--json OUT]
  uv run python research/audits/recapture.py report RECORDS ... [--unit op|cls] [--json OUT]
  uv run python research/audits/recapture.py fold --table T RECORDS ...

RECORDS are ``.jsonl`` or ``.jsonl.gz`` files; T defaults to
``research/audits/recapture/incidence.json``.
"""
import argparse
import datetime
import gzip
import json
import math
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_TABLE = os.path.join(ROOT, "research", "audits", "recapture", "incidence.json")
TABLE_VERSION = 1
UNITS = ("op", "cls")
Z95 = 1.959964
# Mean number of runs each observed logical was found in, below which the
# interval is reported as sparse: set by the toric-code calibration in
# test_recapture_census.py, where coverage was nominal above it and failed in
# both directions below it.
MIN_MEAN_INCIDENCE = 5.0
# Distinct ids the table keeps per weight class and unit. A class whose runs
# keep finding new operators past this is censored: its count is a floor and
# no estimate is made, and the table stays bounded whatever |L_w| is.
MAX_IDS = 5000


# -- records -------------------------------------------------------------------

def read_records(paths):
    """Yield the records in ``paths`` (``.jsonl`` or ``.jsonl.gz``), ``None`` per unreadable line.

    A run killed mid-write can leave one torn line, and it must not take the
    file with it; :func:`load_records` counts the ``None`` entries.
    """
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    yield None


def load_records(paths):
    """Return ``(records, skipped)``: the parsed records and how many lines did not parse."""
    records, skipped = [], 0
    for rec in read_records(paths):
        if rec is None:
            skipped += 1
        elif isinstance(rec, dict) and rec.get("slug") and isinstance(rec.get("sides"), dict):
            records.append(rec)
        else:
            skipped += 1
    return records, skipped


# -- the incidence table -----------------------------------------------------------

def new_table():
    return {"table_version": TABLE_VERSION, "updated": None, "folded_records": 0, "entries": {}}


def load_table(path):
    """Return the table at ``path``, or a new one when there is none yet."""
    try:
        with open(path, encoding="utf-8") as f:
            table = json.load(f)
    except FileNotFoundError:
        return new_table()
    if table.get("table_version") != TABLE_VERSION:
        raise ValueError(f"{path}: table_version {table.get('table_version')!r}, want {TABLE_VERSION}")
    return table


def save_table(table, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(table, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
    return path


def _run_key(rec):
    return f"{int(rec.get('run_seed', 0))}:{int(rec.get('file_seed', 0))}"


def _stratum(table, slug, side, key, rec):
    entries = table["entries"]
    st = entries.setdefault(slug, {}).setdefault(side, {}).setdefault(key, {
        "runs": [], "trials": 0, "claimed_d": rec.get("claimed_d"), "refuted_runs": 0,
        "classes": {}})
    return st


def fold(table, records):
    """Add ``records`` to ``table`` in place; return how many were new.

    A run is one (run seed, file seed) pair per entry, side, and battery, and
    is folded once however many times its record arrives. Within a run a
    logical counts once per weight class; across runs its count is the
    number of runs it was found in, the incidence the estimator reads. A
    class whose distinct ids pass ``MAX_IDS``, or whose run hit the sweep's
    per-side cap, is marked censored.
    """
    added = 0
    for rec in records:
        key = ((rec.get("battery") or {}).get("key")) or "unknown"
        run = _run_key(rec)
        new_run = False
        for side, block in rec["sides"].items():
            st = _stratum(table, rec["slug"], side, key, rec)
            if run in st["runs"]:
                continue
            new_run = True
            st["runs"].append(run)
            st["trials"] += int(rec.get("trials") or 0)
            st["refuted_runs"] += 1 if rec.get("refuted") else 0
            weights = [int(w) for w in block.get("w", [])]
            per_w = defaultdict(lambda: {"op": set(), "cls": set()})
            for i, w in enumerate(weights):
                for unit in UNITS:
                    ids = block.get(unit) or []
                    if i < len(ids) and ids[i] is not None:
                        per_w[w][unit].add(ids[i])
            for w, found in per_w.items():
                cls = st["classes"].setdefault(str(w), {
                    "runs_with": 0, "censored": False, "op": {}, "cls": {}})
                cls["runs_with"] += 1
                if block.get("overflow"):
                    cls["censored"] = True
                for unit in UNITS:
                    counts = cls[unit]
                    for i in found[unit]:
                        if i in counts:
                            counts[i] += 1
                        elif len(counts) < MAX_IDS:
                            counts[i] = 1
                        else:
                            cls["censored"] = True
        if new_run:
            added += 1
    table["folded_records"] += added
    table["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return added


# -- the estimate ---------------------------------------------------------------------

def chao(s_obs, f1, f2, runs):
    """Bias-corrected incidence Chao estimate with its 95% interval.

    ``runs`` is the number of sampling units m; the factor (m - 1) / m is the
    incidence correction and the estimate tends to the abundance form (Chao1)
    as m grows. Returns ``(estimate, lower, upper, variance)``. The interval
    is Chao's log-transformed one, which cannot drop below ``s_obs``. With
    ``f1 == 0`` everything seen was seen twice or more, the estimate is
    ``s_obs``, and the interval is degenerate.
    """
    if s_obs <= 0 or runs < 2:
        return float(s_obs), float(s_obs), float(s_obs), 0.0
    a = (runs - 1) / runs
    if f2 > 0:
        est = s_obs + a * f1 * (f1 - 1) / (2 * (f2 + 1))
        var = (a * f1 * (f1 - 1) / (2 * (f2 + 1))
               + a * a * f1 * (2 * f1 - 1) ** 2 / (4 * (f2 + 1) ** 2)
               + a * a * f1 * f1 * f2 * (f1 - 1) ** 2 / (4 * (f2 + 1) ** 4))
    else:
        est = s_obs + a * f1 * (f1 - 1) / 2
        var = (a * f1 * (f1 - 1) / 2 + a * a * f1 * (2 * f1 - 1) ** 2 / 4
               - a * a * f1 ** 4 / (4 * est))
    var = max(var, 0.0)
    t = est - s_obs
    if t <= 0 or var <= 0:
        return est, float(s_obs), max(est, float(s_obs)), var
    k = math.exp(Z95 * math.sqrt(math.log(1 + var / (t * t))))
    return est, s_obs + t / k, s_obs + t * k, var


def census_from_table(table, *, unit="op", min_runs=2, slugs=None):
    """Estimate every weight class in ``table`` that has captures.

    Returns ``{slug: {side: {battery_key: stratum}}}`` where a stratum
    carries ``runs``, ``trials``, ``seeds``, ``claimed_d``, ``refuted_runs``,
    and ``classes``: one entry per weight ``w`` with captures, holding
    ``S_obs``, ``f1``, ``f2``, ``estimate``, ``ci95``, ``coverage`` (``S_obs``
    over the estimate), ``incidences`` (logical-in-run pairs),
    ``mean_incidence`` (incidences over ``S_obs``), ``calibrated`` (mean
    incidence at least ``MIN_MEAN_INCIDENCE``), ``runs_with_captures``, and
    ``censored`` (the count is a floor and the estimate is withheld). A
    stratum with fewer than ``min_runs`` runs or without captures has
    ``classes == {}`` and says so under ``note``.
    """
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}, not {unit!r}")
    out = {}
    for slug, sides in sorted(table["entries"].items()):
        if slugs is not None and slug not in slugs:
            continue
        out[slug] = {}
        for side, batteries in sorted(sides.items()):
            out[slug][side] = {}
            for key, st in sorted(batteries.items()):
                m = len(st["runs"])
                stratum = {"runs": m, "trials": st["trials"],
                           "seeds": sorted({int(r.split(":")[0]) for r in st["runs"]}),
                           "claimed_d": st.get("claimed_d"), "refuted_runs": st["refuted_runs"],
                           "classes": {}, "note": None}
                if not st["classes"]:
                    stratum["note"] = (f"no logical found at weight <= {st.get('claimed_d')} in "
                                       f"{m} run(s), {st['trials']} trials")
                elif m < min_runs:
                    stratum["note"] = f"{m} run(s): no recapture to estimate from yet"
                else:
                    for w_key in sorted(st["classes"], key=int):
                        cls = st["classes"][w_key]
                        counts = list(cls[unit].values())
                        s_obs = len(counts)
                        if s_obs == 0:
                            continue
                        f1 = sum(1 for c in counts if c == 1)
                        f2 = sum(1 for c in counts if c == 2)
                        incidences = sum(counts)
                        mean_inc = incidences / s_obs
                        row = {"S_obs": s_obs, "f1": f1, "f2": f2,
                               "incidences": incidences, "mean_incidence": round(mean_inc, 2),
                               "runs_with_captures": cls["runs_with"], "censored": bool(cls["censored"]),
                               "calibrated": False, "estimate": None, "ci95": None, "coverage": None}
                        if not cls["censored"]:
                            est, lo, hi, _ = chao(s_obs, f1, f2, m)
                            row.update(estimate=round(est, 2), ci95=[round(lo, 2), round(hi, 2)],
                                       coverage=round(s_obs / est, 3) if est > 0 else None,
                                       calibrated=mean_inc >= MIN_MEAN_INCIDENCE)
                        stratum["classes"][int(w_key)] = row
                out[slug][side][key] = stratum
    return out


def census(records, *, unit="op", min_runs=2):
    """Return the census of raw ``records``: fold them into a throwaway table and estimate."""
    table = new_table()
    fold(table, records)
    return census_from_table(table, unit=unit, min_runs=min_runs)


# -- the report ------------------------------------------------------------------------

def render(result, unit="op"):
    """Markdown: one table of estimates, then the strata with nothing to estimate."""
    what = "operators" if unit == "op" else "classes"
    lines = [f"| entry | side | battery | runs | w | {what} seen | f1 | f2 | mean recaptures | "
             "estimate | 95% CI | coverage |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    quiet = []
    sparse = censored = False
    for slug, sides in result.items():
        for side, batteries in sides.items():
            for key, st in batteries.items():
                if not st["classes"]:
                    quiet.append(f"- `{slug}` {side} ({key}): {st['note']}")
                    continue
                for w, c in st["classes"].items():
                    if c["censored"]:
                        censored = True
                        lines.append(f"| `{slug}` | {side} | {key} | {st['runs']} | {w} | >= {c['S_obs']} "
                                     f"(censored) | {c['f1']} | {c['f2']} | {c['mean_incidence']} | "
                                     "withheld | | |")
                        continue
                    ci = f"[{c['ci95'][0]}, {c['ci95'][1]}]"
                    if not c["calibrated"]:
                        ci += " (sparse)"
                        sparse = True
                    lines.append(f"| `{slug}` | {side} | {key} | {st['runs']} | {w} | {c['S_obs']} | "
                                 f"{c['f1']} | {c['f2']} | {c['mean_incidence']} | {c['estimate']} | "
                                 f"{ci} | {c['coverage']} |")
    if len(lines) == 2:
        lines = ["No weight class has captures in two or more runs yet."]
    if sparse:
        lines += ["", f"(sparse): each observed logical was found in fewer than {MIN_MEAN_INCIDENCE:g} runs "
                  "on average, the regime where the interval failed calibration in both directions; "
                  "read the count, not the interval."]
    if censored:
        lines += ["", f"(censored): a run hit the sweep's per-side cap or the table's {MAX_IDS} ids for "
                  "this weight class, so the count is a floor and no estimate is made."]
    if quiet:
        lines += ["", "Budget only (no captures, or one run):"] + quiet
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="census from the table, or from raw record files")
    rep.add_argument("records", nargs="*", help="raw record files (.jsonl or .jsonl.gz); default: the table")
    rep.add_argument("--table", default=DEFAULT_TABLE, help="the incidence table (default: %(default)s)")
    rep.add_argument("--slug", action="append", default=None, help="only these entries (repeatable)")
    rep.add_argument("--unit", choices=UNITS, default="op",
                     help="count distinct operators (op, default) or logical classes (cls)")
    rep.add_argument("--min-runs", type=int, default=2, help="runs a stratum needs before an estimate (default 2)")
    rep.add_argument("--json", metavar="OUT", help="write the census as JSON here as well")
    fo = sub.add_parser("fold", help="add raw record files to the table")
    fo.add_argument("records", nargs="+", help="raw record files (.jsonl or .jsonl.gz)")
    fo.add_argument("--table", default=DEFAULT_TABLE, help="the incidence table (default: %(default)s)")
    args = ap.parse_args(argv)

    if args.cmd == "fold":
        table = load_table(args.table)
        records, skipped = load_records(args.records)
        added = fold(table, records)
        save_table(table, args.table)
        print(f"folded {added} new run record(s) of {len(records)} read"
              + (f", {skipped} unreadable line(s) skipped" if skipped else "")
              + f" into {args.table} ({table['folded_records']} in all)")
        return 0

    if args.records:
        records, skipped = load_records(args.records)
        table = new_table()
        fold(table, records)
        source = f"{len(records)} record(s) from {len(args.records)} file(s)" + (
            f", {skipped} unreadable line(s) skipped" if skipped else "")
    else:
        if not os.path.exists(args.table):
            print(f"no table at {args.table} and no record files given; run "
                  "verify/refute_board.py --recapture PATH and fold it first", file=sys.stderr)
            return 2
        table = load_table(args.table)
        source = f"table {args.table}: {table['folded_records']} run record(s), updated {table['updated']}"
    result = census_from_table(table, unit=args.unit, min_runs=args.min_runs,
                               slugs=set(args.slug) if args.slug else None)
    print(source + "\n")
    print(render(result, unit=args.unit))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"unit": args.unit, "source": source, "census": result}, f, indent=1, sort_keys=True)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

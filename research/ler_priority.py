"""Order the circuit-bearing entries for logical-error-rate backfills by schedule depth.

Issue #6834: 92% of the committed circuits are flagged Johnson-coil
schedules, and the sequential span-flagged half runs a median 54 TICK layers
per round against 9 to 18 for the interleaved and unflagged ones. The
canonical noise recipe (verify/circuit_tools.py) depolarizes every idle data
qubit at every layer, so at equal ``d_circ`` a deep schedule sees several
times the faults per round and its measured rate saturates where a shallow
one is sub-threshold: seven of the 34 small entries measured in #6272,
#6333, #6810, and #6817 could take no ``circuit.ler`` point at p = 0.001,
all of them deep. A backfill that opens the shallow schedules first spends
its shots where a sub-threshold point is possible.

This script lists the entries that ship memory circuits and carry no
``circuit.ler`` yet, shallowest first, with the depth the issue measured:
``TICK`` instructions of ``memory_z.stim`` divided by ``circuit.rounds``
(``--basis x`` reads the other file). It never measures anything; the
measurement is ``verify/ler_measure.py``, and ``--commands`` prints one
invocation per entry in the chosen order.

    uv run --extra research python research/ler_priority.py                # the queue, shallowest first
    uv run --extra research python research/ler_priority.py --max-depth 20 --limit 40 --commands
    uv run --extra research python research/ler_priority.py --measured     # the measured entries, with their worst rate
    uv run --extra research python research/ler_priority.py --json queue.json

Nothing here reads ``verify/`` beyond the committed files, and nothing is
written to an entry.
"""
import argparse
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

TICK = re.compile(r"^\s*TICK\b", re.M)


def ticks_per_round(path, rounds):
    """TICK layers per round of one memory circuit file, the measure of issue #6834.

    A count over the text (``TICK`` lines divided by ``rounds``), so it needs
    no stim and agrees with the issue's table; one decimal. None when the
    file is missing or ``rounds`` is not positive.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None
    if not rounds or int(rounds) <= 0:
        return None
    return round(len(TICK.findall(text)) / int(rounds), 1)


def ler_points(circuit):
    """Every measured point of a circuit block, as (basis, point) pairs; [] when none."""
    ler = circuit.get("ler")
    if not isinstance(ler, dict):
        return []
    out = []
    for basis, recorded in ler.items():
        pts = [recorded] if isinstance(recorded, dict) else (recorded or [])
        for pt in pts:
            if isinstance(pt, dict):
                out.append((basis, pt))
    return out


def worst_rate(points, p=0.001):
    """Return the worse basis's ``ler_per_round`` at physical rate ``p``, or None."""
    vals = [pt.get("ler_per_round") for _, pt in points
            if pt.get("p") == p and isinstance(pt.get("ler_per_round"), (int, float))]
    return max(vals) if vals else None


def entries(codes_dir, circuits_dir, basis="z"):
    """One row per entry with a circuit block: slug, parameters, d_circ, depth, qubits, points."""
    rows = []
    for path in sorted(glob.glob(os.path.join(codes_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        circ = doc.get("circuit")
        if not isinstance(circ, dict):
            continue
        slug = os.path.splitext(os.path.basename(path))[0]
        dc = circ.get("d_circ") or {}
        vals = [int(dc[s]["value"]) for s in ("X", "Z")
                if isinstance(dc.get(s), dict) and isinstance(dc[s].get("value"), int)]
        stim_path = os.path.join(circuits_dir, slug, f"memory_{basis}.stim")
        points = ler_points(circ)
        rows.append({
            "slug": slug, "n": doc.get("n"), "k": doc.get("k"),
            "d": (doc.get("distance") or {}).get("d"),
            "d_circ": min(vals) if vals else None,
            "rounds": circ.get("rounds"),
            "ticks_per_round": ticks_per_round(stim_path, circ.get("rounds")),
            "points": len(points),
            "worst_ler_per_round_at_0.001": worst_rate(points),
        })
    return rows


def queue(rows, *, max_depth=None, min_d_circ=1, limit=None):
    """Return the unmeasured entries, shallowest first, then highest d_circ, then smallest n.

    An entry whose depth is unknown (no readable circuit file) sorts last,
    since nothing says it is cheap to measure.
    """
    todo = [r for r in rows if r["points"] == 0 and (r["d_circ"] or 0) >= min_d_circ]
    if max_depth is not None:
        todo = [r for r in todo if r["ticks_per_round"] is not None and r["ticks_per_round"] <= max_depth]
    todo.sort(key=lambda r: (r["ticks_per_round"] is None, r["ticks_per_round"] or 0,
                             -(r["d_circ"] or 0), r["n"] or 0, r["slug"]))
    return todo[:limit] if limit else todo


def command(row, p_grid=(0.01, 0.005, 0.002, 0.001)):
    """Return the ler_measure invocation for one entry, over the grid of the issue's batches."""
    ps = " ".join(f"{p:g}" for p in p_grid)
    return f"uv run --extra research python verify/ler_measure.py codes/{row['slug']}.json --p {ps}"


def _fmt(v):
    return "-" if v is None else (f"{v:.6f}" if isinstance(v, float) and v < 1 else str(v))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--codes-dir", default=os.path.join(_ROOT, "codes"))
    ap.add_argument("--circuits-dir", default=os.path.join(_ROOT, "circuits"))
    ap.add_argument("--basis", choices=("x", "z"), default="z", help="which memory circuit to measure the depth on")
    ap.add_argument("--max-depth", type=float, default=None,
                    help="keep entries at most this many TICK layers per round")
    ap.add_argument("--min-d-circ", type=int, default=1, help="keep entries with at least this d_circ")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--measured", action="store_true",
                    help="list the entries that already carry points, deepest first, with the worst rate at p = 0.001")
    ap.add_argument("--commands", action="store_true", help="print one ler_measure command per queued entry")
    ap.add_argument("--json", default=None, help="write the rows to this file")
    args = ap.parse_args(argv)

    rows = entries(args.codes_dir, args.circuits_dir, args.basis)
    if args.measured:
        shown = sorted((r for r in rows if r["points"]),
                       key=lambda r: (-(r["ticks_per_round"] or 0), r["slug"]))
        if args.limit:
            shown = shown[:args.limit]
        print(f"{len(shown)} measured entries, deepest first")
        print("slug             [[n,k,d]]       d_circ  ticks/round  points  worst ler/round at p=0.001")
        for r in shown:
            print(f"{r['slug']:16s} [[{r['n']},{r['k']},{r['d']}]]".ljust(33)
                  + f"{_fmt(r['d_circ']):>6}  {_fmt(r['ticks_per_round']):>11}  {r['points']:>6}  "
                  f"{_fmt(r['worst_ler_per_round_at_0.001'])}")
    else:
        shown = queue(rows, max_depth=args.max_depth, min_d_circ=args.min_d_circ, limit=args.limit)
        n_circ = len(rows)
        n_todo = sum(1 for r in rows if r["points"] == 0)
        print(f"{n_circ} entries with circuits, {n_todo} without a measured rate; "
              f"{len(shown)} queued" + (f" at depth <= {args.max_depth:g}" if args.max_depth is not None else "")
              + ", shallowest first")
        if args.commands:
            for r in shown:
                print(command(r))
        else:
            print("slug             [[n,k,d]]       d_circ  ticks/round  rounds")
            for r in shown:
                print(f"{r['slug']:16s} [[{r['n']},{r['k']},{r['d']}]]".ljust(33)
                      + f"{_fmt(r['d_circ']):>6}  {_fmt(r['ticks_per_round']):>11}  {_fmt(r['rounds']):>6}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"basis": args.basis, "rows": shown}, fh, indent=1)
            fh.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

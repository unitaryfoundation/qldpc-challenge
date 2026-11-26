#!/usr/bin/env python3
r"""Dry-run sweep of the board's circuit tier with Sisyphus, measured for cost as well as for finds.

Every circuit-tier entry records d_circ as a witnessed upper bound, and the
gate's own search (circuit_tools.ris_dem) cannot test that bound on a large
detector error model: it gets a few hundred trials there and its lightest
fault set is far above any claim. Sisyphus (sisyphus-qec,
github.com/varunmenon1310/sisyphus) is an information-set search that does
reach those claims, and PR #7264 proposes it as a second searcher in the
gate. This script is the step before that: it runs the same search over the
committed circuits outside the gate and records what the gate would have to
pay and what it would find, so that the budget, the memory, and the failure
rate are measured before anything blocks a submission on them.

For each memory circuit it derives the detector error model the gate derives
(circuit_tools.derive_dem), runs Sisyphus on it in a process of its own for a
fixed number of seconds without stopping at the claim, and records

    status       ok, refuted (a fault set lighter than the claim that
                 circuit_tools.witness_errors accepts), rejected (a lighter
                 proposal that check refuses), crash (non-zero exit; a
                 negative return code is the signal, -9 for an out-of-memory
                 kill among others), or timeout (killed at seconds + grace)
    time         set-up (matrices, kernels, windows) apart from search, and
                 from the search's own history the first moment it held a
                 fault set at the claimed weight and the first moment it
                 held a lighter one
    memory       the peak, sampled over the whole process group: the leader's
                 resident size, the sum of resident sizes, and on Linux the
                 sum of proportional sizes, which is the figure to hold
                 against a machine's memory since forked workers share pages

Sisyphus is not a dependency of this repository, so name it on the command
line; the record keeps the version that ran:

    uv run --frozen --extra research --with sisyphus-qec==0.2.1 \
        python research/audits/sisyphus_circuit_sweep.py sweep \
        --min-mechanisms 50000 --seconds 60 --shard 0/4 \
        --out research/audits/sisyphus_circuit_sweep-<date>-0.json

    uv run --frozen python research/audits/sisyphus_circuit_sweep.py report RECORD.json [RECORD.json ...] \\
        [--out MERGED.json]

A record is resumable: entries already in --out are skipped. Nothing here
edits codes/ or circuits/. A refuted entry is corrected the way
CONTRIBUTING.md describes under "Lowering a circuit fault distance already on
the board", with the witness the record holds.
"""

import argparse
import datetime
import json
import os
import platform
import signal
import statistics
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
import circuit_tools as CT  # noqa: E402
import stim  # noqa: E402

CODES = os.path.join(ROOT, "codes")
CIRCUITS = os.path.join(ROOT, "circuits")
SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}
MARKER = "SISYPHUS_SWEEP "
# Steps never bind; the wall-clock limit does.
MAX_STEPS = 10**9
KB_PER_GB = 1024 * 1024


# ---------------------------------------------------------------- the search


def child(stim_path, seconds, seed, workers):
    """Run Sisyphus on one memory circuit in this process and print one result line."""
    from importlib.metadata import version

    from sisyphus_qec import dem_to_matrices, lift_columns, side_distance

    t0 = time.monotonic()
    dem = CT.derive_dem(stim.Circuit(open(stim_path).read()))
    H, L, columns = dem_to_matrices(dem)
    t_matrices = time.monotonic() - t0
    res = side_distance(
        H,
        None,
        pair_rows=L,
        num_trials=MAX_STEPS,
        num_workers=max(2, int(workers)),  # Sisyphus 0.2.0 honours a time limit only with a pool
        time_limit=float(seconds),
        cutoff=0,
        seed=int(seed),
    )
    total = time.monotonic() - t0
    rec = {
        "version": version("sisyphus-qec"),
        "lightest": None,
        "witness": None,
        "steps": int(res.shots),
        "search_seconds": round(float(res.wall_time), 2),
        "setup_seconds": round(max(0.0, total - float(res.wall_time)), 2),
        "matrix_seconds": round(t_matrices, 2),
        "history": [[round(float(h[0]), 2), int(h[1])] for h in res.history][-60:],
    }
    if res.distance > 0 and res.witness is not None:
        rec["lightest"] = int(res.distance)
        rec["witness"] = sorted(int(i) for i in lift_columns(res.witness, columns))
        # Sisyphus keeps a history only when it schedules detector windows. Without
        # one (a small DEM) its own estimate of when the final weight was first
        # reached is the one time there is, and stands in as a single entry.
        if not any(w <= rec["lightest"] for _, w in rec["history"]) and res.t_best >= 0:
            rec["history"].append([round(float(res.t_best), 2), rec["lightest"]])
    print(MARKER + json.dumps(rec), flush=True)
    return 0


# -------------------------------------------------------------------- memory


def _linux_group(pgid):
    """Return (pid, rss_kb, pss_kb) for every process in group pgid, read from /proc."""
    rows = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            stat = open(f"/proc/{name}/stat").read()
            if int(stat[stat.rindex(")") + 2 :].split()[2]) != pgid:
                continue
            rss = pss = 0
            for line in open(f"/proc/{name}/smaps_rollup"):
                if line.startswith("Rss:"):
                    rss = int(line.split()[1])
                elif line.startswith("Pss:"):
                    pss = int(line.split()[1])
            rows.append((int(name), rss, pss))
        except (OSError, ValueError):
            continue  # the process ended between the listing and the read
    return rows


def group_memory(pgid):
    """Return (pid, rss_kb, pss_kb or None) for every process in group pgid."""
    if os.path.isdir("/proc/self") and os.path.exists("/proc/self/smaps_rollup"):
        return _linux_group(pgid)
    out = subprocess.run(["ps", "-o", "pid=,rss=", "-g", str(pgid)], capture_output=True, text=True, check=False)
    tok = out.stdout.split()
    return [(int(tok[i]), int(tok[i + 1]), None) for i in range(0, len(tok) - 1, 2)]


def kill_group(proc):
    """Kill the process group proc leads and reap proc, without waiting on a survivor's pipes."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    try:
        proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
        proc.wait()


# ------------------------------------------------------------------ one basis


def child_command(stim_path, seconds, seed, workers):
    """Return the command that runs `child` on stim_path under this interpreter."""
    return [
        sys.executable,
        os.path.abspath(__file__),
        "child",
        stim_path,
        "--seconds",
        f"{float(seconds):.1f}",
        "--seed",
        str(int(seed)),
        "--workers",
        str(int(workers)),
    ]


def first_time(history, weight):
    """Return the first history time at which the search held a fault set of at most `weight`."""
    for t, w in history:
        if w <= weight:
            return t
    return None


def run_basis(stim_path, claim, *, seconds, seed=0, workers=4, grace=300.0, command=None, interval=0.25):
    """Run the search on one memory circuit and return its record; see the module docstring."""
    dem = CT.derive_dem(stim.Circuit(open(stim_path).read()))
    rec = {"claim": int(claim), "mechanisms": int(dem.num_errors), "detectors": int(dem.num_detectors)}
    cmd = command or child_command(stim_path, seconds, seed, workers)
    t0 = time.monotonic()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    peak = {"processes": 0, "leader_rss": 0, "rss_sum": 0, "pss_sum": None}
    deadline = t0 + float(seconds) + float(grace)
    timed_out = False
    while proc.poll() is None:
        rows = group_memory(proc.pid)
        if rows:
            peak["processes"] = max(peak["processes"], len(rows))
            peak["leader_rss"] = max(peak["leader_rss"], max((r for p, r, _ in rows if p == proc.pid), default=0))
            peak["rss_sum"] = max(peak["rss_sum"], sum(r for _, r, _ in rows))
            if rows[0][2] is not None:
                peak["pss_sum"] = max(peak["pss_sum"] or 0, sum(s for _, _, s in rows))
        if time.monotonic() > deadline:
            timed_out = True
            kill_group(proc)
            break
        time.sleep(interval)
    out, err = ("", "") if timed_out else proc.communicate()
    rec["wall_seconds"] = round(time.monotonic() - t0, 2)
    rec["peak"] = {
        "processes": peak["processes"],
        "leader_rss_gb": round(peak["leader_rss"] / KB_PER_GB, 3),
        "rss_sum_gb": round(peak["rss_sum"] / KB_PER_GB, 3),
        "pss_sum_gb": None if peak["pss_sum"] is None else round(peak["pss_sum"] / KB_PER_GB, 3),
    }
    if timed_out:
        rec["status"] = "timeout"
        return rec
    lines = [ln for ln in out.splitlines() if ln.startswith(MARKER)]
    if proc.returncode != 0 or len(lines) != 1:
        rec["status"] = "crash"
        rec["returncode"] = proc.returncode
        rec["stderr"] = " | ".join((err or "").strip().splitlines()[-3:])[-400:]
        return rec
    got = json.loads(lines[0][len(MARKER) :])
    witness = got.pop("witness")
    rec.update(got)
    rec["t_reach_claim"] = first_time(got["history"], claim)
    rec["t_below_claim"] = first_time(got["history"], claim - 1)
    lightest = got["lightest"]
    if lightest is not None and lightest < claim:
        if CT.witness_errors(dem, witness, lightest):
            rec["status"] = "rejected"
        else:
            rec["status"] = "refuted"
            rec["witness"] = witness
    else:
        rec["status"] = "ok"
    return rec


# ------------------------------------------------------------------ the sweep


def circuit_slugs(codes_dir=CODES, circuits_dir=CIRCUITS):
    """Return the slugs that carry a circuit tier, largest committed X-memory circuit first."""
    sized = []
    for name in sorted(os.listdir(codes_dir)):
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        path = os.path.join(circuits_dir, slug, SIDE_FILES["X"] + ".stim")
        if os.path.exists(path) and "circuit" in json.load(open(os.path.join(codes_dir, name))):
            sized.append((-os.path.getsize(path), slug))
    return [slug for _, slug in sorted(sized)]


def shard(slugs, spec):
    """Return shard I of N ("I/N") of slugs by stride, so each shard gets every size."""
    if not spec:
        return list(slugs)
    i, n = (int(x) for x in spec.split("/"))
    if not 0 <= i < n:
        raise ValueError(f"shard {spec}: need 0 <= I < N")
    return list(slugs)[i::n]


def sweep_entry(slug, *, seconds, seed, workers, grace, min_mechanisms=0, codes_dir=CODES, circuits_dir=CIRCUITS):
    """Return the record of one entry, or None when its X-memory DEM is under min_mechanisms."""
    doc = json.load(open(os.path.join(codes_dir, slug + ".json")))
    block = doc["circuit"]
    entry = {
        "slug": slug,
        "n": doc["n"],
        "k": doc["k"],
        "d": doc["distance"]["d"],
        "family": doc.get("family"),
        "rounds": block.get("rounds"),
        "schedule": (block.get("notes") or "").split("(")[0].strip()[:80],
        "bases": {},
    }
    for side in ("X", "Z"):
        path = os.path.join(circuits_dir, slug, SIDE_FILES[side] + ".stim")
        if side == "X" and min_mechanisms:
            if CT.derive_dem(stim.Circuit(open(path).read())).num_errors < min_mechanisms:
                return None
        claim = int(block["d_circ"][side]["value"])
        entry["bases"][side] = run_basis(path, claim, seconds=seconds, seed=seed, workers=workers, grace=grace)
    return entry


def _quantiles(values):
    """Return {n, median, p90, max} of values, or None when there are none."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    return {
        "n": len(v),
        "median": round(statistics.median(v), 2),
        "p90": round(v[min(len(v) - 1, int(0.9 * len(v)))], 2),
        "max": round(v[-1], 2),
    }


def summarize(entries):
    """Return the distribution a budget is set from: statuses, times, memory, and the refuted entries."""
    bases = [(e["slug"], s, b) for e in entries for s, b in e["bases"].items()]
    status = {}
    for _, _, b in bases:
        status[b["status"]] = status.get(b["status"], 0) + 1
    memory_key = "pss_sum_gb" if any(b["peak"]["pss_sum_gb"] is not None for _, _, b in bases) else "rss_sum_gb"
    return {
        "entries": len(entries),
        "bases": len(bases),
        "status": status,
        "setup_seconds": _quantiles(b.get("setup_seconds") for _, _, b in bases),
        "wall_seconds": _quantiles(b.get("wall_seconds") for _, _, b in bases),
        "t_reach_claim": _quantiles(b.get("t_reach_claim") for _, _, b in bases),
        "t_below_claim": _quantiles(b.get("t_below_claim") for _, _, b in bases if b["status"] == "refuted"),
        "claim_not_reached": sum(
            1 for _, _, b in bases if b["status"] == "ok" and (b.get("lightest") is None or b["lightest"] > b["claim"])
        ),
        "peak_memory_gb": _quantiles(b["peak"][memory_key] for _, _, b in bases),
        "peak_memory_measure": memory_key,
        "refuted": sorted(
            [slug, side, b["claim"], b["lightest"], b["t_below_claim"]]
            for slug, side, b in bases
            if b["status"] == "refuted"
        ),
        "failed": sorted(
            [slug, side, b["status"], b.get("returncode")]
            for slug, side, b in bases
            if b["status"] in ("crash", "timeout", "rejected")
        ),
    }


def host():
    """Return what a reader needs to place the timings: platform, cores, memory."""
    info = {"platform": platform.platform(), "machine": platform.machine(), "cpus": os.cpu_count()}
    try:
        info["memory_gb"] = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (ValueError, OSError):
        info["memory_gb"] = None
    return info


def merge(records):
    """Return one record with every entry of `records` once, the first record's settings, and a fresh summary."""
    out = {k: v for k, v in records[0].items() if k not in ("entries", "summary", "shard")}
    entries = {}
    for record in records:
        for e in record["entries"]:
            entries[e["slug"]] = e
    out["merged_from"] = len(records)
    out["entries"] = [entries[slug] for slug in sorted(entries)]
    out["summary"] = summarize(out["entries"])
    return out


def load_record(path):
    """Return the record at path, or None when there is none yet."""
    return json.load(open(path)) if os.path.exists(path) else None


def save_record(record, path):
    """Write record to path through a rename, so an interrupted sweep leaves a readable file."""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None):
    """Run the sweep, the report, or the child search."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("child", help="internal: one search in this process")
    c.add_argument("stim_path")
    c.add_argument("--seconds", type=float, required=True)
    c.add_argument("--seed", type=int, default=0)
    c.add_argument("--workers", type=int, default=4)
    s = sub.add_parser("sweep", help="run the search over circuit-tier entries")
    s.add_argument("--out", required=True)
    s.add_argument("--slugs", nargs="*", default=None, help="entries to run (default: every circuit tier)")
    s.add_argument("--shard", default=None, help="I/N: run every Nth entry starting at I, largest circuits first")
    s.add_argument("--min-mechanisms", type=int, default=0, help="skip entries whose X-memory DEM is smaller")
    s.add_argument("--seconds", type=float, default=60.0, help="search limit per basis (default 60)")
    s.add_argument("--grace", type=float, default=300.0, help="seconds past the limit before the kill (default 300)")
    s.add_argument(
        "--workers", type=int, default=4, help="Sisyphus worker processes (default 4, the CI runner's cores)"
    )
    s.add_argument("--seed", type=int, default=0)
    r = sub.add_parser("report", help="summarize one or more records")
    r.add_argument("records", nargs="+")
    r.add_argument("--out", default=None, help="also write the records merged into one, each entry once")
    a = ap.parse_args(argv)
    if a.cmd == "child":
        return child(a.stim_path, a.seconds, a.seed, a.workers)
    if a.cmd == "report":
        record = merge([json.load(open(path)) for path in a.records])
        if a.out:
            save_record(record, a.out)
        print(json.dumps(record["summary"], indent=1))
        return 0
    record = load_record(a.out) or {
        "tool": "sisyphus-qec",
        "date": datetime.date.today().isoformat(),
        "seconds_per_basis": a.seconds,
        "grace": a.grace,
        "workers": a.workers,
        "seed": a.seed,
        "shard": a.shard,
        "min_mechanisms": a.min_mechanisms,
        "host": host(),
        "entries": [],
    }
    done = {e["slug"] for e in record["entries"]}
    for slug in shard(a.slugs or circuit_slugs(), a.shard):
        if slug in done:
            continue
        entry = sweep_entry(
            slug, seconds=a.seconds, seed=a.seed, workers=a.workers, grace=a.grace, min_mechanisms=a.min_mechanisms
        )
        if entry is None:
            continue
        record["entries"].append(entry)
        record["summary"] = summarize(record["entries"])
        save_record(record, a.out)
        print(
            slug,
            {s: (b["status"], b.get("lightest"), b["claim"], b["wall_seconds"]) for s, b in entry["bases"].items()},
            flush=True,
        )
    print(json.dumps(record.get("summary")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

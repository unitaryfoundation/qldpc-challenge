"""Re-derive and re-check the refutations behind the board's proof_log certs.

A proof_log certificate does not carry its refutation. It carries the sha256
of the formula that was refuted and the recipe to regenerate it, because the
refutations run to hundreds of megabytes and a committed blob is not
something CI can audit (PR #2754). What makes that honest is this script: it
regenerates each side's CNF from the code JSON, refuses to go on if the hash
is not the recorded one, refutes the formula again with kissat, and has
drat-trim check the new proof. A certificate whose formula no longer hashes
to the recorded value, or whose formula is no longer refuted, fails the run.

    python verify/replay_proofs.py --all                  # the weekly audit
    python verify/replay_proofs.py --sample 12 --seed 2754  # a PR's rotating subset
    python verify/replay_proofs.py 72-12-6 144-12-12      # named entries

The sample excludes entries whose recorded solve and check time exceeds
--max-secs, so a pull request pays for a few seconds of replay while the
weekly run pays for all of it.
"""
import argparse
import glob
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sat_certify import (  # noqa: E402
    _logicals,
    _matrix,
    side_cnf,
    write_dimacs,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "certs")
BATCH_LOG = os.path.join(CERTS, "proof_log_batch.jsonl")
UNKNOWN_REPLAY_SECS = 600.0
REPLAY_ESTIMATE_SAFETY_FACTOR = 1.25


def replayable():
    """Every certificate at proof_log that records a replay and a formula hash."""
    out = {}
    for path in sorted(glob.glob(os.path.join(CERTS, "*.json"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                cert = json.load(f)
        except (OSError, ValueError):
            continue
        v = cert.get("verification") or {}
        if v.get("level") == "proof_log" and v.get("replay") \
                and v.get("cnf_sha256"):
            out[slug] = cert
    return out


def recorded_secs():
    """Solve plus check seconds per entry from the batch log, where known."""
    secs = {}
    if not os.path.exists(BATCH_LOG):
        return secs
    with open(BATCH_LOG, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            secs[r["slug"]] = sum((r.get(f"{s}_{k}") or 0) for s in "XZ"
                                  for k in ("solve_secs", "check_secs"))
    return secs


def _hashes(cert):
    """Return the per-side formula hashes a certificate records."""
    out = {}
    for part in cert["verification"]["cnf_sha256"].split(";"):
        side, _, h = part.partition("=")
        out[side] = h
    return out


def replay(slug, cert, work, tlim):
    """Regenerate, re-refute, and re-check one entry; return a report."""
    with open(os.path.join(ROOT, "codes", slug + ".json"),
              encoding="utf-8") as f:
        doc = json.load(f)
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    rep = {"slug": slug, "n": n, "sides": {}, "ok": True}
    for side, H_same, H_opp in (("X", HX, HZ), ("Z", HZ, HX)):
        want = _hashes(cert).get(side)
        if want is None:
            continue
        # The rung the side rests on: d - 1 on an exact certificate, and
        # the top UNSAT rung of a partial one's ladder (issue #4230).
        W = int((cert["sides"].get(side) or {}).get("proved_min", cert["d"])) - 1
        t0 = time.time()
        L = _logicals(H_opp, H_same)
        clauses, nvars = side_cnf(H_opp, L, W)
        cnf = os.path.join(work, f"{slug}-{side}.cnf")
        proof = os.path.join(work, f"{slug}-{side}.proof")
        got = write_dimacs(clauses, nvars, cnf)
        blk = {"W": W, "cnf_sha256_matches": got == want}
        if got != want:
            # The recorded refutation was of a different formula than this
            # emitter now produces. That is a defect in the emitter or the
            # entry, not a proof of anything, so the side stops here.
            blk["detail"] = (f"regenerated CNF hashes to {got[:16]}, the "
                             f"certificate recorded {want[:16]}")
            rep["ok"] = False
            rep["sides"][side] = blk
            continue
        try:
            r = subprocess.run(["kissat", "-q", "--no-binary", cnf, proof],
                               capture_output=True, text=True, timeout=tlim,
                               check=False)
            blk["kissat"] = {10: "SAT", 20: "UNSAT"}.get(
                r.returncode, f"exit {r.returncode}")
            if r.returncode == 20:
                c = subprocess.run(["drat-trim", cnf, proof],
                                   capture_output=True, text=True,
                                   timeout=tlim, check=False)
                blk["drat_trim"] = ("VERIFIED" if "s VERIFIED" in
                                    (c.stdout or "") + (c.stderr or "")
                                    else "NOT VERIFIED")
        except subprocess.TimeoutExpired:
            blk["kissat"] = "TIMEOUT"
        blk["secs"] = round(time.time() - t0, 1)
        if blk.get("drat_trim") != "VERIFIED":
            rep["ok"] = False
        rep["sides"][side] = blk
        for p in (cnf, proof):
            if os.path.exists(p):
                os.remove(p)
    return rep


def _estimated_secs(slug, secs):
    """Estimate solve/check time, conservatively filling missing rows."""
    return secs.get(slug, UNKNOWN_REPLAY_SECS)


def select_shard(items, spec, secs=None):
    """Partition entries by recorded runtime, longest first, into shard ``I/K``.

    Every item goes to the currently lightest shard, which keeps the predicted
    replay time balanced when slug order happens to cluster slow certificates.
    The assignment is deterministic for a fixed set of recorded times.
    """
    i_str, _, k_str = spec.partition("/")
    i, k = int(i_str), int(k_str)
    if k < 1 or not 0 <= i < k:
        raise ValueError(f"shard must be I/K with 0 <= I < K, not {spec!r}")
    secs = recorded_secs() if secs is None else secs
    shards = [[] for _ in range(k)]
    loads = [0.0] * k
    ordered = sorted(items, key=lambda slug: (-_estimated_secs(slug, secs), slug))
    for slug in ordered:
        target = min(range(k), key=lambda shard: (loads[shard], shard))
        shards[target].append(slug)
        loads[target] += _estimated_secs(slug, secs)
    return shards[i]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="*", help="entries to replay")
    ap.add_argument("--all", action="store_true",
                    help="replay every proof_log certificate")
    ap.add_argument("--sample", type=int, default=0,
                    help="replay this many entries chosen by --seed")
    ap.add_argument("--seed", type=int, default=None,
                    help="which rotating subset; defaults to the day number")
    ap.add_argument("--max-secs", type=float, default=20.0,
                    help="sample only entries whose recorded solve and check "
                         "time is at most this (default 20)")
    ap.add_argument("--tlim", type=int, default=900,
                    help="per-solve and per-check time limit (default 900)")
    ap.add_argument("--json", action="store_true",
                    help="print one JSON report per entry")
    ap.add_argument("--shard", default=None, metavar="I/K",
                    help="replay only shard I of K of the chosen entries (every K-th "
                         "of them in slug order from the I-th), so a run can be split "
                         "across jobs (issue #5578)")
    ap.add_argument("--max-minutes", type=float, default=None, metavar="M",
                    help="stop opening entries after M minutes; what was opened is "
                         "replayed to the end and the count left is reported (a budget "
                         "stop is not a failure)")
    a = ap.parse_args(argv)

    certs = replayable()
    secs = recorded_secs()
    if a.all:
        chosen = sorted(certs)
    elif a.sample:
        pool = sorted(s for s in certs if secs.get(s, 0) <= a.max_secs)
        seed = a.seed if a.seed is not None else int(time.time() // 86400)
        chosen = sorted(random.Random(seed).sample(pool,
                                                   min(a.sample, len(pool))))
    else:
        chosen = a.slugs
    if a.shard is not None:
        try:
            chosen = select_shard(chosen, a.shard, secs)
        except ValueError as e:
            print(e)
            return 2
    missing = [s for s in chosen if s not in certs]
    if missing:
        print(f"not replayable (no proof_log certificate with a replay "
              f"recipe): {' '.join(missing)}")
        return 2
    if not chosen:
        print("nothing to replay")
        return 0
    for tool in ("kissat", "drat-trim"):
        if shutil.which(tool) is None:
            print(f"{tool} is not on PATH")
            return 2

    work = tempfile.mkdtemp(prefix="replay-")
    failed, t0 = [], time.time()
    left = []
    try:
        for i, slug in enumerate(chosen):
            if a.max_minutes is not None:
                remaining = a.max_minutes * 60 - (time.time() - t0)
                if remaining <= 0:
                    left.extend(chosen[i:])
                    break
                estimate = _estimated_secs(slug, secs) * REPLAY_ESTIMATE_SAFETY_FACTOR
                if estimate > remaining:
                    left.append(slug)
                    continue
            rep = replay(slug, certs[slug], work, a.tlim)
            if a.json:
                print(json.dumps(rep, sort_keys=True))
            else:
                sides = " ".join(
                    f"{s}:{'ok' if b.get('drat_trim') == 'VERIFIED' else 'FAIL'}"
                    for s, b in sorted(rep["sides"].items()))  # noqa: E501
                print(f"{slug}: {'ok' if rep['ok'] else 'FAILED'}  {sides}")
            if not rep["ok"]:
                failed.append(rep)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"{len(chosen) - len(left)} replayed, {len(failed)} failed, "
          + (f"{len(left)} left unopened at the {a.max_minutes:g} min budget, " if left else "")
          + f"{round(time.time() - t0)}s")
    for rep in failed:
        print(json.dumps(rep, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

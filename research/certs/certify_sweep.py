#!/usr/bin/env python3
r"""Work the cheap head of the certification queue and stage what closes (issue #4148).

research/certs/todo.json orders every upper-bound entry by what certifying it
is worth and what it should cost (certification_queue.py, issue #4027), and
until this script nothing worked it: the queue was regenerated weekly and
certified nothing. This sweep works its head on a bounded budget.

Per entry, in queue order, it runs verify/sat_certify.py's certifier with the
proof path at one time limit per solve: both sides asked at weight d - 1 in
the selector encoding with CryptoMiniSat, and re-emitted as pure CNF, refuted
by kissat, and checked by drat-trim. It opens entries until the job budget is
spent and records every attempt, closed or not, as one line of
attempts.jsonl, so an entry that timed out at this budget is not reopened at
the same budget next week and a reader can see what was tried.

What it stages is the #3666 shape: the certifier's own record with the
per-side proof block removed, written to <out-dir>/certs/<slug>.json, and for
a proof_log certificate a row for certs/proof_log_batch.jsonl with the clause
counts, proof and trimmed-core sizes, and solve and check seconds. ``stage``
copies that into certs/ for a certs-only PR, which the certify-weekly
workflow opens. Nothing here edits codes/. An entry whose side values differ
from its d is skipped: the certifier asks both sides at d - 1, and the site
honors a certificate only when its side values match the entry's
(site/build.py, cert_consistent).

A side that comes back SAT is a logical lighter than the claim. That is a
refutation of the entry, not a certificate: the witness goes in the attempt
row, nothing is staged, and ``run`` exits 3 so the workflow reports it.

Each entry is certified in a subprocess under a hard wall clock. The
solver's own time limit is advisory: CryptoMiniSat checks it between search
rounds, and a 442-qubit, k = 234 instance ran nine minutes past a 60 s limit
in testing. An entry killed at the wall clock is recorded as a timeout, with
the kill in its note, and nothing of it is staged.

With a tropidist checkout (research/certs/tropidist_certify.py, issue #4716)
``--backend`` chooses what runs. ``tropidist`` runs that tool alone: it closes
in seconds what the SAT path takes minutes over, its records are solver
level, and it is the only certifier for stabilizer entries, which it admits.
``tropidist+sat`` runs it first and hands a CSS entry it closed to the SAT
proof path, filing the proof_log record when that finishes and the tool's
record otherwise; an entry the tool did not close is not retried with SAT in
the same run unless a ladder is on, in which case the ladder runs on it and
its record replaces the tool's when it proves at least as much, and a tool
error falls back to SAT. Every attempt row names
the backend that produced it and, for a side that did not close, the lower
bound the tool proved.

With ``--ladder SECONDS`` (issue #4230) the SAT path asks each side at
W = 1, 2, ... up to d - 1 instead of at d - 1 alone, spending at most that
many seconds per side. UNSAT at W is the theorem d >= W + 1 whatever happens
above it, so an entry that does not close still leaves a proven lower bound,
and the run stages it as a partial certificate (``d_exact`` false,
``d_lower``), which the board shows as the interval d_lower <= d <= d. A
partial certificate already in certs/ is reopened at its own d_lower when
``--retry`` names it or the ladder budget is larger than the one it
recorded, and replaced only when the new run raises the bound; the old rungs
stay in the file. The tropidist backend's per-side lower bounds are filed the
same way.

    uv run --extra research python research/certs/certify_sweep.py run --tlim 600 --job-seconds 14400
    uv run --extra research python research/certs/certify_sweep.py run --tlim 120 --ladder 300
    uv run --extra research python research/certs/certify_sweep.py run --backend tropidist+sat \\
        --tropidist /tmp/tropidist --threads 4
    uv run python research/certs/certify_sweep.py stage --out-dir research/out/certify_sweep
    uv run python research/certs/certify_sweep.py pr-body --out-dir research/out/certify_sweep --out body.md
"""
import argparse
import copy
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "verify"))
CODES = os.path.join(ROOT, "codes")
CERTS = os.path.join(ROOT, "certs")
TODO = os.path.join(HERE, "todo.json")
ATTEMPTS = os.path.join(HERE, "attempts.jsonl")
OUT_DIR = os.path.join(ROOT, "research", "out", "certify_sweep")
BATCH_LOG = "proof_log_batch.jsonl"
OUTCOMES = ("exact", "partial", "timeout", "refuted", "error")
EXIT_REFUTED = 3
SAT_CERTIFY = os.path.join(ROOT, "verify", "sat_certify.py")
TROPIDIST_CERTIFY = os.path.join(HERE, "tropidist_certify.py")
BACKENDS = ("sat", "tropidist", "tropidist+sat")
WALL_FLOOR = 300


def wall_clock(tlim, ladder=None):
    """Return the hard per-entry limit: six solves of tlim (two per side, three tools) plus setup.

    A ladder adds its per-side budget twice: the rung it is on when the
    budget runs out may still take its six solves.
    """
    return 6 * tlim + WALL_FLOOR + (2 * int(ladder) if ladder else 0)


def tropidist_wall(tlim):
    """Return the hard per-entry limit of the tropidist backend: one run of tlim per side plus setup."""
    return 2 * tlim + WALL_FLOOR


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


# How long an exact attempt holds its entry back while its PR lands. After
# that the PR was never opened, or was closed without merging, and the entry
# is solved again rather than locked out by a certificate nobody filed.
AWAITING_DAYS = 14


def _days_since(date_str, today=None):
    try:
        then = datetime.date.fromisoformat(date_str or "")
    except ValueError:
        return None
    now = datetime.date.fromisoformat(today) if today else datetime.datetime.now(datetime.timezone.utc).date()
    return (now - then).days


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_url():
    """Return the Actions run URL when this is one, so a row says where it came from."""
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run_id}"


def load_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def last_attempts(rows):
    """Return the latest row per slug, in file order."""
    return {r["slug"]: r for r in rows}


def load_queue(path=TODO):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _row_from_doc(slug, doc):
    """Build a queue-shaped row for a slug named on the command line but not in the queue."""
    dist = doc["distance"]
    sides = {s: {"value": dist[s]["value"]} for s in ("X", "Z", "P") if isinstance(dist.get(s), dict)}
    return {"slug": slug, "code_type": doc.get("code_type", "CSS"), "n": doc["n"], "k": doc["k"],
            "d": dist["d"], "sides": sides, "band": None, "position": None, "record": None}


def _cert_on_file(certs_dir, slug):
    path = os.path.join(certs_dir, slug + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def select(queue, *, last, tlim, certs_dir=CERTS, codes_dir=CODES, slugs=None, retry=False, today=None,
           stabilizer_ok=False, ladder=None):
    """Return the entries the sweep opens, in queue order, and why it passes over the rest.

    Skipped: stabilizer entries unless ``stabilizer_ok`` (the SAT path has no
    Pauli-weight certifier; the tropidist backend has), entries that have a
    certificate file already, entries whose side values differ from d (a
    certificate at d would not be honored), entries not on the board, an
    entry a previous attempt refuted, an entry a previous attempt certified
    whose PR has not landed (for ``AWAITING_DAYS`` days; after that the
    certificate was lost or its PR closed, and the entry is solved again),
    and, unless ``retry``, an entry that timed out or
    errored at this time limit or a longer one (with a ladder budget at least
    ``ladder``). Naming ``slugs`` lifts the attempt-based skips for those
    slugs and admits slugs outside the queue. The first four skips hold
    either way: a certificate at d would change nothing for those entries.

    A partial certificate on file (``d_exact`` false) is not a closed entry:
    with ``ladder`` it is reopened at its own ``d_lower`` when ``retry`` or
    ``slugs`` names it or the new budget is larger than the one it recorded,
    and the row then carries ``start`` and ``raise_from``; otherwise it is
    skipped as ``partial``.
    """
    by_slug = {r["slug"]: r for r in queue.get("entries", [])}
    if slugs:
        rows = []
        for slug in slugs:
            if slug in by_slug:
                rows.append(by_slug[slug])
                continue
            path = os.path.join(codes_dir, slug + ".json")
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    rows.append(_row_from_doc(slug, json.load(f)))
            else:
                rows.append({"slug": slug, "code_type": "?", "n": 0, "k": 0, "d": 0, "sides": {}})
    else:
        rows = list(queue.get("entries", []))
    chosen, skipped, reasons = [], Counter(), {}

    def skip(slug, key, why):
        skipped[key] += 1
        reasons[slug] = why

    for r in rows:
        slug = r["slug"]
        stab = r.get("code_type") == "stabilizer"
        if r.get("code_type") != "CSS" and not (stab and stabilizer_ok):
            skip(slug, "stabilizer", "stabilizer entry: the SAT path has no Pauli-weight certifier; "
                                     "the tropidist backend admits it")
            continue
        if not os.path.exists(os.path.join(codes_dir, slug + ".json")):
            skip(slug, "not_on_board", "no codes/ file: the queue is older than the board")
            continue
        on_file = _cert_on_file(certs_dir, slug)
        if on_file is not None and (on_file.get("d_exact") or not on_file.get("d_lower")):
            skip(slug, "certified", "certs/ already has a file for it")
            continue
        if on_file is not None:
            had = ((on_file.get("ladder") or {}).get("budget_per_side") or 0)
            if not ladder:
                skip(slug, "partial", f"certs/ has a partial certificate (d >= {on_file['d_lower']}); "
                                      "a ladder run raises it")
                continue
            if not (retry or slugs or ladder > had):
                skip(slug, "partial", f"certs/ has a partial certificate (d >= {on_file['d_lower']}) from a "
                                      f"{had:g} s ladder; --retry or a larger --ladder raises it")
                continue
            r = dict(r, start=int(on_file["d_lower"]), raise_from=on_file)
        values = {s: v.get("value") for s, v in (r.get("sides") or {}).items()}
        want = {"P"} if stab else {"X", "Z"}
        if set(values) != want or any(v != r["d"] for v in values.values()):
            skip(slug, "side_mismatch",
                 f"side values {values} differ from d = {r['d']}; a certificate at d would not be honored")
            continue
        prev = last.get(slug) if not slugs else None
        if prev and prev.get("outcome") == "refuted":
            skip(slug, "refuted", f"refuted on {prev.get('date')}; the entry's claim has to change first")
            continue
        if prev and prev.get("outcome") == "exact":
            age = _days_since(prev.get("date"), today)
            if age is None or age <= AWAITING_DAYS:
                skip(slug, "awaiting_pr", f"certified on {prev.get('date')}; its certificate has not landed")
                continue
        if (prev and not retry and prev.get("outcome") in ("timeout", "error")
                and (prev.get("tlim") or 0) >= tlim and (prev.get("ladder") or 0) >= (ladder or 0)):
            skip(slug, "attempted", f"{prev.get('outcome')} at {prev.get('tlim')} s per solve on {prev.get('date')}")
            continue
        chosen.append(r)
    return chosen, skipped, reasons


def lower_bound_of(cert):
    """Return the lower bound a record proves on both sides, or None.

    ``d_lower`` when the SAT ladder wrote one; otherwise the minimum over the
    two CSS sides of what each proved: d on a closed side, the tropidist
    backend's ``lower_bound`` on an open one. None when a side proved nothing
    or the record is not two-sided (the partial tier is CSS only).
    """
    sides = cert.get("sides") or {}
    if isinstance(cert.get("d_lower"), int):
        return cert["d_lower"]
    if set(sides) != {"X", "Z"}:
        return None
    bounds = []
    for blk in sides.values():
        blk = blk or {}
        if blk.get("status") == "SAT":
            return None
        b = cert.get("d") if blk.get("exact") else (blk.get("proved_min") or blk.get("lower_bound"))
        if not isinstance(b, int):
            return None
        bounds.append(b)
    return min(bounds)


def classify(cert):
    """exact, refuted, partial, or timeout, from the certifier's record."""
    if cert.get("d_exact"):
        return "exact"
    statuses = {b.get("status") for b in (cert.get("sides") or {}).values()}
    if "SAT" in statuses:
        return "refuted"
    lb = lower_bound_of(cert)
    if lb is not None and lb >= 2:
        return "partial"
    return "timeout"


def partial_certificate(cert, doc):
    """Return a partial record in the shape certs/ files (issue #4230).

    The proof blocks go the way ``certificate`` sends them; every side gets
    its ``proved_min`` (the ladder's, or the tropidist backend's
    ``lower_bound``, or d on a closed side); ``d_lower`` is their minimum;
    and ``verification.checks_sha256`` binds the bound to the entry's
    matrices, which is what the site honors it by.
    """
    from check_certs import checks_sha256
    out = certificate(cert)
    for blk in out["sides"].values():
        if blk.get("exact"):
            blk["proved_min"] = out["d"]
        elif not isinstance(blk.get("proved_min"), int):
            blk["proved_min"] = blk.pop("lower_bound", None) or 1
        blk.pop("lower_bound", None)
    out["d_exact"] = False
    out["d_lower"] = min(b["proved_min"] for b in out["sides"].values())
    out.setdefault("verification", {"level": "solver"})
    out["verification"]["checks_sha256"] = checks_sha256(doc)
    return out


def _top_rung(ladder):
    """The top UNSAT rung of a ladder, or None."""
    tops = [r for r in (ladder or []) if r.get("status") == "UNSAT"]
    return max(tops, key=lambda r: int(r["W"])) if tops else None


def raise_certificate(old, new):
    """Merge a reopened partial certificate with the run that continued it.

    Per side the old rungs below the new run's start are kept ahead of the
    new ones, so the file shows the whole ascent, and ``proved_min`` is the
    larger of the two. The level is decided from the merged ladders: proof_log
    only when every side's top UNSAT rung was proof-checked and recorded the
    formula it refuted, with ``cnf_sha256`` rebuilt from those rungs, since the
    replay regenerates each side at its ``proved_min`` - 1. Returns the merged
    record; ``new`` is returned unchanged when it is exact (the ladder
    reached d - 1, and an exact certificate is its own evidence).
    """
    if new.get("d_exact"):
        return new
    out = copy.deepcopy(new)
    start = int((new.get("ladder") or {}).get("start") or 1)
    for side, blk in out["sides"].items():
        prev = (old.get("sides") or {}).get(side) or {}
        kept = [r for r in (prev.get("ladder") or []) if int(r["W"]) < start]
        blk["ladder"] = kept + list(blk.get("ladder") or [])
        blk["proved_min"] = max(int(prev.get("proved_min") or 1), int(blk.get("proved_min") or 1))
        top = _top_rung(blk["ladder"])
        if top is not None and int(top["W"]) + 1 == blk["proved_min"]:
            tail = (blk.get("note") or "").split("; ", 1)
            blk["note"] = f"no logical < {blk['proved_min']} exists" + (f"; {tail[1]}" if len(tail) > 1 else "")
    out["d_lower"] = min(int(b["proved_min"]) for b in out["sides"].values())
    tops = {s: _top_rung(b.get("ladder")) for s, b in out["sides"].items()}
    verified = all(r is not None and r.get("proof") == "verified" and r.get("cnf_sha256")
                   and int(r["W"]) + 1 == out["sides"][s]["proved_min"] for s, r in tops.items())
    template = next((c["verification"] for c in (new, old)
                     if (c.get("verification") or {}).get("level") == "proof_log"), None)
    if verified and template:
        v = copy.deepcopy(template)
        v["cnf_sha256"] = ";".join(f"{s}={tops[s]['cnf_sha256']}" for s in sorted(tops))
        out["verification"] = v
    else:
        out["verification"] = {"level": "solver",
                               "note": "raised ladder; not every side's top rung carries a checked proof"}
    out["verification"]["checks_sha256"] = (old.get("verification") or {}).get("checks_sha256") \
        or (new.get("verification") or {}).get("checks_sha256")
    out["ladder"] = {"start": int((old.get("ladder") or {}).get("start") or start),
                     "budget_per_side": (new.get("ladder") or {}).get("budget_per_side"),
                     "raised_from": int(old.get("d_lower") or 1)}
    return out


def certificate(cert):
    """Return the record as it is filed: the per-side proof block removed (#3666)."""
    out = copy.deepcopy(cert)
    for blk in out.get("sides", {}).values():
        blk.pop("proof", None)
    return out


def batch_row(slug, n, cert):
    """Return the certs/proof_log_batch.jsonl row of a proof_log certificate, else None."""
    v = cert.get("verification") or {}
    if v.get("level") != "proof_log":
        return None
    row = {"slug": slug, "n": n, "level": "proof_log", "cnf_sha256": v.get("cnf_sha256"),
           "detail": v.get("note")}
    for side, blk in cert["sides"].items():
        pr = blk.get("proof") or {}
        row[f"{side}_cnf_clauses"] = (pr.get("cnf") or {}).get("clauses")
        row[f"{side}_proof_bytes"] = (pr.get("proof") or {}).get("bytes")
        row[f"{side}_trimmed_bytes"] = (pr.get("trimmed") or {}).get("bytes")
        row[f"{side}_solve_secs"] = pr.get("solve_secs")
        row[f"{side}_check_secs"] = pr.get("check_secs")
    return row


def _side_summary(blk):
    pr = blk.get("proof") or {}
    if pr.get("proved"):
        proof = "verified"
    elif pr:
        proof = pr.get("detail") or pr.get("status") or "?"
    else:
        proof = None
    out = {"status": blk.get("status"), "secs": blk.get("secs")}
    if proof is not None:
        out["proof"] = proof
    if pr.get("solve_secs") is not None:
        out["proof_secs"] = round((pr.get("solve_secs") or 0) + (pr.get("check_secs") or 0), 1)
    if blk.get("lower_bound") is not None:
        out["lower_bound"] = blk["lower_bound"]
    if blk.get("proved_min") is not None:
        out["lower_bound"] = blk["proved_min"]
    if blk.get("ladder"):
        out["rungs"] = [f"{r['W']}:{r['status']}" for r in blk["ladder"]]
    return out


def tropidist_in_subprocess(path, slug, tlim, root, threads, wall):
    """Run research/certs/tropidist_certify.py on one entry under a hard wall clock.

    Returns (record, error, killed) like certify_in_subprocess. Exit 0 and 1
    are verdicts (exact or not) with the record on stdout; exit 2 is the
    certifier refusing (no checkout, a pairing set that does not span k, a
    vector the board rejects), reported from its last stderr line.
    """
    cmd = [sys.executable, TROPIDIST_CERTIFY, path, "--tropidist", root, "--tlim", str(float(tlim)),
           "--threads", str(int(threads)), "--json"]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=wall)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()
        proc.communicate()
        return None, None, True
    if proc.returncode not in (0, 1) or not out.strip():
        tail = (err or "").strip().splitlines()
        return None, (tail[-1] if tail else f"tropidist_certify exit {proc.returncode}"), False
    try:
        return json.loads(out), None, False
    except ValueError:
        return None, f"tropidist_certify printed no record for {slug}", False


def certify_in_subprocess(path, slug, tlim, proof_dir, wall, script=None, ladder=None, start=1):
    """Run verify/sat_certify.py on one entry under a hard wall clock.

    Returns (record, error, killed): the certifier's JSON record, or the
    error it printed, or killed=True when the wall clock ended it. The
    subprocess gets its own session so the kill reaches kissat and drat-trim
    as well as the Python parent.
    """
    cmd = [sys.executable, script or SAT_CERTIFY, path, "--proof", proof_dir, "--tlim", str(int(tlim)), "--json"]
    if ladder:
        cmd += ["--ladder", "--budget", str(float(ladder)), "--start", str(int(start or 1))]
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=wall)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()
        proc.communicate()
        return None, None, True
    if proc.returncode not in (0, 1) or not out.strip():
        tail = (err or "").strip().splitlines()
        return None, (tail[-1] if tail else f"sat_certify exit {proc.returncode}"), False
    try:
        return json.loads(out), None, False
    except ValueError:
        return None, f"sat_certify printed no record for {slug}", False


def attempt_row(row, cert, *, tlim, date, head, url, secs, error=None, killed=False, backend="sat",
                upgrade=None, ladder=None):
    """One line of attempts.jsonl.

    ``backend`` names what produced the record; ``upgrade`` what the SAT path
    did after the tool closed an entry.
    """
    out = {"date": date, "head": head, "run": url, "slug": row["slug"], "n": row["n"], "k": row["k"],
           "d": row["d"], "band": row.get("band"), "position": row.get("position"), "tlim": tlim,
           "secs": round(secs, 1), "backend": backend}
    if upgrade:
        out["upgrade"] = upgrade
    if ladder:
        out["ladder"] = ladder
    if row.get("start"):
        out["start"] = row["start"]
    if killed:
        wall = tropidist_wall(tlim) if backend == "tropidist" else wall_clock(tlim, ladder)
        out.update(outcome="timeout", level=None, sides={},
                   note=f"killed at the {wall} s wall clock; the solver's own limit did not hold")
        return out
    if error is not None:
        out.update(outcome="error", level=None, sides={}, note=error[:500])
        return out
    outcome = classify(cert)
    out["outcome"] = outcome
    out["level"] = (cert.get("verification") or {}).get("level") if outcome in ("exact", "partial") else None
    out["sides"] = {s: _side_summary(b) for s, b in cert["sides"].items()}
    if outcome == "partial":
        out["d_lower"] = lower_bound_of(cert)
        out["note"] = f"proved d >= {out['d_lower']} below the claim"
    if outcome == "refuted":
        wits = {s: b.get("witness") for s, b in cert["sides"].items() if b.get("status") == "SAT"}
        out["witness"] = wits
        out["note"] = ("a logical lighter than the claim exists on side "
                       + ", ".join(f"{s} (weight {len(w)})" for s, w in wits.items()))
    return out


def _write_json(path, obj, indent=2):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=indent, sort_keys=True)
        f.write("\n")


def _sat_attempt(path, slug, tlim, wall, certify, ladder=None, start=1):
    """One SAT-path attempt: (record, error, killed), in a subprocess or through the stand-in."""
    proof_dir = tempfile.mkdtemp(prefix=f"certify-{slug}-")
    kw = {"ladder": True, "budget": ladder, "start": start or 1} if ladder else {}
    try:
        if certify is None:
            return certify_in_subprocess(path, slug, tlim, proof_dir, wall, ladder=ladder, start=start)
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        return certify(doc, tlim=tlim, proof_dir=proof_dir, slug=slug, **kw), None, False
    except ValueError as e:
        return None, str(e), False
    finally:
        shutil.rmtree(proof_dir, ignore_errors=True)


def _tropidist_attempt(path, slug, tlim, root, threads, certify_tropidist):
    """One tropidist attempt: (record, error, killed), in a subprocess or through the stand-in."""
    if certify_tropidist is None:
        return tropidist_in_subprocess(path, slug, tlim, root, threads, tropidist_wall(tlim))
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    try:
        return certify_tropidist(doc, tlim=tlim, slug=slug), None, False
    except (ValueError, RuntimeError) as e:
        return None, str(e), False


def _is_proof_log(cert):
    return (cert is not None and classify(cert) == "exact"
            and (cert.get("verification") or {}).get("level") == "proof_log")


def run_sweep(*, queue, out_dir, attempts_path, tlim, job_seconds, max_entries=0, slugs=None,
              retry=False, certs_dir=CERTS, codes_dir=CODES, certify=None, tools=None,
              backend="sat", tropidist=None, threads=1, certify_tropidist=None, ladder=None):
    """Open entries in queue order until the budget is spent; stage what closes.

    Returns the run manifest, which is also written to <out_dir>/run.json.
    Each entry runs in a subprocess under a wall clock; ``certify`` and
    ``certify_tropidist`` callables (the tests' stand-ins) run in-process
    instead. ``tools`` defaults to verify/sat_certify.py's.

    ``backend`` is one of BACKENDS. "sat" is verify/sat_certify.py with the
    proof path. "tropidist" is research/certs/tropidist_certify.py on the
    checkout ``tropidist`` with ``threads`` threads: solver-level records,
    stabilizer entries admitted. "tropidist+sat" runs the tool first and hands
    a CSS entry it closed to the SAT proof path, filing the proof_log record
    when that finishes and the tool's otherwise; an entry the tool did not
    close is not retried with SAT in the same run, and a tool error falls back
    to SAT.

    ``ladder`` is the SAT path's per-side budget in seconds for the ascending
    ladder (issue #4230); None asks at d - 1 alone. With it, an entry that
    does not close is staged as a partial certificate when it proved d >= 2,
    and a partial certificate on file is reopened at its d_lower and
    replaced only when the run raises the bound.
    """
    if backend not in BACKENDS:
        raise ValueError(f"backend must be one of {BACKENDS}")
    use_tool = "tropidist" in backend
    if use_tool and tropidist is None and certify_tropidist is None:
        raise ValueError("the tropidist backend needs a checkout: --tropidist or TROPIDIST_ROOT")
    if tools is None:
        import sat_certify
        tools = sat_certify.tool_versions
    wall = wall_clock(tlim, ladder)
    date, head, url = utc_today(), git_head(), run_url()
    last = last_attempts(load_jsonl(attempts_path))
    chosen, skipped, reasons = select(queue, last=last, tlim=tlim, today=date, certs_dir=certs_dir,
                                      codes_dir=codes_dir, slugs=slugs, retry=retry, stabilizer_ok=use_tool,
                                      ladder=ladder)
    if max_entries:
        chosen = chosen[:max_entries]
    versions = dict(tools())
    if use_tool and tropidist:
        from tropidist_certify import tropidist_commit
        versions["tropidist"] = tropidist_commit(tropidist)
    manifest = {"date": date, "head": head, "run": url, "tlim": tlim, "wall": wall, "job_seconds": job_seconds,
                "ladder": ladder,
                "queue_date": queue.get("date"), "queue_head": queue.get("head"), "backend": backend,
                "selected": len(chosen), "skipped": dict(skipped), "tools": versions,
                "results": [], "staged": [], "stopped_by_budget": False, "left": 0}
    os.makedirs(os.path.join(out_dir, "certs"), exist_ok=True)
    t_start = time.time()
    for i, row in enumerate(chosen):
        if time.time() - t_start > job_seconds:
            manifest["stopped_by_budget"] = True
            manifest["left"] = len(chosen) - i
            break
        slug = row["slug"]
        path = os.path.join(codes_dir, slug + ".json")
        stab = row.get("code_type") == "stabilizer"
        t0 = time.time()
        cert, error, killed, used, upgrade = None, None, False, "sat", None
        if use_tool:
            used = "tropidist"
            cert, error, killed = _tropidist_attempt(path, slug, tlim, tropidist, threads, certify_tropidist)
        # The SAT path runs alone, after a tool error, on an entry the tool
        # closed (to carry it to proof_log), and, with a ladder, on an entry
        # the tool left open: the ladder's rungs can be proof-checked, which
        # the tool's bound cannot, and a bound at least as high replaces it.
        tool_open = cert is not None and classify(cert) in ("partial", "timeout")
        if backend == "sat" or (backend == "tropidist+sat" and not stab
                                and (error is not None or (cert is not None and classify(cert) == "exact")
                                     or (bool(ladder) and tool_open))):
            sat_cert, sat_error, sat_killed = _sat_attempt(path, slug, tlim, wall, certify, ladder=ladder,
                                                           start=row.get("start", 1))
            if cert is None:
                cert, error, killed, used = sat_cert, sat_error, sat_killed, "sat"
            elif _is_proof_log(sat_cert):
                cert, used, upgrade = sat_cert, "sat", "proof_log"
            elif (tool_open and sat_cert is not None and classify(sat_cert) in ("exact", "partial")
                  and (lower_bound_of(sat_cert) or 1) >= (lower_bound_of(cert) or 1)):
                cert, used, upgrade = sat_cert, "sat", f"ladder over tropidist d >= {lower_bound_of(cert) or 1}"
            else:
                upgrade = "sat " + (classify(sat_cert) if sat_cert is not None
                                    else "killed" if sat_killed else f"error: {sat_error}"[:200])
        att = attempt_row(row, cert, tlim=tlim, date=date, head=head, url=url,
                          secs=time.time() - t0, error=error, killed=killed, backend=used, upgrade=upgrade,
                          ladder=ladder)
        if att["outcome"] == "timeout" and row.get("raise_from"):
            att["note"] = (f"reopened at W = {row['start']}; the ladder did not rise above the filed "
                           f"d >= {row['raise_from'].get('d_lower')}")
        if att["outcome"] in ("exact", "partial"):
            filed = certificate(cert)
            if att["outcome"] == "partial":
                with open(path, encoding="utf-8") as f:
                    filed = partial_certificate(cert, json.load(f))
            old = row.get("raise_from")
            if old:
                filed = raise_certificate(old, filed)
                att["raised"] = {"from": int(old.get("d_lower") or 1), "to": lower_bound_of(filed) or filed["d"]}
                if att["outcome"] == "partial" and att["raised"]["to"] <= att["raised"]["from"]:
                    att["note"] = f"ladder did not rise above the filed d >= {att['raised']['from']}"
                    filed = None
                else:
                    att["d_lower"] = lower_bound_of(filed)
                    att["level"] = filed["verification"]["level"]
            if filed is not None:
                _write_json(os.path.join(out_dir, "certs", slug + ".json"), filed)
                br = batch_row(slug, row["n"], cert)
                if br and filed["verification"].get("level") == "proof_log":
                    append_jsonl(os.path.join(out_dir, "certs", BATCH_LOG), br)
                manifest["staged"].append(slug)
        append_jsonl(attempts_path, att)
        manifest["results"].append(att)
        print(f"{slug}: {att['outcome']}" + (f" d >= {att['d_lower']}" if att.get("d_lower") else "")
              + (f" ({att['level']})" if att.get("level") else "")
              + f" in {att['secs']} s" + (f"; {att['note']}" if att.get("note") else ""), flush=True)
    manifest["opened"] = len(manifest["results"])
    manifest["seconds"] = round(time.time() - t_start, 1)
    manifest["outcomes"] = dict(Counter(r["outcome"] for r in manifest["results"]))
    manifest["skipped_reasons"] = {s: reasons[s] for s in list(reasons)[:200]}
    _write_json(os.path.join(out_dir, "run.json"), manifest)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_markdown(manifest))
    with open(os.path.join(out_dir, "counts.txt"), "w", encoding="utf-8") as f:
        f.write(counts_line(manifest) + "\n")
    return manifest


def counts_line(m):
    """Return the one-line tally the workflow puts in its commit message."""
    o = m.get("outcomes", {})
    return (f"{m.get('opened', 0)} opened, exact {o.get('exact', 0)}, partial {o.get('partial', 0)}, "
            f"timeout {o.get('timeout', 0)}, refuted {o.get('refuted', 0)}, error {o.get('error', 0)}")


def summary_markdown(m):
    o = m.get("outcomes", {})
    lines = [f"## certification sweep of {m['date']}", "",
             f"main at {(m.get('head') or '?')[:12]}, queue of {m.get('queue_date')}, "
             f"{m['tlim']} s per solve under a {m.get('wall')} s wall clock per entry"
             + (f", ladder budget {m['ladder']} s per side" if m.get("ladder") else "")
             + f", job budget {m['job_seconds']} s. "
             f"Opened {m.get('opened', 0)} of {m['selected']} selected entries in {m.get('seconds', 0)} s"
             + (f"; stopped by the budget with {m['left']} left for the next run." if m.get("stopped_by_budget")
                else "."), "",
             f"exact {o.get('exact', 0)}, partial {o.get('partial', 0)}, timeout {o.get('timeout', 0)}, "
             f"refuted {o.get('refuted', 0)}, error {o.get('error', 0)}; skipped " + (", ".join(f"{k} {v}" for k, v in sorted(m["skipped"].items()))
                                                        or "none"), ""]
    staged = [r for r in m["results"] if r["outcome"] == "exact"]
    if staged:
        lines += ["| entry | n | k | d | level | backend | sides |", "|---|---|---|---|---|---|---|"]
        for r in staged:
            lines.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | {r['level']} | "
                         f"{r.get('backend', 'sat')} | {_sides_cell(r['sides'])} |")
        lines.append("")
    partial = [r for r in m["results"] if r["outcome"] == "partial"]
    if partial:
        lines += ["| entry | n | k | d | proved | level | sides |", "|---|---|---|---|---|---|---|"]
        for r in partial:
            lines.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | d >= {r.get('d_lower')} | "
                         f"{r.get('level')} | {_sides_cell(r['sides'])} |")
        lines.append("")
    for outcome in ("refuted", "timeout", "error"):
        rows = [r for r in m["results"] if r["outcome"] == outcome]
        if rows:
            lines.append(f"{outcome}: " + ", ".join(
                r["slug"] + (f" ({r['note']})" if outcome != "timeout" and r.get("note") else "") for r in rows))
            lines.append("")
    return "\n".join(lines)


def _side_cell(s):
    if not s:
        return "?"
    txt = f"{s.get('status')} {s.get('secs')} s"
    if s.get("proof") == "verified":
        txt += f", proof {s.get('proof_secs')} s"
    elif s.get("proof"):
        txt += f", proof: {s['proof']}"
    if s.get("lower_bound") is not None:
        txt += f", d >= {s['lower_bound']}"
    if s.get("rungs"):
        txt += " (" + " ".join(s["rungs"]) + ")"
    return txt


def _sides_cell(sides):
    """One table cell for an entry's sides: X and Z, or the single Pauli side P."""
    return "; ".join(f"{name} {_side_cell(sides.get(name))}" for name in sorted(sides or {}))


def stage(out_dir, *, certs_dir=CERTS):
    """Copy the staged certificates into certs/ and append their batch rows.

    A slug that gained a certificate in the meantime is left alone and
    reported, so a race with another PR never overwrites a filed record.
    Returns (staged slugs, skipped slugs).
    """
    src = os.path.join(out_dir, "certs")
    staged, skipped = [], []
    for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        dst = os.path.join(certs_dir, name)
        if os.path.exists(dst):
            # A partial certificate is replaced only by a higher bound or an
            # exact certificate; anything filed meanwhile that is not below
            # what this run proved is left alone.
            have = _cert_on_file(certs_dir, slug) or {}
            with open(os.path.join(src, name), encoding="utf-8") as f:
                mine = json.load(f)
            better = (not have.get("d_exact") and have.get("d_lower") is not None
                      and (mine.get("d_exact") or (mine.get("d_lower") or 1) > have["d_lower"]))
            if not better:
                skipped.append(slug)
                continue
        shutil.copyfile(os.path.join(src, name), dst)
        staged.append(slug)
    batch = os.path.join(src, BATCH_LOG)
    if os.path.exists(batch):
        for row in load_jsonl(batch):
            if row["slug"] in staged:
                append_jsonl(os.path.join(certs_dir, BATCH_LOG), row)
    with open(os.path.join(out_dir, "staged.json"), "w", encoding="utf-8") as f:
        json.dump({"staged": staged, "skipped": skipped}, f, indent=1)
    return staged, skipped


def staged_slugs(out_dir, sub="certs"):
    """Return what ``stage`` copied once it has run, else what the run left under out_dir."""
    rec = os.path.join(out_dir, "staged.json")
    if os.path.exists(rec):
        with open(rec, encoding="utf-8") as f:
            return sorted(json.load(f)["staged"])
    d = os.path.join(out_dir, sub)
    return sorted(n[:-5] for n in os.listdir(d) if n.endswith(".json")) if os.path.isdir(d) else []


def pr_text(m, staged=None):
    """(title, body) of the certs-only PR for a run manifest."""
    rows = [r for r in m["results"] if r["outcome"] == "exact" and (staged is None or r["slug"] in staged)]
    partial = [r for r in m["results"] if r["outcome"] == "partial" and (staged is None or r["slug"] in staged)]
    n = len(rows)
    date = m["date"]
    noun = "entry" if n == 1 else "entries"
    if rows and partial:
        title = (f"certs: exact distances for {n} {noun} and lower bounds for {len(partial)} from the weekly "
                 f"certification sweep of {date}")
    elif partial:
        title = (f"certs: proven lower bounds for {len(partial)} "
                 f"{'entry' if len(partial) == 1 else 'entries'} from the weekly certification sweep of {date}")
    else:
        title = f"certs: exact distances for {n} {noun} from the weekly certification sweep of {date}"
    levels = Counter(r["level"] for r in rows)
    sat_rows = [r for r in rows if r.get("backend", "sat") == "sat"]
    tool_rows = [r for r in rows if r.get("backend") == "tropidist"]
    solver = [r for r in sat_rows if r["level"] == "solver"]
    tools = m.get("tools") or {}
    run = f" ([run]({m['run']}))" if m.get("run") else ""
    body = [
        (f"Certificates for the {n} board {'entry' if n == 1 else 'entries'} that closed exact"
         + (f" and the {len(partial)} that gained a proven lower bound" if partial else "")
         + f" in the weekly certification sweep of {date}{run}, the head of research/certs/todo.json on that "
         "date (research/certs/certify_sweep.py, issue #4148). Every certified distance equals the distance "
         "the entry already claims on both sides, so no codes/ file changes and the diff is evidence quality "
         "only: these entries move from a witnessed upper bound to the exact tier"
         + (", or from a bare upper bound to a proven interval." if partial else ".")),
        ""]
    if sat_rows:
        body += [
            f"The SAT path is verify/sat_certify.py with --proof at {m['tlim']} s per solve on a GitHub-hosted "
            f"runner, from main at {(m.get('head') or '?')[:12]}. Each side is asked at weight d - 1 twice in the "
            "same process: once in the selector encoding with CryptoMiniSat, and once re-emitted as pure CNF "
            f"(side_cnf, XOR chunk arity 5, no symmetry prefix), refuted by kissat {tools.get('kissat') or '?'}, "
            "and checked by drat-trim. Regenerating every side's formula from the codes/ file on this branch "
            "reproduces the recorded cnf_sha256, which is the check verify/replay_proofs.py makes before it "
            "re-solves. The workflow ran that replay on the quick staged proof_log certificates before opening "
            "this PR.",
            ""]
    if tool_rows:
        stabs = [r for r in tool_rows if "P" in (r.get("sides") or {})]
        body += [
            f"{len(tool_rows)} {'certificate is' if len(tool_rows) == 1 else 'certificates are'} from the "
            f"tropidist backend (research/certs/tropidist_certify.py, issue #4716): github.com/Fanerst/tropidist "
            f"at commit {(tools.get('tropidist') or 'unpinned')[:12]}, the exhaustive distance evaluators of "
            f"arXiv:2611.08247, at {m['tlim']} s per side. Its lower bound is exhaustion inside the tool's kernel "
            "with no replayable artifact, so these records are at the solver level, and the vector it returned "
            "for each side was re-verified with verify/heuristic_distance.py before filing."
            + (f" {len(stabs)} of them {'is a' if len(stabs) == 1 else 'are'} stabilizer "
               f"{'entry' if len(stabs) == 1 else 'entries'}, certified in Pauli weight through the "
               "three-mechanisms-per-qubit encoding that module describes; these are the board's first "
               "stabilizer certificates." if stabs else ""),
            ""]
    body += [
        f"Filed in the #3666 shape: the run's own record with the per-side proof block removed, and for each "
        "proof_log certificate a row in certs/proof_log_batch.jsonl with the clause counts, proof and "
        f"trimmed-core sizes, and solve and check seconds. {levels.get('proof_log', 0)} at proof_log, "
        f"{levels.get('solver', 0)} at solver"
        + (" (CryptoMiniSat closed both sides and the proof path did not finish on at least one side: "
           + ", ".join(r["slug"] for r in solver) + ")" if solver else "") + "."]
    if rows:
        body += ["", "| entry | n | k | d | level | backend | sides |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        body.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | {r['level']} | "
                    f"{r.get('backend', 'sat')} | {_sides_cell(r['sides'])} |")
    if partial:
        raised = [r for r in partial if r.get("raised")]
        body += ["",
                 f"{len(partial)} partial {'certificate' if len(partial) == 1 else 'certificates'} (issue #4230): "
                 f"the ladder asked each side at W = 1, 2, ... with {m.get('ladder')} s per side and did not reach "
                 "d - 1, so the entry keeps its witnessed upper bound and gains the proven lower bound d_lower, "
                 "the largest W + 1 at which both sides returned UNSAT. The board shows these as the interval "
                 "d_lower <= d <= d. Each file is bound to its entry's matrices by verification.checks_sha256, "
                 "so a later correction of the claim keeps the bound; verify/check_certs.py fails if a witness "
                 "ever sits below it."
                 + (f" {len(raised)} of them {'replaces' if len(raised) == 1 else 'replace'} a partial "
                    "certificate already on file, with the old rungs kept ahead of the new ones." if raised else ""),
                 "",
                 "| entry | n | k | d | proved | level | sides |", "|---|---|---|---|---|---|---|"]
        for r in partial:
            body.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | d >= {r.get('d_lower')} | "
                        f"{r.get('level')} | {_sides_cell(r['sides'])} |")
    body += ["",
             "The attempt log research/certs/attempts.jsonl on main records this run's attempts, including the "
             "entries that did not close in budget.",
             "",
             "Opened by the certify-weekly workflow. A pull request opened with the Actions token gets no "
             "pull_request runs, so close and reopen it, or push an empty commit, to run verify.yml's "
             "certificate checks and the proof replay here. The workflow ran both on this branch before opening "
             "it, and its run summary has the output."]
    return title, "\n".join(body) + "\n"


def refutation_text(m):
    """(title, body) of the issue a refutation opens, or None when there is none."""
    rows = [r for r in m["results"] if r["outcome"] == "refuted"]
    if not rows:
        return None
    n = len(rows)
    title = f"Certification sweep of {m['date']}: {n} {'entry' if n == 1 else 'entries'} refuted at d - 1"
    body = [f"The weekly certification sweep of {m['date']}" + (f" ([run]({m['run']}))" if m.get("run") else "")
            + " asked each side of these entries for a logical of weight at most d - 1 and found one. Each witness "
            "is in research/certs/attempts.jsonl under the entry's row; nothing was staged for them. The claim "
            "needs a refutation PR (the distance block tightened to the witness, verify/check_authorship.py's "
            "refutation binding), and the sweep will not reopen an entry it refuted.", ""]
    for r in rows:
        wit = r.get("witness") or {}
        body.append(f"- {r['slug']} ([[{r['n']},{r['k']},{r['d']}]]): " + ", ".join(
            f"side {s} has a logical of weight {len(w)}" for s, w in wit.items()))
    return title, "\n".join(body) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="work the head of the queue")
    r.add_argument("--out-dir", default=OUT_DIR)
    r.add_argument("--attempts", default=ATTEMPTS)
    r.add_argument("--queue", default=TODO)
    r.add_argument("--tlim", type=int, default=600, help="seconds per solve (default 600)")
    r.add_argument("--job-seconds", type=float, default=4 * 3600,
                   help="stop opening entries after this long (default 14400)")
    r.add_argument("--max-entries", type=int, default=0, help="open at most this many (0: no cap)")
    r.add_argument("--slugs", nargs="*", default=None, help="try these instead of the queue head")
    r.add_argument("--retry", action="store_true", help="reopen entries that timed out at this budget")
    r.add_argument("--backend", choices=BACKENDS, default="sat",
                   help="sat (default), tropidist, or tropidist+sat (the tool first, then the SAT proof path "
                        "on what it closed)")
    r.add_argument("--tropidist", default=os.environ.get("TROPIDIST_ROOT"),
                   help="the tropidist checkout (default: $TROPIDIST_ROOT)")
    r.add_argument("--threads", type=int, default=1, help="threads per tropidist run (default 1)")
    r.add_argument("--ladder", type=float, default=None, metavar="SECONDS",
                   help="ask W = 1, 2, ... up to d - 1 with this many seconds per side, and stage what it "
                        "proves below the claim as a partial certificate (issue #4230)")
    s = sub.add_parser("stage", help="copy the staged certificates into certs/")
    s.add_argument("--out-dir", default=OUT_DIR)
    p = sub.add_parser("pr-body", help="write the certs-only PR body; prints its title")
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--out", required=True)
    i = sub.add_parser("issue", help="write the refutation issue body; prints its title, or nothing")
    i.add_argument("--out-dir", default=OUT_DIR)
    i.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        m = run_sweep(queue=load_queue(a.queue), out_dir=a.out_dir, attempts_path=a.attempts, tlim=a.tlim,
                      job_seconds=a.job_seconds, max_entries=a.max_entries, slugs=a.slugs, retry=a.retry,
                      ladder=a.ladder or None,
                      backend=a.backend, tropidist=a.tropidist, threads=a.threads)
        o = m["outcomes"]
        print(f"opened {m['opened']} of {m['selected']}: exact {o.get('exact', 0)}, partial "
              f"{o.get('partial', 0)} (staged under {os.path.relpath(a.out_dir, ROOT)}), timeout "
              f"{o.get('timeout', 0)}, refuted "
              f"{o.get('refuted', 0)}, error {o.get('error', 0)}, left {m['left']}")
        return EXIT_REFUTED if o.get("refuted") else 0
    if a.cmd == "stage":
        staged, skipped = stage(a.out_dir)
        print("staged: " + (" ".join(staged) or "nothing"))
        if skipped:
            print("already certified, left alone: " + " ".join(skipped))
        return 0
    with open(os.path.join(a.out_dir, "run.json"), encoding="utf-8") as f:
        m = json.load(f)
    if a.cmd == "pr-body":
        title, body = pr_text(m, staged=staged_slugs(a.out_dir))
    else:
        got = refutation_text(m)
        if got is None:
            return 0
        title, body = got
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(body)
    print(title)
    return 0


if __name__ == "__main__":
    sys.exit(main())

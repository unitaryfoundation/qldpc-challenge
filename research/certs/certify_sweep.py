#!/usr/bin/env python3
"""Work the cheap head of the certification queue and stage what closes (issue #4148).

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

    uv run --extra research python research/certs/certify_sweep.py run --tlim 600 --job-seconds 14400
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
OUTCOMES = ("exact", "timeout", "refuted", "error")
EXIT_REFUTED = 3
SAT_CERTIFY = os.path.join(ROOT, "verify", "sat_certify.py")
WALL_FLOOR = 300


def wall_clock(tlim):
    """Return the hard per-entry limit: six solves of tlim (two per side, three tools) plus setup."""
    return 6 * tlim + WALL_FLOOR


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


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
    sides = {s: {"value": dist[s]["value"]} for s in ("X", "Z") if isinstance(dist.get(s), dict)}
    return {"slug": slug, "code_type": doc.get("code_type", "CSS"), "n": doc["n"], "k": doc["k"],
            "d": dist["d"], "sides": sides, "band": None, "position": None, "record": None}


def select(queue, *, last, tlim, certs_dir=CERTS, codes_dir=CODES, slugs=None, retry=False):
    """Return the entries the sweep opens, in queue order, and why it passes over the rest.

    Skipped: stabilizer entries (no certifier), entries that have a
    certificate file already, entries whose side values differ from d (a
    certificate at d would not be honored), entries not on the board, an
    entry a previous attempt refuted, an entry a previous attempt certified
    whose PR has not landed, and, unless ``retry``, an entry that timed out or
    errored at this time limit or a longer one. Naming ``slugs`` lifts the
    attempt-based skips for those slugs and admits slugs outside the queue.
    The first four skips hold either way: a certificate at d would change
    nothing for those entries.
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
        if r.get("code_type") != "CSS":
            skip(slug, "stabilizer", "stabilizer entry: no Pauli-weight certifier yet")
            continue
        if not os.path.exists(os.path.join(codes_dir, slug + ".json")):
            skip(slug, "not_on_board", "no codes/ file: the queue is older than the board")
            continue
        if os.path.exists(os.path.join(certs_dir, slug + ".json")):
            skip(slug, "certified", "certs/ already has a file for it")
            continue
        values = {s: v.get("value") for s, v in (r.get("sides") or {}).items()}
        if len(values) != 2 or any(v != r["d"] for v in values.values()):
            skip(slug, "side_mismatch",
                 f"side values {values} differ from d = {r['d']}; a certificate at d would not be honored")
            continue
        prev = last.get(slug) if not slugs else None
        if prev and prev.get("outcome") == "refuted":
            skip(slug, "refuted", f"refuted on {prev.get('date')}; the entry's claim has to change first")
            continue
        if prev and prev.get("outcome") == "exact":
            skip(slug, "awaiting_pr", f"certified on {prev.get('date')}; its certificate has not landed")
            continue
        if (prev and not retry and prev.get("outcome") in ("timeout", "error")
                and (prev.get("tlim") or 0) >= tlim):
            skip(slug, "attempted", f"{prev.get('outcome')} at {prev.get('tlim')} s per solve on {prev.get('date')}")
            continue
        chosen.append(r)
    return chosen, skipped, reasons


def classify(cert):
    """exact, refuted, or timeout, from the certifier's record."""
    if cert.get("d_exact"):
        return "exact"
    statuses = {b.get("status") for b in (cert.get("sides") or {}).values()}
    if "SAT" in statuses:
        return "refuted"
    return "timeout"


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
    return out


def certify_in_subprocess(path, slug, tlim, proof_dir, wall, script=None):
    """Run verify/sat_certify.py on one entry under a hard wall clock.

    Returns (record, error, killed): the certifier's JSON record, or the
    error it printed, or killed=True when the wall clock ended it. The
    subprocess gets its own session so the kill reaches kissat and drat-trim
    as well as the Python parent.
    """
    cmd = [sys.executable, script or SAT_CERTIFY, path, "--proof", proof_dir, "--tlim", str(int(tlim)), "--json"]
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


def attempt_row(row, cert, *, tlim, date, head, url, secs, error=None, killed=False):
    """One line of attempts.jsonl."""
    out = {"date": date, "head": head, "run": url, "slug": row["slug"], "n": row["n"], "k": row["k"],
           "d": row["d"], "band": row.get("band"), "position": row.get("position"), "tlim": tlim,
           "secs": round(secs, 1)}
    if killed:
        out.update(outcome="timeout", level=None, sides={},
                   note=f"killed at the {wall_clock(tlim)} s wall clock; the solver's own limit did not hold")
        return out
    if error is not None:
        out.update(outcome="error", level=None, sides={}, note=error[:500])
        return out
    outcome = classify(cert)
    out["outcome"] = outcome
    out["level"] = (cert.get("verification") or {}).get("level") if outcome == "exact" else None
    out["sides"] = {s: _side_summary(b) for s, b in cert["sides"].items()}
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


def run_sweep(*, queue, out_dir, attempts_path, tlim, job_seconds, max_entries=0, slugs=None,
              retry=False, certs_dir=CERTS, codes_dir=CODES, certify=None, tools=None):
    """Open entries in queue order until the budget is spent; stage what closes.

    Returns the run manifest, which is also written to <out_dir>/run.json.
    Each entry runs in a subprocess under ``wall_clock(tlim)``; a ``certify``
    callable (the tests' stand-in) runs in-process instead. ``tools`` defaults
    to verify/sat_certify.py's.
    """
    if tools is None:
        import sat_certify
        tools = sat_certify.tool_versions
    wall = wall_clock(tlim)
    date, head, url = utc_today(), git_head(), run_url()
    last = last_attempts(load_jsonl(attempts_path))
    chosen, skipped, reasons = select(queue, last=last, tlim=tlim, certs_dir=certs_dir,
                                      codes_dir=codes_dir, slugs=slugs, retry=retry)
    if max_entries:
        chosen = chosen[:max_entries]
    manifest = {"date": date, "head": head, "run": url, "tlim": tlim, "wall": wall, "job_seconds": job_seconds,
                "queue_date": queue.get("date"), "queue_head": queue.get("head"),
                "selected": len(chosen), "skipped": dict(skipped), "tools": tools(),
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
        proof_dir = tempfile.mkdtemp(prefix=f"certify-{slug}-")
        t0 = time.time()
        cert, error, killed = None, None, False
        try:
            if certify is None:
                cert, error, killed = certify_in_subprocess(path, slug, tlim, proof_dir, wall)
            else:
                with open(path, encoding="utf-8") as f:
                    doc = json.load(f)
                cert = certify(doc, tlim=tlim, proof_dir=proof_dir, slug=slug)
        except ValueError as e:
            error = str(e)
        finally:
            shutil.rmtree(proof_dir, ignore_errors=True)
        att = attempt_row(row, cert, tlim=tlim, date=date, head=head, url=url,
                          secs=time.time() - t0, error=error, killed=killed)
        if att["outcome"] == "exact":
            _write_json(os.path.join(out_dir, "certs", slug + ".json"), certificate(cert))
            br = batch_row(slug, row["n"], cert)
            if br:
                append_jsonl(os.path.join(out_dir, "certs", BATCH_LOG), br)
            manifest["staged"].append(slug)
        append_jsonl(attempts_path, att)
        manifest["results"].append(att)
        print(f"{slug}: {att['outcome']}" + (f" ({att['level']})" if att.get("level") else "")
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
    return (f"{m.get('opened', 0)} opened, exact {o.get('exact', 0)}, timeout {o.get('timeout', 0)}, "
            f"refuted {o.get('refuted', 0)}, error {o.get('error', 0)}")


def summary_markdown(m):
    o = m.get("outcomes", {})
    lines = [f"## certification sweep of {m['date']}", "",
             f"main at {(m.get('head') or '?')[:12]}, queue of {m.get('queue_date')}, "
             f"{m['tlim']} s per solve under a {m.get('wall')} s wall clock per entry, job budget "
             f"{m['job_seconds']} s. "
             f"Opened {m.get('opened', 0)} of {m['selected']} selected entries in {m.get('seconds', 0)} s"
             + (f"; stopped by the budget with {m['left']} left for the next run." if m.get("stopped_by_budget")
                else "."), "",
             f"exact {o.get('exact', 0)}, timeout {o.get('timeout', 0)}, refuted {o.get('refuted', 0)}, "
             f"error {o.get('error', 0)}; skipped " + (", ".join(f"{k} {v}" for k, v in sorted(m["skipped"].items()))
                                                        or "none"), ""]
    staged = [r for r in m["results"] if r["outcome"] == "exact"]
    if staged:
        lines += ["| entry | n | k | d | level | X | Z |", "|---|---|---|---|---|---|---|"]
        for r in staged:
            lines.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | {r['level']} | "
                         f"{_side_cell(r['sides'].get('X'))} | {_side_cell(r['sides'].get('Z'))} |")
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
    return txt


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
            skipped.append(slug)
            continue
        shutil.copyfile(os.path.join(src, name), dst)
        staged.append(slug)
    batch = os.path.join(src, BATCH_LOG)
    if os.path.exists(batch):
        for row in load_jsonl(batch):
            if row["slug"] in staged:
                append_jsonl(os.path.join(certs_dir, BATCH_LOG), row)
    return staged, skipped


def pr_text(m, staged=None):
    """(title, body) of the certs-only PR for a run manifest."""
    rows = [r for r in m["results"] if r["outcome"] == "exact" and (staged is None or r["slug"] in staged)]
    n = len(rows)
    date = m["date"]
    noun = "entry" if n == 1 else "entries"
    title = f"certs: exact distances for {n} {noun} from the weekly certification sweep of {date}"
    levels = Counter(r["level"] for r in rows)
    solver = [r for r in rows if r["level"] == "solver"]
    tools = m.get("tools") or {}
    run = f" ([run]({m['run']}))" if m.get("run") else ""
    body = [
        f"Certificates for the {n} board {'entry' if n == 1 else 'entries'} that closed exact in the weekly "
        f"certification sweep of {date}{run}, the head of research/certs/todo.json on that date "
        "(research/certs/certify_sweep.py, issue #4148). Every certified distance equals the distance the "
        "entry already claims on both sides, so no codes/ file changes and the diff is evidence quality only: "
        "these entries move from a witnessed upper bound to the exact tier.",
        "",
        f"The run is verify/sat_certify.py with --proof at {m['tlim']} s per solve on a GitHub-hosted runner, "
        f"from main at {(m.get('head') or '?')[:12]}. Each side is asked at weight d - 1 twice in the same "
        "process: once in the selector encoding with CryptoMiniSat, and once re-emitted as pure CNF (side_cnf, "
        f"XOR chunk arity 5, no symmetry prefix), refuted by kissat {tools.get('kissat') or '?'}, and checked "
        "by drat-trim. Regenerating every side's formula from the codes/ file on this branch reproduces the "
        "recorded cnf_sha256, which is the check verify/replay_proofs.py makes before it re-solves. The workflow "
        "ran that replay on the quick staged proof_log certificates before opening this PR.",
        "",
        f"Filed in the #3666 shape: the run's own record with the per-side proof block removed, and for each "
        "proof_log certificate a row in certs/proof_log_batch.jsonl with the clause counts, proof and "
        f"trimmed-core sizes, and solve and check seconds. {levels.get('proof_log', 0)} at proof_log, "
        f"{levels.get('solver', 0)} at solver"
        + (" (CryptoMiniSat closed both sides and the proof path did not finish on at least one side: "
           + ", ".join(r["slug"] for r in solver) + ")" if solver else "") + ".",
        "",
        "| entry | n | k | d | level | X | Z |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        body.append(f"| {r['slug']} | {r['n']} | {r['k']} | {r['d']} | {r['level']} | "
                    f"{_side_cell(r['sides'].get('X'))} | {_side_cell(r['sides'].get('Z'))} |")
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
                      job_seconds=a.job_seconds, max_entries=a.max_entries, slugs=a.slugs, retry=a.retry)
        o = m["outcomes"]
        print(f"opened {m['opened']} of {m['selected']}: exact {o.get('exact', 0)} (staged under "
              f"{os.path.relpath(a.out_dir, ROOT)}), timeout {o.get('timeout', 0)}, refuted "
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
        staged = sorted(os.path.splitext(n)[0] for n in os.listdir(os.path.join(a.out_dir, "certs"))
                        if n.endswith(".json"))
        title, body = pr_text(m, staged=staged)
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

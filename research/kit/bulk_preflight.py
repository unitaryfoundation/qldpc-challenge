"""Preflight a batch of staged candidates: duplicates, the gate, the batch frontier, one report.

    uv run --extra research python research/kit/bulk_preflight.py <candidate.json>... [--dir DIR]
        [--json FILE] [--peer-audits DIR] [--no-gate] [--allow-python-gate]

Issue #7450. A contributor triaging several staged candidates ran the duplicate
collapse, the gate, and the frontier reading separately and reconciled them by
hand. This runs them in order on the whole batch and says, per candidate, what
stands between it and a PR. The candidates are the documents
``kit/submit.save_submission`` writes; nothing here promotes, commits, or posts.

In order:

1. The accelerator. ``verify/gate_changed.py`` degrades to its Python passes when
   ``verify/gf2_fast`` is not importable, which is how #5094 came to be refuted
   in CI, and a fresh sparse worktree has no built accelerator. A batch run is
   where a silently shallow gate costs the most, so it refuses to gate without
   the module unless ``--allow-python-gate`` says the shallow pass is wanted.
2. Duplicates inside the batch: the (n, k, d, max check weight) point, and for
   stabilizer documents the row space of the presentation (the rule of
   ``kit/dedup_submissions.py``). Two candidates at one point are one PR at most.
3. The gate, through ``coordination.gate_and_record`` (the prescreen first, the
   verdict written beside the file, the one board-independent step cached by
   digest so a rerun is cheap). ``--no-gate`` reads the verdicts already beside
   the files instead and marks the rest ``ungated``.
4. The reading: the verdict's ``gates.novelty`` and ``gates.dedup`` blocks, the
   batch's own dominance (``kit/frontier.within_batch``: a candidate another
   survivor of the batch dominates cannot keep its frontier claim), and, for a
   gain that is on d alone, the matched-depth peer audit ``kit/peer_audit``
   requires, read from ``<stem>.peer-audit.json`` beside the candidate or
   ``audits/peer-audit-<slug>.json`` next to it (``--peer-audits`` names another
   directory).

One line per candidate, then the counts. Statuses, most to least settled:

    blocked          the prescreen or the gate refused it
    duplicate        the gate found an exact or Weisfeiler-Leman duplicate on the
                     board, or an earlier candidate of the batch sits at its point
    dominated        passed, but a board entry dominates it: a non-frontier result,
                     filed only with --allow-non-frontier, never as a frontier code
    batch-dominated  passed, but another candidate of the batch dominates it
    needs-audit      passed and board-advancing, but the gain over a board entry is
                     on d alone and no credible matched-depth audit is on record
    tie              passed and board-advancing with an empty advances_by: a frontier
                     tie that beats no entry; the motto admits it, at low value
    ready            passed, board-advancing, undominated in the batch, audits in order
    ungated          --no-gate and no verdict beside the file

Exit status 1 when any candidate is blocked, else 0. The next step for a ready
candidate is ``kit/promote.py`` or ``./qldpc submit``; after promotion,
``./qldpc preflight --body-file <body.md>`` runs the scope, ruff, family-tag,
board-test, and prose checks on the promoted files.
"""

import argparse
import datetime
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import coordination  # noqa: E402
import dedup_submissions  # noqa: E402
import frontier  # noqa: E402
import peer_audit  # noqa: E402

STATUSES = ("blocked", "duplicate", "dominated", "batch-dominated", "needs-audit", "tie", "ready", "ungated")

_WEIGHT_CLASS = (("weight-4", 4), ("weight-6", 6), ("weight-8", 8))


def accelerator_available():
    """Return True when the gate's C++ accelerator imports from verify/."""
    try:
        import gf2_fast  # noqa: F401
    except ImportError:
        return False
    return True


def candidate_files(files, directory=None):
    """Return the candidate paths: the arguments plus ``*.json`` under ``directory``, no verdicts or reports."""
    out = list(files or [])
    if directory:
        out += sorted(glob.glob(os.path.join(directory, "*.json")))
    seen, kept = set(), []
    for f in out:
        base = os.path.basename(f)
        if base.endswith((".verdict.json", ".preflight.json", ".recipe.json", ".peer-audit.json", ".exact_first.json")):
            continue
        key = os.path.abspath(f)
        if key not in seen:
            seen.add(key)
            kept.append(f)
    return kept


def weight_class(w):
    """Return the board's weight class for a max check weight (``verify/validate_candidate.py``'s bands)."""
    for name, cap in _WEIGHT_CLASS:
        if w <= cap:
            return name
    return "weight-9plus"


def code_axes(doc):
    """Return ``(n, k, d, w)`` for a candidate document, ``w`` None when it has no checks."""
    n, k, d = int(doc["n"]), int(doc["k"]), int(doc["distance"]["d"])
    checks = doc.get("checks") or {}
    if "S" in checks:
        w = max(len(set(s.get("X", [])) | set(s.get("Z", []))) for s in checks["S"])
    elif "X" in checks:
        w = max({*(len(r) for r in checks["X"]), *(len(r) for r in checks["Z"])})
    else:
        w = None
    return n, k, d, (int(w) if w is not None else None)


def slug_of(doc):
    """Return the board slug ``n-k-d`` a candidate would take."""
    n, k, d, _ = code_axes(doc)
    return f"{n}-{k}-{d}"


def frontier_row(doc, verdict, path):
    """Return the candidate as a row ``kit/frontier`` compares: axes, classes, and a name."""
    n, k, d, w = code_axes(doc)
    cell = ((verdict or {}).get("gates") or {}).get("novelty", {}).get("cell") or []
    weight = cell[0] if len(cell) == 2 else weight_class(w if w is not None else 10**6)
    # without a verdict the locality class is unknown; unrestricted is the class
    # every entry competes in, so it can only add dominators, never hide one
    locality = cell[1] if len(cell) == 2 else "unrestricted"
    return {
        "n": n,
        "k": k,
        "d": d,
        "w": w,
        "code_type": "stabilizer" if "S" in (doc.get("checks") or {}) else "CSS",
        "weight_class": weight,
        "locality_class": locality,
        "slug": os.path.basename(path)[:-5],
    }


def batch_duplicates(docs):
    """Return ``{index: index_of_first}`` for every candidate that repeats an earlier one's point or presentation."""
    first_at_point, first_at_canon, out = {}, {}, {}
    for i, doc in enumerate(docs):
        point = code_axes(doc)
        if point in first_at_point:
            out[i] = first_at_point[point]
            continue
        first_at_point[point] = i
        canon = dedup_submissions.canon(doc) if doc.get("code_type") == "stabilizer" else None
        if canon is not None:
            if canon in first_at_canon:
                out[i] = first_at_canon[canon]
                continue
            first_at_canon[canon] = i
    return out


def peer_audit_path(path, slug, directory=None):
    """Return the peer-audit record for the candidate at ``path``, or None when none is on disk."""
    stem = path[:-5] if path.endswith(".json") else path
    here = os.path.dirname(os.path.abspath(path))
    options = [f"{stem}.peer-audit.json", os.path.join(here, "audits", f"peer-audit-{slug}.json")]
    if directory:
        options.insert(0, os.path.join(directory, f"peer-audit-{slug}.json"))
    for p in options:
        if os.path.isfile(p):
            return p
    return None


def required_trials(doc):
    """Return the deepest search the claim rests on, from the sides' witness provenance, or None."""
    depths = []
    for side in ("X", "Z", "P"):
        blk = (doc.get("distance") or {}).get(side)
        prov = blk.get("witness_provenance") if isinstance(blk, dict) else None
        if isinstance(prov, dict):
            for key in ("survived_samples", "found_at_samples"):
                v = prov.get(key)
                if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                    depths.append(v)
    return max(depths) if depths else None


def gate_one(path, *, seed=None):
    """Run the gate on one candidate and return ``(verdict, verdict_path, preflight_report)``.

    A document the prescreen refuses yields ``(None, None, report)``; the report
    is already written beside the candidate by ``coordination``.
    """
    try:
        verdict, out = coordination.gate_and_record(path, seed=seed)
    except coordination.PreflightFailure as e:
        return None, None, e.result
    return verdict, out, None


def read_verdict(path):
    """Return the verdict already beside the candidate, or None."""
    vp = coordination.verdict_path(path)
    try:
        with open(vp, encoding="utf-8") as fh:
            return json.load(fh), vp
    except (OSError, ValueError):
        return None, None


def classify(entries, *, peer_audit_dir=None):
    """Fill in ``status`` and ``reasons`` for every entry of the batch.

    ``entries`` are the dicts :func:`preflight` builds, each with ``path``,
    ``doc``, ``verdict`` (or None), ``preflight`` (a failed prescreen report or
    None), and ``gated`` (whether the gate was asked this run). Duplicates and
    the batch frontier are decided across the batch; everything else per entry.
    """
    docs = [e["doc"] for e in entries]
    dups = batch_duplicates(docs)
    for i, e in enumerate(entries):
        e["duplicate_of"] = entries[dups[i]]["path"] if i in dups else None

    # the batch frontier is over the candidates that passed the gate and are
    # not themselves repeats: a blocked document is not a submission
    passed_idx = [i for i, e in enumerate(entries) if (e["verdict"] or {}).get("passed") and i not in dups]
    rows = [frontier_row(entries[i]["doc"], entries[i]["verdict"], entries[i]["path"]) for i in passed_idx]
    inside = frontier.within_batch(rows)
    for pos, i in enumerate(passed_idx):
        entries[i]["batch_dominated_by"] = inside.get(pos, [])
    for e in entries:
        e.setdefault("batch_dominated_by", [])

    for i, e in enumerate(entries):
        reasons = []
        verdict = e["verdict"]
        if e["preflight"] is not None:
            failed = [c for c, ok in (e["preflight"].get("checks") or {}).items() if not ok] or ["prescreen"]
            e["status"] = "blocked"
            e["reasons"] = [f"the prescreen refused the document: {', '.join(failed)}"]
            continue
        if verdict is None:
            e["status"] = "ungated"
            e["reasons"] = ["no verdict beside the file; run without --no-gate"]
            continue
        gates = verdict.get("gates") or {}
        novelty = gates.get("novelty") or {}
        dedup = gates.get("dedup") or {}
        if not verdict.get("passed"):
            failed = [name for name, g in gates.items() if isinstance(g, dict) and g.get("ok") is False]
            e["status"] = "blocked"
            e["reasons"] = [f"the gate refused it: {', '.join(failed) or 'see the verdict'}"]
            continue
        if dedup.get("exact_duplicate_of") or dedup.get("wl_equivalent_of"):
            peer = dedup.get("exact_duplicate_of") or dedup.get("wl_equivalent_of")
            kind = "an exact duplicate of" if dedup.get("exact_duplicate_of") else "Weisfeiler-Leman equivalent to"
            e["status"] = "duplicate"
            e["reasons"] = [f"{kind} board entry {peer}"]
            continue
        if e["duplicate_of"]:
            e["status"] = "duplicate"
            e["reasons"] = [f"same point or presentation as {e['duplicate_of']} earlier in the batch; one PR per point"]
            continue
        blockers = frontier.blockers(novelty.get("dominated_by"), novelty.get("board_advancing"))
        if blockers:
            e["status"] = "dominated"
            e["reasons"] = blockers
            continue
        if e["batch_dominated_by"]:
            e["status"] = "batch-dominated"
            e["reasons"] = [f"dominated within the batch by {', '.join(e['batch_dominated_by'])}"]
            continue
        peers = novelty.get("d_only_peers") or []
        if peers:
            slug = slug_of(e["doc"])
            ap = peer_audit_path(e["path"], slug, peer_audit_dir)
            audit = None
            if ap:
                try:
                    audit = peer_audit.load_audit(ap)
                except peer_audit.PeerAuditError as err:
                    reasons.append(str(err))
            e["peer_audit"] = ap
            problems = peer_audit.blockers(
                peers, audit, required_trials=required_trials(e["doc"]), candidate_path=e["path"]
            )
            if problems or reasons:
                e["status"] = "needs-audit"
                e["reasons"] = reasons + problems
                continue
            reasons.append(f"d-only gain over {', '.join(peers)} discharged by {ap}")
        if not novelty.get("advances_by"):
            e["status"] = "tie"
            e["reasons"] = reasons + ["board-advancing with an empty advances_by: a frontier tie that beats no entry"]
            continue
        e["status"] = "ready"
        e["reasons"] = reasons + [f"advances its cell on {', '.join(novelty['advances_by'])}"]
    return entries


def preflight(paths, *, gate=True, seed=None, peer_audit_dir=None, gate_fn=None):
    """Return the classified batch: one entry per candidate path."""
    gate_fn = gate_fn or gate_one
    entries = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        entry = {"path": path, "doc": doc, "verdict": None, "verdict_path": None, "preflight": None, "gated": gate}
        if gate:
            verdict, vp, report = gate_fn(path, seed=seed)
            entry.update(verdict=verdict, verdict_path=vp, preflight=report)
        else:
            verdict, vp = read_verdict(path)
            entry.update(verdict=verdict, verdict_path=vp)
        entries.append(entry)
    return classify(entries, peer_audit_dir=peer_audit_dir)


def report_record(entries, *, accelerator):
    """Return the JSON record for ``--json``: per-candidate facts without the documents."""
    rows = []
    for e in entries:
        novelty = ((e["verdict"] or {}).get("gates") or {}).get("novelty") or {}
        n, k, d, w = code_axes(e["doc"])
        rows.append(
            {
                "path": e["path"],
                "slug": slug_of(e["doc"]),
                "n": n,
                "k": k,
                "d": d,
                "w": w,
                "cell": novelty.get("cell"),
                "status": e["status"],
                "reasons": e["reasons"],
                "verdict_path": e["verdict_path"],
                "passed": (e["verdict"] or {}).get("passed"),
                "board_advancing": novelty.get("board_advancing"),
                "advances_by": novelty.get("advances_by"),
                "dominated_by": novelty.get("dominated_by"),
                "d_only_peers": novelty.get("d_only_peers"),
                "batch_dominated_by": e.get("batch_dominated_by") or [],
                "duplicate_of": e.get("duplicate_of"),
                "peer_audit": e.get("peer_audit"),
            }
        )
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    return {
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "run_id": coordination.run_id(),
        "accelerator": accelerator,
        "candidates": rows,
        "counts": {s: c for s, c in counts.items() if c},
    }


def print_report(record, out=None):
    """Print one line per candidate and the counts."""
    out = out or sys.stdout
    width = max((len(r["slug"]) for r in record["candidates"]), default=4)
    for r in record["candidates"]:
        cell = "~".join(r["cell"]) if r["cell"] else "-"
        w = r["w"] if r["w"] is not None else "?"
        first = r["reasons"][0] if r["reasons"] else ""
        print(f"{r['status']:15} {r['slug']:{width}} w={w:<3} {cell:28} {first}", file=out)
        for extra in r["reasons"][1:]:
            print(f"{'':15} {'':{width}}      {extra}", file=out)
    counts = ", ".join(f"{c} {s}" for s, c in record["counts"].items())
    print(f"{len(record['candidates'])} candidates: {counts}", file=out)
    if not record["accelerator"]:
        print(
            "note: the gate ran without verify/gf2_fast (--allow-python-gate); its refutation pass was the shallow one",
            file=out,
        )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*", help="staged candidate documents")
    ap.add_argument("--dir", help="also every *.json candidate in this directory")
    ap.add_argument("--json", metavar="FILE", help="write the record here as well")
    ap.add_argument("--peer-audits", metavar="DIR", help="directory of peer-audit-<slug>.json records")
    ap.add_argument("--seed", type=int, default=None, help="gate seed (default: the gate's own)")
    ap.add_argument(
        "--no-gate", action="store_true", help="read the verdicts beside the files instead of running the gate"
    )
    ap.add_argument(
        "--allow-python-gate",
        action="store_true",
        help="gate without verify/gf2_fast, knowing the refutation pass is then the shallow Python one",
    )
    a = ap.parse_args(argv)
    paths = candidate_files(a.files, a.dir)
    if not paths:
        print("no candidate files given", file=sys.stderr)
        return 2
    accelerator = accelerator_available()
    if not a.no_gate and not accelerator and not a.allow_python_gate:
        print(
            "verify/gf2_fast is not importable, so the gate would run its shallow Python passes "
            "(verify/gate_changed.py degrades without the accelerator; AGENTS.md, Worktrees). Build it "
            "with `make fast` or copy verify/gf2_fast.cpython-*.so from a checkout that has it; "
            "--allow-python-gate runs the shallow gate knowingly.",
            file=sys.stderr,
        )
        return 2
    entries = preflight(paths, gate=not a.no_gate, seed=a.seed, peer_audit_dir=a.peer_audits)
    record = report_record(entries, accelerator=accelerator or a.no_gate)
    print_report(record)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(record, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"record written to {a.json}", file=sys.stderr)
    return 1 if record["counts"].get("blocked") else 0


if __name__ == "__main__":
    sys.exit(main())

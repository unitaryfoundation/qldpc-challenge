"""The certification sweep opens the queue head it can use, files what closes, and never guesses.

Selection skips what a certificate at d cannot help (stabilizer entries, side
values that differ from d), what is already filed, and what an earlier attempt
settled at this budget. A closed record is filed in the #3666 shape: the proof
block stripped, a batch row for a proof_log certificate. A refuted side is a
refutation, not a certificate (issue #4148).
"""
import importlib.util
import json
import os
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))


def _script():
    spec = importlib.util.spec_from_file_location("certify_sweep_script", os.path.join(_HERE, "certify_sweep.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(slug, n=12, d=2, code_type="CSS", x=None, z=None, band="A", position=1):
    return {"slug": slug, "code_type": code_type, "n": n, "k": 2, "d": d, "band": band, "position": position,
            "record": True, "sides": {"X": {"value": d if x is None else x}, "Z": {"value": d if z is None else z}}
            if code_type == "CSS" else {"P": {"value": d}}}


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def test_selection_skips_what_the_sweep_cannot_use(tmp_path):
    S = _script()
    codes, certs = str(tmp_path / "codes"), str(tmp_path / "certs")
    for slug in ("plain", "filed", "mismatch", "timed", "errored", "refuted", "landed", "stab", "short"):
        _write(os.path.join(codes, slug + ".json"), {"n": 12})
    _write(os.path.join(certs, "filed.json"), {"d_exact": True})
    queue = {"entries": [_row("stab", code_type="stabilizer"), _row("filed"), _row("mismatch", x=3),
                         _row("timed"), _row("errored"), _row("refuted"), _row("landed"), _row("gone"),
                         _row("short"), _row("plain")]}
    last = {"timed": {"outcome": "timeout", "tlim": 600, "date": "2026-10-20"},
            "errored": {"outcome": "error", "tlim": 900, "date": "2026-10-20"},
            "refuted": {"outcome": "refuted", "tlim": 600, "date": "2026-10-20"},
            "landed": {"outcome": "exact", "tlim": 600, "date": "2026-10-20"},
            "short": {"outcome": "timeout", "tlim": 60, "date": "2026-10-20"}}
    chosen, skipped, reasons = S.select(queue, last=last, tlim=600, certs_dir=certs, codes_dir=codes)
    assert [r["slug"] for r in chosen] == ["short", "plain"], "an older, shorter attempt does not block a longer one"
    assert skipped == {"stabilizer": 1, "certified": 1, "side_mismatch": 1, "attempted": 2, "refuted": 1,
                       "awaiting_pr": 1, "not_on_board": 1}
    assert "differ from d" in reasons["mismatch"] and "timeout at 600" in reasons["timed"]
    # --retry reopens what timed out or errored, never what was refuted or already certified
    chosen, skipped, _ = S.select(queue, last=last, tlim=600, certs_dir=certs, codes_dir=codes, retry=True)
    assert [r["slug"] for r in chosen] == ["timed", "errored", "short", "plain"]
    # a longer budget reopens a shorter attempt on its own
    chosen, _, _ = S.select(queue, last=last, tlim=1200, certs_dir=certs, codes_dir=codes)
    assert "timed" in [r["slug"] for r in chosen] and "errored" in [r["slug"] for r in chosen]
    # named slugs: queue order is replaced by the named order, and a slug outside the queue is read from codes/
    _write(os.path.join(codes, "extra.json"), {"n": 20, "k": 2, "code_type": "CSS",
                                                 "distance": {"d": 4, "X": {"value": 4}, "Z": {"value": 4}}})
    chosen, _, _ = S.select(queue, last=last, tlim=600, certs_dir=certs, codes_dir=codes,
                            slugs=["extra", "timed", "refuted", "filed"])
    assert [r["slug"] for r in chosen] == ["extra", "timed", "refuted"] and chosen[0]["d"] == 4


def _proof(sha, clauses, proved=True):
    pr = {"cnf": {"sha256": sha, "clauses": clauses, "vars": 10, "bytes": 100}, "solve_secs": 0.5,
          "check_secs": 0.2, "proved": proved, "status": "UNSAT", "verified": proved,
          "proof": {"bytes": 95, "path": None}, "trimmed": {"bytes": 419, "path": "/tmp/x"}, "xor_chunk": 5}
    if not proved:
        pr.update(status="TIMEOUT", detail="kissat did not finish in 600s")
    return pr


def _record(level="proof_log"):
    sides = {s: {"value": 2, "exact": True, "status": "UNSAT", "secs": 0.1, "note": "no logical < 2 exists",
                 "proof": _proof("a" * 64 if s == "X" else "b" * 64, 89 if s == "X" else 83,
                                 proved=(level == "proof_log" or s == "X"))} for s in "XZ"}
    v = {"level": "proof_log", "checker": "drat-trim sha256:f58f63b0f76945d4",
         "cnf_sha256": "X=" + "a" * 64 + ";Z=" + "b" * 64, "note": "pure-CNF re-encoding refuted by kissat",
         "replay": {"emit": "python verify/replay_proofs.py s", "check": "kissat; drat-trim", "emitter": "side_cnf"}} \
        if level == "proof_log" else {"level": "solver", "note": "proof path did not complete: kissat did not finish"}
    return {"name": "s", "d": 2, "d_exact": True, "encoding": "selector", "logical_classes": 2, "sides": sides,
            "solver": "CryptoMiniSat 5.14 SAT", "symmetry": False, "tlim_per_solve": 600, "verification": v}


def test_the_filed_certificate_is_the_record_without_its_proof_blocks():
    S = _script()
    rec = _record()
    cert = S.certificate(rec)
    assert "proof" not in cert["sides"]["X"] and "proof" in rec["sides"]["X"], "the input is left alone"
    assert cert["verification"]["level"] == "proof_log" and cert["d_exact"] is True
    assert set(cert) == set(rec)
    row = S.batch_row("s", 12, rec)
    assert row == {"slug": "s", "n": 12, "level": "proof_log", "cnf_sha256": rec["verification"]["cnf_sha256"],
                   "detail": rec["verification"]["note"],
                   "X_cnf_clauses": 89, "X_proof_bytes": 95, "X_trimmed_bytes": 419, "X_solve_secs": 0.5,
                   "X_check_secs": 0.2, "Z_cnf_clauses": 83, "Z_proof_bytes": 95, "Z_trimmed_bytes": 419,
                   "Z_solve_secs": 0.5, "Z_check_secs": 0.2}
    assert S.batch_row("s", 12, _record("solver")) is None, "only a proof_log certificate gets a batch row"
    assert S.classify(rec) == "exact"
    sat = _record()
    sat["d_exact"] = False
    sat["sides"]["Z"].update(status="SAT", exact=False, witness=[0, 1])
    assert S.classify(sat) == "refuted"
    att = S.attempt_row(_row("s"), sat, tlim=600, date="2026-10-27", head="h", url=None, secs=1.0)
    assert att["outcome"] == "refuted" and att["witness"] == {"Z": [0, 1]} and att["level"] is None
    timed = _record()
    timed["d_exact"] = False
    timed["sides"]["X"].update(status="TIMEOUT", exact=False)
    assert S.classify(timed) == "timeout"
    err = S.attempt_row(_row("s"), None, tlim=600, date="2026-10-27", head="h", url=None, secs=1.0,
                        error="X side: pairing set spans 1 of 2 logical classes")
    assert err["outcome"] == "error" and err["note"].startswith("X side")


def test_a_run_files_what_closes_logs_every_attempt_and_exits_three_on_a_refutation(tmp_path):
    S = _script()
    codes, certs, out = str(tmp_path / "codes"), str(tmp_path / "certs"), str(tmp_path / "out")
    os.makedirs(certs)
    for slug in ("closes", "times-out", "refutes", "breaks"):
        _write(os.path.join(codes, slug + ".json"), {"n": 12, "k": 2, "code_type": "CSS",
                                                     "distance": {"d": 2, "X": {"value": 2}, "Z": {"value": 2}}})
    queue = {"date": "2026-10-27", "head": "q", "entries": [_row("closes"), _row("times-out"), _row("refutes"),
                                                             _row("breaks")]}

    def certify(doc, tlim, proof_dir, slug):
        assert os.path.isdir(proof_dir)
        rec = _record()
        if slug == "times-out":
            rec["d_exact"] = False
            rec["sides"]["Z"].update(status="TIMEOUT", exact=False)
        if slug == "refutes":
            rec["d_exact"] = False
            rec["sides"]["X"].update(status="SAT", exact=False, witness=[3])
        if slug == "breaks":
            raise ValueError("Z side: the XOR encoding says UNSAT and the pure-CNF encoding says SAT")
        return rec

    attempts = str(tmp_path / "attempts.jsonl")
    m = S.run_sweep(queue=queue, out_dir=out, attempts_path=attempts, tlim=600, job_seconds=1000, certs_dir=certs,
                    codes_dir=codes, certify=certify, tools=lambda: {"kissat": "4.0.4", "drat_trim": "x"})
    assert m["outcomes"] == {"exact": 1, "timeout": 1, "refuted": 1, "error": 1} and m["staged"] == ["closes"]
    rows = S.load_jsonl(attempts)
    assert [r["slug"] for r in rows] == ["closes", "times-out", "refutes", "breaks"]
    assert all(set(r) >= {"date", "head", "slug", "n", "k", "d", "tlim", "outcome", "secs", "sides"} for r in rows)
    assert os.path.exists(os.path.join(out, "certs", "closes.json"))
    assert [r["slug"] for r in S.load_jsonl(os.path.join(out, "certs", "proof_log_batch.jsonl"))] == ["closes"]
    with open(os.path.join(out, "certs", "closes.json"), encoding="utf-8") as f:
        assert "proof" not in json.load(f)["sides"]["X"]
    # the next run leaves all four alone: certified awaiting its PR, timed out at this budget, refuted, errored
    m2 = S.run_sweep(queue=queue, out_dir=str(tmp_path / "out2"), attempts_path=attempts, tlim=600, job_seconds=1000,
                     certs_dir=certs, codes_dir=codes, certify=certify, tools=lambda: {})
    assert m2["opened"] == 0 and m2["skipped"] == {"awaiting_pr": 1, "attempted": 2, "refuted": 1}
    # stage copies the certificate and its batch row, and refuses to overwrite one that landed meanwhile
    staged, skipped = S.stage(out, certs_dir=certs)
    assert staged == ["closes"] and skipped == []
    assert os.path.exists(os.path.join(certs, "closes.json"))
    assert [r["slug"] for r in S.load_jsonl(os.path.join(certs, "proof_log_batch.jsonl"))] == ["closes"]
    staged, skipped = S.stage(out, certs_dir=certs)
    assert staged == [] and skipped == ["closes"]
    assert len(S.load_jsonl(os.path.join(certs, "proof_log_batch.jsonl"))) == 1, "no duplicate batch row"
    title, body = S.pr_text(m, staged=["closes"])
    assert title == "certs: exact distances for 1 entry from the weekly certification sweep of " + m["date"]
    assert "| closes | 12 | 2 | 2 | proof_log |" in body and "#3666" in body and "times-out" not in body
    title, issue = S.refutation_text(m)
    assert "1 entry refuted" in title and "refutes" in issue and "weight 1" in issue
    summary = S.summary_markdown(m)
    assert "exact 1, timeout 1, refuted 1, error 1" in summary and "| closes |" in summary
    # the CLI exit code: 3 marks a refutation so the workflow reports it; 0 otherwise
    assert S.EXIT_REFUTED == 3


def test_the_budget_stops_opening_entries_and_reports_what_is_left(tmp_path):
    S = _script()
    codes, certs, out = str(tmp_path / "codes"), str(tmp_path / "certs"), str(tmp_path / "out")
    os.makedirs(certs)
    for slug in ("a", "b", "c"):
        _write(os.path.join(codes, slug + ".json"), {"n": 12})
    queue = {"entries": [_row("a"), _row("b"), _row("c")]}
    m = S.run_sweep(queue=queue, out_dir=out, attempts_path=str(tmp_path / "att.jsonl"), tlim=600, job_seconds=0,
                    certs_dir=certs, codes_dir=codes, certify=lambda *a, **k: _record(), tools=lambda: {})
    # the budget is checked before each entry, so a zero budget opens the first and stops
    assert m["opened"] <= 1 and m["stopped_by_budget"] and m["left"] == 3 - m["opened"]
    m = S.run_sweep(queue=queue, out_dir=out, attempts_path=str(tmp_path / "att2.jsonl"), tlim=600, job_seconds=100,
                    max_entries=2, certs_dir=certs, codes_dir=codes, certify=lambda *a, **k: _record(),
                    tools=lambda: {})
    assert m["opened"] == 2 and m["selected"] == 2


def test_a_real_certificate_on_a_tiny_board_entry_passes_the_certificate_checker(tmp_path):
    """The certifier's record, stripped and filed, is one verify/check_certs.py accepts."""
    pytest.importorskip("pycryptosat")
    pytest.importorskip("pysat")
    S = _script()
    import sys
    sys.path.insert(0, os.path.join(_ROOT, "verify"))
    import check_certs
    import sat_certify
    with open(os.path.join(_ROOT, "research", "certs", "todo.json"), encoding="utf-8") as f:
        queue = json.load(f)
    small = [r for r in queue["entries"] if r["code_type"] == "CSS" and r["n"] <= 20 and r["d"] <= 3
             and all(v["value"] == r["d"] for v in r["sides"].values())
             and os.path.exists(os.path.join(_ROOT, "codes", r["slug"] + ".json"))]
    if not small:
        pytest.skip("no tiny upper-bound CSS entry left to certify")
    certs = str(tmp_path / "certs")
    os.makedirs(certs)
    # the default path: verify/sat_certify.py in a subprocess under the wall clock
    m = S.run_sweep(queue=queue, out_dir=str(tmp_path / "out"), attempts_path=str(tmp_path / "att.jsonl"), tlim=60,
                    job_seconds=300, slugs=[small[0]["slug"]], certs_dir=certs, tools=sat_certify.tool_versions)
    (row,) = m["results"]
    assert row["outcome"] == "exact", row
    with open(os.path.join(tmp_path, "out", "certs", row["slug"] + ".json"), encoding="utf-8") as f:
        cert = json.load(f)
    assert check_certs.evidence_problems(row["slug"], cert) == []
    assert cert["sides"]["X"]["value"] == row["d"] and "proof" not in cert["sides"]["X"]
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(check_certs.load_schema()).validate(cert)



def test_the_wall_clock_kills_a_certifier_that_ignores_its_limit(tmp_path, monkeypatch):
    """A stand-in certifier that sleeps through its limit is killed, with its children, and logged as a timeout."""
    S = _script()
    stub = tmp_path / "stub_certify.py"
    stub.write_text("import subprocess, sys, time\n"
                    "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                    "time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(S, "SAT_CERTIFY", str(stub))
    monkeypatch.setattr(S, "WALL_FLOOR", 0)
    codes, certs = str(tmp_path / "codes"), str(tmp_path / "certs")
    os.makedirs(certs)
    _write(os.path.join(codes, "slow.json"), {"n": 12})
    t0 = time.time()
    m = S.run_sweep(queue={"entries": [_row("slow")]}, out_dir=str(tmp_path / "out"),
                    attempts_path=str(tmp_path / "att.jsonl"), tlim=0.25, job_seconds=100, certs_dir=certs,
                    codes_dir=codes, tools=lambda: {})
    assert time.time() - t0 < 30
    (row,) = m["results"]
    assert row["outcome"] == "timeout" and "wall clock" in row["note"] and m["staged"] == []
    rec, err, killed = S.certify_in_subprocess(os.path.join(codes, "slow.json"), "slow", 1, str(tmp_path / "p"),
                                               wall=0.5, script=str(stub))
    assert killed and rec is None and err is None
    # a certifier that exits with an error reports its last line
    bad = tmp_path / "bad_certify.py"
    bad.write_text("import sys\n"
                   "print('ValueError: X side: pairing set spans 1 of 2 logical classes', file=sys.stderr)\n"
                   "sys.exit(1)\n", encoding="utf-8")
    rec, err, killed = S.certify_in_subprocess(os.path.join(codes, "slow.json"), "slow", 1, str(tmp_path / "p"),
                                               wall=10, script=str(bad))
    assert rec is None and not killed and err.startswith("ValueError: X side")

"""verify_all orchestration: which entries pay the sampled LER replica.

With --ler-base REF only entries whose codes/<slug>.json or circuits/<slug>/
changed since REF are re-measured (PR runs); without it every claim is (pushes
to main). An unusable ref falls back to re-measuring everything, so a broken
diff can only cost time, never coverage. The verifiers themselves are faked:
this tests the routing, not stim.

--circuit-base REF routes the circuit tier the same way, and the second half
of this file covers it: which entries are checked, that nothing but the
circuit tier is skipped, and that verify.yml passes the flag on a data-only
pull request and on no other run.
"""
import json
import os
import subprocess

import qldpc_verify as QV
import verify_all as VA

OK_REP = {"ok": True, "earned_distance": {"d": {"value": 1, "tier": "t"}},
          "computed": {}, "checks": []}
OK_CIRC = {"ok": True, "earned_d_circ": {"d_circ": {"value": 1}}, "checks": []}
LER = {b: {"ler_per_round": 1e-3} for b in ("X", "Z")}


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True, text=True)


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _repo(tmp_path):
    """Build a repo: main has three ler entries; pr edits a's JSON and b's circuit."""
    root = str(tmp_path)
    for s in ("a-1-1", "b-1-1", "c-1-1"):
        _write(root, f"codes/{s}.json", json.dumps({"name": s, "circuit": {"ler": LER}}))
        _write(root, f"circuits/{s}/memory_x.stim", "# base\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "pr")
    _write(root, "codes/a-1-1.json",
           json.dumps({"name": "a-1-1", "circuit": {"ler": LER}, "note": "edited"}))
    _write(root, "circuits/b-1-1/memory_x.stim", "# rescheduled\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "pr")
    return root


def _run(monkeypatch, argv):
    measured = []
    monkeypatch.setattr(QV, "verify", lambda doc: json.loads(json.dumps(OK_REP)))
    monkeypatch.setattr(VA, "verify_circuit", lambda doc, d: json.loads(json.dumps(OK_CIRC)))
    monkeypatch.setattr(VA, "verify_ler",
                        lambda doc, d: (measured.append(doc["name"]), {"ok": True})[1])
    rc = VA.main(argv)
    return rc, sorted(measured)


def test_pr_run_measures_only_changed_entries(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, measured = _run(monkeypatch, ["--root", root, "--ler-base", "main"])
    assert rc == 0
    assert measured == ["a-1-1", "b-1-1"]          # JSON edit and circuit edit; not c
    c_line = next(ln for ln in capsys.readouterr().out.splitlines() if "c-1-1.json" in ln)
    assert c_line.startswith("PASS") and "ler unchanged since base" in c_line


def test_default_run_measures_everything(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    rc, measured = _run(monkeypatch, ["--root", root])
    assert rc == 0 and measured == ["a-1-1", "b-1-1", "c-1-1"]


def test_unusable_base_falls_back_to_everything(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, measured = _run(monkeypatch, ["--root", root, "--ler-base", "no-such-ref"])
    assert rc == 0 and measured == ["a-1-1", "b-1-1", "c-1-1"]
    assert "re-measuring every ler claim" in capsys.readouterr().out


def test_skipped_claim_cannot_hide_a_failing_entry(tmp_path, monkeypatch):
    """Skip only the replica: circuit failures on an unchanged entry still fail.

    A skipped LER re-measurement must not turn into a skipped entry.
    """
    root = _repo(tmp_path)
    bad = dict(OK_CIRC, ok=False, checks=[{"check": "dem_matches", "ok": False}])
    monkeypatch.setattr(QV, "verify", lambda doc: json.loads(json.dumps(OK_REP)))
    monkeypatch.setattr(VA, "verify_circuit",
                        lambda doc, d: json.loads(json.dumps(bad if doc["name"] == "c-1-1" else OK_CIRC)))
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    assert VA.main(["--root", root, "--ler-base", "main"]) == 1


def test_structural_reports_come_from_the_shared_pass(tmp_path, monkeypatch):
    """verify_all reads board_reports, the pass every other consumer reads.

    Issue #2613: a second implementation of the whole-board structural pass
    lived here as a bare verify() per entry, so the gate's dedup inputs and
    CI's verdict could drift apart. Faking board_reports and leaving verify
    armed proves the report never comes from anywhere else.
    """
    root = _repo(tmp_path)
    asked = []

    def fake_reports(code_dir):
        asked.append(os.path.relpath(code_dir, root) if code_dir.startswith(root)
                     else os.path.basename(code_dir))
        if not code_dir.startswith(root):
            return ()                            # no fixtures in this fake tree
        out = []
        for name in sorted(os.listdir(code_dir)):
            path = os.path.join(code_dir, name)
            with open(path) as f:
                doc = json.load(f)
            out.append({"path": path, "slug": name[:-5], "doc": doc,
                        "report": json.loads(json.dumps(OK_REP)),
                        "size_error": None, "load_error": None})
        return tuple(out)

    def no_bare_verify(doc):
        raise AssertionError("verify_all must not verify an entry itself")

    monkeypatch.setattr(QV, "board_reports", fake_reports)
    monkeypatch.setattr(VA, "board_reports", fake_reports)
    monkeypatch.setattr(QV, "verify", no_bare_verify)
    monkeypatch.setattr(VA, "verify_circuit", lambda doc, d: json.loads(json.dumps(OK_CIRC)))
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    assert VA.main(["--root", root]) == 0
    assert asked == ["codes", "fixtures"]
    assert not hasattr(VA, "verify")


def test_circuit_verdict_does_not_leak_into_the_shared_report(tmp_path, monkeypatch):
    """A circuit failure layered on one entry must not alter the shared report.

    The reports are memoized and shared, so a verdict written into one here
    would turn the same entry false for the gate or the site reading it in
    the same process.
    """
    root = _repo(tmp_path)
    shared = {}

    def fake_reports(code_dir):
        if not code_dir.startswith(root):
            return ()
        out = []
        for name in sorted(os.listdir(code_dir)):
            path = os.path.join(code_dir, name)
            with open(path) as f:
                doc = json.load(f)
            rep = shared.setdefault(name, json.loads(json.dumps(OK_REP)))
            out.append({"path": path, "slug": name[:-5], "doc": doc, "report": rep,
                        "size_error": None, "load_error": None})
        return tuple(out)

    bad = dict(OK_CIRC, ok=False, checks=[{"check": "dem_matches", "ok": False}])
    monkeypatch.setattr(VA, "board_reports", fake_reports)
    monkeypatch.setattr(VA, "verify_circuit", lambda doc, d: json.loads(json.dumps(bad)))
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    assert VA.main(["--root", root]) == 1
    assert all(rep["ok"] and rep["checks"] == [] for rep in shared.values())


def test_unparseable_entry_fails_instead_of_crashing(tmp_path, monkeypatch, capsys):
    """A parse failure is a FAIL on that entry, not an exception that ends the run.

    board_reports records it as load_error; this file has to surface it.
    """
    root = _repo(tmp_path)
    _write(root, "codes/zz-1-1.json", "{not json")
    monkeypatch.setattr(QV, "verify", lambda doc: json.loads(json.dumps(OK_REP)))
    monkeypatch.setattr(VA, "verify_circuit", lambda doc, d: json.loads(json.dumps(OK_CIRC)))
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    assert VA.main(["--root", root]) == 1
    out = capsys.readouterr().out
    assert any(ln.startswith("FAIL") and "zz-1-1.json" in ln and "JSONDecodeError" in ln
               for ln in out.splitlines())


# --circuit-base: which entries pay the circuit tier (the same routing question
# as --ler-base above, for the deterministic half of the tier).

def _run_circuit(monkeypatch, argv, circ=None, structural=None):
    """Run main with faked verifiers; return (rc, entries whose circuit tier ran)."""
    checked = []

    def fake_circuit(doc, d):
        checked.append(doc["name"])
        return json.loads(json.dumps((circ or {}).get(doc["name"], OK_CIRC)))

    monkeypatch.setattr(QV, "verify", lambda doc: json.loads(json.dumps(
        (structural or {}).get(doc["name"], OK_REP))))
    monkeypatch.setattr(VA, "verify_circuit", fake_circuit)
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    return VA.main(argv), sorted(checked)


def test_circuit_base_checks_only_changed_entries(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-base", "main"])
    assert rc == 0
    assert checked == ["a-1-1", "b-1-1"]           # JSON edit and circuit edit; not c
    out = capsys.readouterr().out
    c_line = next(ln for ln in out.splitlines() if "c-1-1.json" in ln)
    # The skipped entry passes on the base branch's evidence, and its line must
    # say so rather than print a d_circ this run did not earn.
    assert c_line.startswith("PASS") and "circuit unchanged since base" in c_line
    assert "d_circ<=" not in c_line
    assert "circuit tier not re-run for 1 entries unchanged since main" in out


def test_default_run_checks_every_circuit(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, checked = _run_circuit(monkeypatch, ["--root", root])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert "circuit tier not re-run" not in capsys.readouterr().out


def test_ler_base_alone_does_not_skip_a_circuit(tmp_path, monkeypatch):
    """The two flags are separate: the LER skip is sound on more runs than this one."""
    root = _repo(tmp_path)
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--ler-base", "main"])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]


def test_unusable_circuit_base_falls_back_to_everything(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-base", "no-such-ref"])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert "checking every circuit tier" in capsys.readouterr().out


def test_circuit_base_still_fails_a_changed_entry(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    bad = dict(OK_CIRC, ok=False, checks=[{"check": "dem_matches", "ok": False}])
    rc, _ = _run_circuit(monkeypatch, ["--root", root, "--circuit-base", "main"],
                         circ={"b-1-1": bad})    # b changed only under circuits/
    assert rc == 1


def test_circuit_base_never_skips_the_structural_pass(tmp_path, monkeypatch, capsys):
    """Only the circuit tier is skipped: an unchanged entry that fails structurally fails."""
    root = _repo(tmp_path)
    bad = dict(OK_REP, ok=False, checks=[{"check": "css_commutation", "ok": False}])
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-base", "main"],
                               structural={"c-1-1": bad})
    assert rc == 1 and checked == ["a-1-1", "b-1-1"]
    assert any(ln.startswith("FAIL") and "c-1-1.json" in ln
               for ln in capsys.readouterr().out.splitlines())


# The flag is only sound when the verifier is the base branch's, so the
# workflow may pass it on a data-only pull request and nowhere else. That rule
# is a few lines of shell inside verify.yml, so run those lines.

_WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".github", "workflows", "verify.yml")
_PR_SWEEPS = ("verify all submissions (trusted verifier for code changes)",
              "verify all submissions (LER stack unchanged)")


def _workflow_steps():
    """Return {step name: its lines} for verify.yml, read by indentation (no yaml dependency)."""
    steps, name = {}, None
    with open(_WORKFLOW, encoding="utf-8") as f:
        for line in f.read().splitlines():
            if line.startswith("      - name: "):
                name = line[len("      - name: "):]
                steps[name] = []
            elif line.startswith("      - ") or (line.strip() and not line.startswith(" " * 7)):
                name = None
            elif name is not None:
                steps[name].append(line)
    return steps


def _script(lines):
    """Return the `run: |` script of a step, dedented."""
    run = lines.index("        run: |")
    return "\n".join(ln[10:] for ln in lines[run + 1:]) + "\n"


def _verify_all_argv(script, tmp_path, data_only):
    """Run a sweep step's shell with a recording `uv` on PATH; return verify_all's argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "argv"
    uv = bindir / "uv"
    uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n')
    uv.chmod(0o755)
    env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "BASE_REF": "origin/main"}
    if data_only is not None:
        env["DATA_ONLY"] = data_only
    subprocess.run(["bash", "-e", "-c", script], env=env, check=True, cwd=tmp_path)
    argv = log.read_text().split("\n")
    return argv[argv.index("verify/verify_all.py") + 1:-1]


def test_workflow_passes_circuit_base_on_a_data_only_pr(tmp_path):
    steps = _workflow_steps()
    for name in _PR_SWEEPS:
        argv = _verify_all_argv(_script(steps[name]), tmp_path, "true")
        assert argv[-2:] == ["--circuit-base", "origin/main"], (name, argv)
        assert argv[argv.index("--ler-base") + 1] == "origin/main", (name, argv)


def test_workflow_withholds_circuit_base_when_anything_else_changed(tmp_path):
    """Not data-only, or the output missing altogether: the whole tier runs (fail closed)."""
    steps = _workflow_steps()
    for name in _PR_SWEEPS:
        for data_only in ("false", "", None):
            argv = _verify_all_argv(_script(steps[name]), tmp_path, data_only)
            assert "--circuit-base" not in argv, (name, data_only, argv)
            assert "--ler-base" in argv, (name, data_only, argv)


def test_only_the_pull_request_sweeps_can_skip_a_circuit():
    """A push to main and the scheduled run check every circuit, or nothing does."""
    steps = _workflow_steps()
    sweeps = {name for name, lines in steps.items()
              if any("verify/verify_all.py" in ln and not ln.lstrip().startswith("#")
                     for ln in lines)}
    assert set(_PR_SWEEPS) < sweeps and len(sweeps) == 4, sorted(sweeps)
    flagged = {name for name in sweeps
               if any("--circuit-base" in ln and not ln.lstrip().startswith("#")
                      for ln in steps[name])}
    assert flagged == set(_PR_SWEEPS), (
        f"{sorted(flagged - set(_PR_SWEEPS))} pass --circuit-base outside a pull request. "
        "The skip rests on a full run on the base branch; if the push and scheduled sweeps "
        "skip too, no run checks an unchanged entry's circuit at all."
    )

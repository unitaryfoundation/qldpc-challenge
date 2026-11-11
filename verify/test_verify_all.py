"""verify_all orchestration: which entries pay the sampled LER replica.

With --ler-base REF only entries whose codes/<slug>.json or circuits/<slug>/
changed since REF are re-measured (PR runs); without it every claim is (pushes
to main). An unusable ref falls back to re-measuring everything, so a broken
diff can only cost time, never coverage. The verifiers themselves are faked:
this tests the routing, not stim.

--circuit-base REF routes the circuit tier the same way, and the second half
of this file covers it: which entries are checked, that nothing but the
circuit tier is skipped, and that the flag is void once a file of the
verifier stack differs from REF. --circuit-record PATH is the same skip for
runs on main, from a record of passes keyed by content, and the last part
covers that: what a record line vouches for, that a failure is never
stored, and that verify.yml hands the record to no pull request.
"""
import json
import os
import subprocess

import pytest
import qldpc_verify as QV
import test_ler_stack as LS
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

def _run_circuit(monkeypatch, argv, circ=None, structural=None, stack_changed=False):
    """Run main with faked verifiers; return (rc, entries whose circuit tier ran).

    The stack check is faked too: left real it would diff this checkout
    against whatever `main` is here, and these tests are about routing.
    """
    checked = []
    monkeypatch.setattr(VA, "circuit_stack_changed", lambda base: stack_changed)

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


# The flag is only sound while the verifier is the one the base branch was
# checked with. verify_all decides that itself, from a diff of CIRCUIT_STACK.

def test_circuit_base_is_void_when_the_verifier_stack_changed(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-base", "main"],
                               stack_changed=True)
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    out = capsys.readouterr().out
    assert "the verifier stack differs from main" in out
    assert "circuit tier not re-run" not in out


def _stack_repo(tmp_path):
    """Build a repo holding every CIRCUIT_STACK file and two files outside it, on branch pr."""
    root = str(tmp_path / "verifier")
    for rel in (*VA.CIRCUIT_STACK, "verify/test_something.py", "site/build.py"):
        _write(root, rel, "base\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", "pr")
    return root


def _commit(root, rel, text="edited\n"):
    _write(root, rel, text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", f"edit {rel}")


def test_stack_check_ignores_files_outside_the_stack(tmp_path):
    root = _stack_repo(tmp_path)
    assert VA.circuit_stack_changed("main", root) is False
    _commit(root, "verify/test_something.py")
    _commit(root, "site/build.py")
    _commit(root, "codes/a-1-1.json")
    assert VA.circuit_stack_changed("main", root) is False


@pytest.mark.parametrize("rel", VA.CIRCUIT_STACK)
def test_stack_check_sees_an_edit_to_every_stack_file(tmp_path, rel):
    root = _stack_repo(tmp_path)
    _commit(root, rel)
    assert VA.circuit_stack_changed("main", root) is True


def test_stack_check_sees_a_deleted_stack_file(tmp_path):
    root = _stack_repo(tmp_path)
    os.remove(os.path.join(root, VA.CIRCUIT_STACK[0]))
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "delete")
    assert VA.circuit_stack_changed("main", root) is True


def test_stack_check_fails_closed(tmp_path):
    """A ref or a checkout that cannot be diffed is a changed stack: the whole tier runs."""
    root = _stack_repo(tmp_path)
    assert VA.circuit_stack_changed("no-such-ref", root) is True
    assert VA.circuit_stack_changed("main", str(tmp_path / "not-a-checkout")) is True
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    assert VA.circuit_stack_changed("main", str(bare)) is True


def test_circuit_stack_is_the_import_closure_of_verify_all():
    """A module verify_all can import and CIRCUIT_STACK does not name fails here.

    The skip and the record both rest on the list being complete, and the
    list and the imports live in different places.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    seen, todo, files = set(), ["verify_all"], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        path = os.path.join(here, name + ".py")
        if os.path.isfile(path):
            files.add("verify/" + name + ".py")
            todo.extend(LS.imported_names(path))
        elif name in LS._BUILT:
            files.update(LS._BUILT[name])
    fixed = {"schema/code.schema.json", "pyproject.toml", "uv.lock", "Makefile",
             ".github/workflows/verify.yml"}
    listed = set(VA.CIRCUIT_STACK)
    assert listed == files | fixed, (
        f"CIRCUIT_STACK in verify/verify_all.py lists {sorted(listed - files - fixed)} that "
        f"verify_all does not import and misses {sorted((files | fixed) - listed)} that it does."
    )
    assert len(VA.CIRCUIT_STACK) == len(listed), "CIRCUIT_STACK repeats an entry"
    root = os.path.dirname(here)
    missing = [rel for rel in VA.CIRCUIT_STACK if not os.path.isfile(os.path.join(root, rel))]
    assert not missing, f"CIRCUIT_STACK names files that do not exist: {missing}"


# --circuit-record: the same skip for runs on main, from a record of passes
# keyed by content rather than from a diff.

def _record_repo(tmp_path):
    """Return (root, record path): the three-entry repo and a record path outside it."""
    root = _repo(tmp_path / "repo")
    return root, str(tmp_path / "circuit-record" / "record.json")


def _passes(record):
    with open(record, encoding="utf-8") as f:
        return json.load(f)["passed"]


def test_record_skips_what_has_passed_on_these_bytes(tmp_path, monkeypatch, capsys):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]     # no record yet
    assert "no circuit record at" in capsys.readouterr().out
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1", "c-1-1"]

    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == []
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("PASS") and "-1-1.json" in ln]
    assert len(lines) == 3
    # A recorded pass is not this run's evidence, so no d_circ is printed for it.
    assert all("circuit recorded as passing on these bytes" in ln and "d_circ<=" not in ln
               for ln in lines)
    assert "circuit tier not re-run for 3 entries recorded as passing" in out


def test_record_reruns_an_entry_when_anything_it_read_changed(tmp_path, monkeypatch):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run_circuit(monkeypatch, argv)
    # Nothing here is committed: the key is the bytes on disk, not git's view.
    _write(root, "codes/a-1-1.json", json.dumps({"name": "a-1-1", "circuit": {"ler": LER}}) + "\n")
    _write(root, "circuits/b-1-1/memory_x.stim", "# rescheduled again\n")
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["a-1-1", "b-1-1"]
    _write(root, "circuits/c-1-1/memory_z.dem", "# a new file beside the old one\n")
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["c-1-1"]
    os.rename(os.path.join(root, "circuits/c-1-1/memory_z.dem"),
              os.path.join(root, "circuits/c-1-1/memory_y.dem"))       # same bytes, new name
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["c-1-1"]
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == []


def test_record_made_under_another_stack_is_empty(tmp_path, monkeypatch, capsys):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run_circuit(monkeypatch, argv)
    capsys.readouterr()
    monkeypatch.setattr(VA, "circuit_stack_digest", lambda: "another-stack")
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert "made under another verifier stack" in capsys.readouterr().out


def test_stack_digest_moves_with_every_stack_file(tmp_path):
    root = _stack_repo(tmp_path)
    base = VA.circuit_stack_digest(root)
    assert VA.circuit_stack_digest(root) == base
    for rel in VA.CIRCUIT_STACK:
        _write(root, rel, "edited\n")
        assert VA.circuit_stack_digest(root) != base, rel
        _write(root, rel, "base\n")
    assert VA.circuit_stack_digest(root) == base
    os.remove(os.path.join(root, VA.CIRCUIT_STACK[-1]))
    assert VA.circuit_stack_digest(root) != base
    _write(root, "site/build.py", "edited\n")                   # outside the stack


def test_record_never_stores_a_failure(tmp_path, monkeypatch):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    bad = dict(OK_CIRC, ok=False, checks=[{"check": "dem_matches", "ok": False}])
    rc, checked = _run_circuit(monkeypatch, argv, circ={"c-1-1": bad})
    assert rc == 1 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1"]
    rc, checked = _run_circuit(monkeypatch, argv, circ={"c-1-1": bad})
    assert rc == 1 and checked == ["c-1-1"]                      # re-run every time
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["c-1-1"]
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1", "c-1-1"]


@pytest.mark.parametrize("text", [
    "{not json",
    "[]",
    json.dumps({"version": 1, "stack": "x"}),
    json.dumps({"version": 99, "stack": "x", "passed": {}}),
])
def test_malformed_record_is_an_empty_record(tmp_path, monkeypatch, capsys, text):
    root, record = _record_repo(tmp_path)
    _write(os.path.dirname(record), "record.json", text)
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-record", record])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert "checking every circuit tier" in capsys.readouterr().out
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1", "c-1-1"]   # and it is repaired


def test_record_line_for_other_bytes_is_not_believed(tmp_path, monkeypatch):
    """A line under the right stack and slug vouches for nothing but its own digest."""
    root, record = _record_repo(tmp_path)
    planted = {"version": VA.RECORD_VERSION, "stack": VA.circuit_stack_digest(),
               "passed": {s: "0" * 64 for s in ("a-1-1", "b-1-1", "c-1-1")}}
    _write(os.path.dirname(record), "record.json", json.dumps(planted))
    rc, checked = _run_circuit(monkeypatch, ["--root", root, "--circuit-record", record])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]


def test_record_forgets_an_entry_that_left_the_board(tmp_path, monkeypatch):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run_circuit(monkeypatch, argv)
    os.remove(os.path.join(root, "codes/c-1-1.json"))
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == []
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1"]


def test_record_never_skips_the_structural_pass(tmp_path, monkeypatch, capsys):
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run_circuit(monkeypatch, argv)
    capsys.readouterr()
    bad = dict(OK_REP, ok=False, checks=[{"check": "css_commutation", "ok": False}])
    rc, checked = _run_circuit(monkeypatch, argv, structural={"c-1-1": bad})
    assert rc == 1 and checked == []
    assert any(ln.startswith("FAIL") and "c-1-1.json" in ln
               for ln in capsys.readouterr().out.splitlines())
    assert sorted(_passes(record)) == ["a-1-1", "b-1-1"]


def test_record_does_not_skip_the_ler_replica(tmp_path, monkeypatch):
    """The record is about the deterministic tier; a sampled rate has its own flag."""
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run(monkeypatch, argv)
    rc, measured = _run(monkeypatch, argv)
    assert rc == 0 and measured == ["a-1-1", "b-1-1", "c-1-1"]


def test_record_is_written_as_the_run_goes(tmp_path, monkeypatch):
    """A run that stops early keeps its passes, and the old record's lines it had not reached."""
    root, record = _record_repo(tmp_path)
    argv = ["--root", root, "--circuit-record", record]
    _run_circuit(monkeypatch, argv)
    old = _passes(record)
    _write(root, "circuits/a-1-1/memory_x.stim", "# changed\n")
    _write(root, "circuits/b-1-1/memory_x.stim", "# changed\n")
    monkeypatch.setattr(VA, "RECORD_FLUSH_EVERY", 1)

    def cut_off_at_b(doc, d):
        if doc["name"] == "b-1-1":
            raise KeyboardInterrupt
        return json.loads(json.dumps(OK_CIRC))

    monkeypatch.setattr(QV, "verify", lambda doc: json.loads(json.dumps(OK_REP)))
    monkeypatch.setattr(VA, "verify_circuit", cut_off_at_b)
    monkeypatch.setattr(VA, "verify_ler", lambda doc, d: {"ok": True})
    with pytest.raises(KeyboardInterrupt):
        VA.main(argv)
    left = _passes(record)
    assert left["a-1-1"] != old["a-1-1"]                         # earned before the stop
    assert left["b-1-1"] == old["b-1-1"] and left["c-1-1"] == old["c-1-1"]
    rc, checked = _run_circuit(monkeypatch, argv)
    assert rc == 0 and checked == ["b-1-1"]     # b's old line is for other bytes; c's holds


def test_unwritable_record_is_reported_and_does_not_change_the_verdict(tmp_path, monkeypatch, capsys):
    root, _ = _record_repo(tmp_path)
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    rc, checked = _run_circuit(
        monkeypatch, ["--root", root, "--circuit-record", str(blocker / "record.json")])
    assert rc == 0 and checked == ["a-1-1", "b-1-1", "c-1-1"]
    assert "WARNING: could not write the circuit record" in capsys.readouterr().out


# Which run gets which flag is a few lines of shell and a few `if:` lines
# inside verify.yml, so run the shell and read the conditions back.

_WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         ".github", "workflows", "verify.yml")
_PR_SWEEPS = ("verify all submissions (trusted verifier for code changes)",
              "verify all submissions (LER stack unchanged)")
_PUSH_SWEEP = "verify all submissions (push to main, LER scoped to the merge)"
_FULL_SWEEP = "verify all submissions (full LER re-measure)"
_RESTORE = "restore the circuit record (push to main)"
_SAVE = "save the circuit record (runs on main)"
_RECORD = "../circuit-record/record.json"


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


def _code(lines):
    """Return a step's lines without its comments."""
    return [ln for ln in lines if not ln.lstrip().startswith("#")]


def _verify_all_argv(script, tmp_path, **env):
    """Run a sweep step's shell with a recording `uv` on PATH; return verify_all's argv."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "argv"
    uv = bindir / "uv"
    uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\n')
    uv.chmod(0o755)
    env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "BASE_REF": "origin/main", **env}
    subprocess.run(["bash", "-e", "-c", script], env=env, check=True, cwd=tmp_path)
    argv = log.read_text().split("\n")
    return argv[argv.index("verify/verify_all.py") + 1:-1]


def test_every_pull_request_sweep_passes_circuit_base(tmp_path):
    """Whether the flag holds is verify_all's call, so no pull request sweep withholds it."""
    steps = _workflow_steps()
    for name in _PR_SWEEPS:
        argv = _verify_all_argv(_script(steps[name]), tmp_path)
        assert argv[-2:] == ["--circuit-base", "origin/main"], (name, argv)
        assert argv[argv.index("--ler-base") + 1] == "origin/main", (name, argv)
    argv = _verify_all_argv(_script(steps[_FULL_SWEEP]), tmp_path, EVENT_NAME="pull_request")
    assert argv == ["--circuit-base", "origin/main"], argv


def test_no_pull_request_sweep_is_handed_the_record(tmp_path):
    """The record is trusted because only main writes and reads it."""
    steps = _workflow_steps()
    for name in _PR_SWEEPS:
        assert not any("--circuit-record" in ln for ln in _code(steps[name])), name
        assert "--circuit-record" not in _verify_all_argv(_script(steps[name]), tmp_path), name
    full = _script(steps[_FULL_SWEEP])
    assert "--circuit-record" not in _verify_all_argv(full, tmp_path, EVENT_NAME="pull_request")
    for event in ("push", "schedule", "workflow_dispatch"):
        assert _verify_all_argv(full, tmp_path, EVENT_NAME=event) == ["--circuit-record", _RECORD]
    push = _code(steps[_PUSH_SWEEP])
    assert any(ln.startswith("        if: github.event_name == 'push' && ") for ln in push)
    run = next(ln for ln in push if "verify/verify_all.py" in ln)
    assert run.endswith(f" --circuit-record {_RECORD}") and "--circuit-base" not in run


def test_every_sweep_is_scoped_one_way_or_the_other():
    """Four sweeps, and each names how its circuit tier is scoped: none is left to a default."""
    steps = _workflow_steps()
    sweeps = {name for name, lines in steps.items()
              if any("verify/verify_all.py" in ln for ln in _code(lines))}
    assert sweeps == {*_PR_SWEEPS, _PUSH_SWEEP, _FULL_SWEEP}, sorted(sweeps)
    for name in sweeps:
        text = "\n".join(_code(steps[name]))
        assert "--circuit-base" in text or "--circuit-record" in text, name


def test_the_record_is_restored_and_saved_only_on_main():
    """The cache is main's at both ends, and the weekly run starts from nothing."""
    steps = _workflow_steps()
    users = {name for name, lines in steps.items()
             if any("circuit-record" in ln for ln in _code(lines))}
    assert users == {_RESTORE, _SAVE, _PUSH_SWEEP, _FULL_SWEEP}, sorted(users)
    # Restored on a push and on nothing else: not a pull request, which must
    # never be answered from a cache, and not the scheduled run, which is the
    # from-scratch check the record's lines are never more than a week from.
    assert "        if: github.event_name == 'push'" in steps[_RESTORE]
    assert "        uses: actions/cache/restore@v4" in steps[_RESTORE]
    with open(_WORKFLOW, encoding="utf-8") as f:
        assert "\n  push:\n    branches: [main]\n" in f.read()
    cond = next(ln for ln in steps[_SAVE] if ln.startswith("        if: "))[len("        if: "):]
    for clause in ("always()", "github.event_name != 'pull_request'",
                   "github.ref == 'refs/heads/main'"):
        assert clause in cond.split(" && "), (clause, cond)
    assert "        uses: actions/cache/save@v4" in steps[_SAVE]
    assert "        uses: actions/cache@v4" not in "\n".join(steps[_RESTORE] + steps[_SAVE])

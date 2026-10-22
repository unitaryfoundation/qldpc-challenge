"""Regression tests for `qldpc submit --reuse-witnesses` (PR #3980).

A re-submit starts from a draft's distance witnesses and keeps the lighter
of them and of the ones a search finds, so an imported code keeps the
witness it already has. `--reuse-witnesses` is the strict form of that
rule: it skips the RIS search and refuses a draft whose witness cannot be
used, rather than quietly replacing it with another one.

The rules to keep:

  * the weight comes from the witness, not from the draft's `value` field,
  * a draft whose witness cannot be used is refused (with the flag) or
    reported and ignored (without it), never replaced silently,
  * the accelerator pass still runs and may tighten the claim,
  * the draft's source attribution (construction, notes, references,
    novelty, witness_provenance) comes with the code.

The last one is why the construction/notes fallback is tied to the flag:
without it, an ordinary re-submit would copy someone else's construction
text under a new name.
"""

import numpy as np
import pytest

import heuristic_distance as hd
import qldpc

# A small CSS code (n = 6, k = 2) with logicals of more than one weight on
# each side, so a test can put a heavy witness in the draft and let the
# accelerator find a lighter one. Every qubit is covered by a check, so the
# distance is 2 rather than 1.
HX = np.array([[1, 1, 1, 1, 0, 0],
               [0, 0, 0, 0, 1, 1]], dtype=np.uint8)
HZ = np.array([[1, 1, 0, 0, 1, 1],
               [0, 0, 1, 1, 1, 1]], dtype=np.uint8)


def _logicals(H_ker, H_row, n=6):
    """Every nontrivial logical, by brute force (n is tiny here)."""
    out = []
    for bits in range(1, 1 << n):
        v = np.array([(bits >> i) & 1 for i in range(n)], dtype=np.int8)
        if hd._valid_logical(v, H_ker, H_row):
            out.append(sorted(int(i) for i in np.where(v)[0]))
    return out


def _vector(support, n=6):
    """Return the 0/1 vector of a support."""
    v = np.zeros(n, dtype=np.int8)
    for i in support:
        v[i] = 1
    return v


X_LOGICALS = _logicals(HZ, HX)
Z_LOGICALS = _logicals(HX, HZ)
LIGHT_X = min(X_LOGICALS, key=len)
HEAVY_X = max(X_LOGICALS, key=len)
LIGHT_Z = min(Z_LOGICALS, key=len)
HEAVY_Z = max(Z_LOGICALS, key=len)


class _FakeFast:
    """Stand-in for the C++ accelerator, so the tests do not spend trials."""

    def __init__(self, side=None, support=()):
        self.side = side
        self.support = list(support)
        self.calls = []

    def distance_rand_witness(self, HX, HZ, trials, seed, a, b):
        self.calls.append(trials)
        if self.side is None:
            return (None, None, None)
        return (1, self.side, self.support)


def _draft(x_witness, z_witness, **overrides):
    """Return a CSS draft carrying the given witnesses."""
    doc = {
        "schema_version": "0.1",
        "name": "[[6,2,2]]",
        "code_type": "CSS",
        "n": 6,
        "k": 2,
        "checks": {"X": [[0, 1, 2, 3], [4, 5]],
                   "Z": [[0, 1, 4, 5], [2, 3, 4, 5]]},
        "distance": {
            "d": min(len(x_witness), len(z_witness)),
            "X": {"value": len(x_witness), "confidence": "upper_bound",
                  "witness": list(x_witness)},
            "Z": {"value": len(z_witness), "confidence": "upper_bound",
                  "witness": list(z_witness)},
        },
        "provenance": {
            "authors": ["@someoneelse"],
            "construction": "imported from a published table",
            "origin": "submission",
            "date": "2026-01-02",
        },
    }
    doc.update(overrides)
    return doc


def _submit(monkeypatch, draft, extra=(), matrices=(HX, HZ)):
    """Run `qldpc submit` on `draft` and return the document it built."""
    built = []

    monkeypatch.setattr(qldpc, "load_checks",
                        lambda _p: (matrices[0], matrices[1], None, draft))
    monkeypatch.setattr(qldpc, "attach_circuit_tier", lambda _d, _a: None)

    def fake_verify(doc, refute):
        built.append(doc)
        return {"ok": True, "checks": [], "computed": {}, "earned_distance": {}}

    monkeypatch.setattr(qldpc, "verify", fake_verify)
    rc = qldpc.main(["submit", "x.json", "--authors", "@me", "--dry-run",
                     "--no-circuit", *extra])
    assert rc == 0
    return built[0]


def _no_search(monkeypatch):
    """Make the RIS search fail loudly if a reuse run reaches it."""
    def boom(*_a, **_kw):
        raise AssertionError("the RIS search must not run in reuse mode")

    monkeypatch.setattr(hd, "ris_min_logical", boom)
    monkeypatch.setattr(hd, "ris_min_pauli_logical", boom)


# ----------------------------------------------------------------------------
# the flag keeps the draft's witness
# ----------------------------------------------------------------------------
def test_reuse_keeps_the_drafts_witness_and_skips_the_search(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, HEAVY_Z)

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert doc["distance"]["X"]["witness"] == HEAVY_X
    assert doc["distance"]["Z"]["witness"] == HEAVY_Z
    assert doc["distance"]["X"]["value"] == len(HEAVY_X)
    assert doc["distance"]["Z"]["value"] == len(HEAVY_Z)
    assert doc["distance"]["d"] == min(len(HEAVY_X), len(HEAVY_Z))


def test_reuse_takes_the_weight_from_the_witness_not_the_drafts_value(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["X"]["value"] = 99

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert doc["distance"]["X"]["value"] == len(HEAVY_X)
    assert doc["distance"]["X"]["witness"] == HEAVY_X


def test_reuse_reports_a_draft_whose_value_disagrees_with_its_witness(
        monkeypatch, capsys):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["X"]["value"] = 99

    _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    out = capsys.readouterr().out
    assert "99" in out and str(len(HEAVY_X)) in out


# ----------------------------------------------------------------------------
# a draft that cannot be used is refused, never replaced by a search
# ----------------------------------------------------------------------------
def test_reuse_refuses_a_witness_that_is_not_a_logical(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft([0], LIGHT_Z)          # a single qubit is not a logical here

    with pytest.raises(SystemExit, match="X witness is not a nontrivial logical"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_an_index_outside_the_code(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["X"]["witness"] = [0, 1, 2, 3, 9]

    with pytest.raises(SystemExit, match=r"outside \[0, 6\)"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_a_negative_index(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["Z"]["witness"] = [-1, 2]

    with pytest.raises(SystemExit, match=r"outside \[0, 6\)"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_a_draft_with_a_witness_on_one_side_only(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    del draft["distance"]["Z"]["witness"]

    with pytest.raises(SystemExit, match="one side only"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_a_draft_with_no_witness_at_all(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    del draft["distance"]["X"]["witness"]
    del draft["distance"]["Z"]["witness"]

    with pytest.raises(SystemExit, match="no distance witness"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_a_refused_reuse_does_not_fall_back_to_the_search(monkeypatch):
    """The refusal is the point: a fallback would hand back a different claim."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda *a, **k: pytest.fail("the search must not run"))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft([0], LIGHT_Z)

    with pytest.raises(SystemExit):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_an_input_that_is_not_a_json_draft(monkeypatch):
    monkeypatch.setattr(qldpc, "load_checks",
                        lambda _p: (HX, HZ, None, None))

    with pytest.raises(SystemExit, match="no JSON draft"):
        qldpc.main(["submit", "x.npz", "--authors", "@me", "--dry-run",
                    "--no-circuit", "--reuse-witnesses"])


def test_reuse_refuses_a_run_without_the_accelerator_pass(monkeypatch):
    monkeypatch.setattr(hd, "_fast", None)
    draft = _draft(HEAVY_X, LIGHT_Z)

    with pytest.raises(SystemExit, match="accelerator is not built"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"])


def test_reuse_refuses_a_run_with_the_accelerator_switched_off(monkeypatch):
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)

    with pytest.raises(SystemExit, match="--fast-trials 0"):
        _submit(monkeypatch, draft,
                extra=["--reuse-witnesses", "--fast-trials", "0"])


# ----------------------------------------------------------------------------
# the accelerator still runs, and its witness wins
# ----------------------------------------------------------------------------
def test_the_accelerator_still_runs_in_reuse_mode(monkeypatch):
    _no_search(monkeypatch)
    fast = _FakeFast()
    monkeypatch.setattr(hd, "_fast", fast)
    draft = _draft(HEAVY_X, LIGHT_Z)

    _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert fast.calls, "the accelerator pass must run on a reused witness"


def test_the_accelerator_can_tighten_a_reused_witness(monkeypatch):
    _no_search(monkeypatch)
    fast = _FakeFast(side="X", support=LIGHT_X)
    monkeypatch.setattr(hd, "_fast", fast)
    draft = _draft(HEAVY_X, LIGHT_Z)

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert doc["distance"]["X"]["value"] == len(LIGHT_X)
    assert doc["distance"]["X"]["witness"] == LIGHT_X
    assert doc["distance"]["Z"]["witness"] == LIGHT_Z


def test_a_witness_the_accelerator_found_replaces_the_drafts_provenance(
        monkeypatch):
    _no_search(monkeypatch)
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@someoneelse"], "date": "2026-01-02",
        "found_at_samples": 1000,
    }
    draft["distance"]["Z"]["witness_provenance"] = {
        "found_by": ["@someoneelse"], "date": "2026-01-02",
        "found_at_samples": 1000,
    }
    monkeypatch.setattr(hd, "_fast", _FakeFast(side="X", support=LIGHT_X))

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    wp = doc["distance"]["X"]["witness_provenance"]
    assert wp["found_by"] == ["@me"]
    assert wp["found_at_samples"] == 2_000_000
    # the side the accelerator did not touch keeps the draft's record
    assert doc["distance"]["Z"]["witness_provenance"]["found_by"] == \
        ["@someoneelse"]


# ----------------------------------------------------------------------------
# the draft's source attribution comes with the code
# ----------------------------------------------------------------------------
def test_reuse_keeps_the_drafts_construction_notes_and_references(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["provenance"]["notes"] = "the published table this came from"
    draft["provenance"]["references"] = ["arXiv:0000.00000"]

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    prov = doc["provenance"]
    assert prov["construction"] == "imported from a published table"
    assert prov["notes"] == "the published table this came from"
    assert prov["references"] == ["arXiv:0000.00000"]


def test_an_explicit_construction_wins_over_the_drafts(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)

    doc = _submit(monkeypatch, draft,
                  extra=["--reuse-witnesses", "--construction", "mine"])

    assert doc["provenance"]["construction"] == "mine"


def test_reuse_keeps_the_drafts_witness_provenance(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@someoneelse"], "date": "2026-01-02",
        "found_at_samples": 1000, "tool": "ris_gpu",
    }

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    wp = doc["distance"]["X"]["witness_provenance"]
    assert wp["found_by"] == ["@someoneelse"]
    assert wp["tool"] == "ris_gpu"


def test_an_import_of_a_published_code_is_recorded_as_known_parameters(
        monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["provenance"]["references"] = ["arXiv:0000.00000"]

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert doc["provenance"]["novelty"] == "known_parameters"


def test_the_drafts_own_novelty_is_kept(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)
    draft["provenance"]["novelty"] = "new_parameters"

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    assert doc["provenance"]["novelty"] == "new_parameters"


def test_without_the_flag_the_drafts_construction_is_not_copied(monkeypatch):
    """An ordinary re-submit must not copy someone else's construction text."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(LIGHT_X),
                                                      _vector(LIGHT_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, LIGHT_Z)

    doc = _submit(monkeypatch, draft)

    assert doc["provenance"]["construction"] == "contributed via qldpc submit"
    assert "references" not in doc["provenance"]


# ----------------------------------------------------------------------------
# without the flag, the draft's witness still wins when it is the lighter one
# ----------------------------------------------------------------------------
def test_without_the_flag_a_lighter_draft_witness_is_kept(monkeypatch):
    """The problem the flag exists for is fixed on every re-submit."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(HEAVY_X),
                                                      _vector(HEAVY_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(LIGHT_X, LIGHT_Z)

    doc = _submit(monkeypatch, draft)

    assert doc["distance"]["X"]["witness"] == LIGHT_X
    assert doc["distance"]["X"]["value"] == len(LIGHT_X)


def test_without_the_flag_a_heavier_search_witness_wins(monkeypatch):
    """The search still replaces the draft's witness when it is lighter."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(LIGHT_X),
                                                      _vector(LIGHT_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(HEAVY_X, HEAVY_Z)

    doc = _submit(monkeypatch, draft)

    assert doc["distance"]["X"]["witness"] == LIGHT_X
    assert doc["distance"]["Z"]["witness"] == LIGHT_Z


def test_without_the_flag_an_unusable_draft_witness_is_reported(monkeypatch,
                                                                 capsys):
    """No silence: the draft's witness is checked, and the check is said out."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(LIGHT_X),
                                                      _vector(LIGHT_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft([0], LIGHT_Z)

    doc = _submit(monkeypatch, draft)

    out = capsys.readouterr().out
    assert "not usable" in out
    assert "not a nontrivial logical" in out
    assert doc["distance"]["X"]["witness"] == LIGHT_X


def test_a_kept_draft_witness_carries_the_drafts_witness_provenance(monkeypatch):
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(HEAVY_X),
                                                      _vector(HEAVY_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(LIGHT_X, LIGHT_Z)
    draft["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@someoneelse"], "date": "2026-01-02",
        "found_at_samples": 1000,
    }

    doc = _submit(monkeypatch, draft)

    wp = doc["distance"]["X"]["witness_provenance"]
    assert wp["found_by"] == ["@someoneelse"]


def test_a_draft_witness_provenance_that_does_not_fit_is_dropped(monkeypatch):
    """The document has to stay schema-valid, so a bad record is dropped."""
    monkeypatch.setattr(hd, "ris_min_logical",
                        lambda HX, HZ, trials, seed: (len(HEAVY_X),
                                                      _vector(HEAVY_X)))
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _draft(LIGHT_X, LIGHT_Z)
    draft["distance"]["X"]["witness_provenance"] = {"found_by": ["@me"]}

    doc = _submit(monkeypatch, draft)

    assert "witness_provenance" not in doc["distance"]["X"]


# ----------------------------------------------------------------------------
# a stabilizer draft
# ----------------------------------------------------------------------------
# Three commuting generators on n = 4 qubits:
#   g0 = X_0 Z_1, g1 = Y_0 X_1 Z_2, g2 = Z_0 X_1 X_2
# Qubit 0 carries an X, a Y and a Z across the three generators, which is
# what makes the code NOT CSS up to a local Clifford (a qubit carrying all
# three letters rules the map out), so the CLI takes the stabilizer path.
# k = 1, and the lightest logical is Z on the untouched qubit 3.
SA = np.array([[1, 0, 0, 0],
               [1, 1, 0, 0],
               [0, 1, 1, 0]], dtype=np.uint8)
SB = np.array([[0, 1, 0, 0],
               [1, 0, 1, 0],
               [1, 0, 0, 0]], dtype=np.uint8)


def _stabilizer_draft(**overrides):
    doc = {
        "schema_version": "0.4",
        "name": "[[4,1,1]]",
        "code_type": "stabilizer",
        "n": 4,
        "k": 1,
        "checks": {"S": [{"X": [0], "Z": [1]},
                         {"X": [0, 1], "Z": [0, 2]},
                         {"X": [1, 2], "Z": [0]}]},
        "distance": {
            "d": 1,
            "P": {"value": 1, "confidence": "upper_bound",
                  "witness": {"X": [], "Z": [3]}},
        },
        "provenance": {
            "authors": ["@someoneelse"],
            "construction": "a stabilizer code from a published table",
            "origin": "submission",
            "date": "2026-01-02",
        },
    }
    doc.update(overrides)
    return doc


def test_reuse_keeps_a_stabilizer_drafts_pauli_witness(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _stabilizer_draft()

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"],
                  matrices=(SA, SB))

    assert doc["code_type"] == "stabilizer"
    assert doc["distance"]["P"]["value"] == 1
    assert doc["distance"]["P"]["witness"] == {"X": [], "Z": [3]}


def test_reuse_refuses_a_stabilizer_draft_with_no_pauli_witness(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _stabilizer_draft()
    del draft["distance"]["P"]["witness"]

    with pytest.raises(SystemExit, match="no Pauli witness"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"],
                matrices=(SA, SB))


def test_reuse_refuses_a_pauli_witness_index_outside_the_code(monkeypatch):
    _no_search(monkeypatch)
    monkeypatch.setattr(hd, "_fast", _FakeFast())
    draft = _stabilizer_draft()
    draft["distance"]["P"]["witness"] = {"X": [], "Z": [7]}

    with pytest.raises(SystemExit, match=r"outside \[0, 4\)"):
        _submit(monkeypatch, draft, extra=["--reuse-witnesses"],
                matrices=(SA, SB))



# ----------------------------------------------------------------------------
# schema_version stays valid when the accelerator tightens (regression)
# ----------------------------------------------------------------------------
def test_reuse_tightened_doc_passes_real_verify(monkeypatch):
    import qldpc_verify

    _no_search(monkeypatch)
    fast = _FakeFast(side="X", support=LIGHT_X)
    monkeypatch.setattr(hd, "_fast", fast)
    draft = _draft(HEAVY_X, LIGHT_Z)

    doc = _submit(monkeypatch, draft, extra=["--reuse-witnesses"])

    report = qldpc_verify.verify(doc, refute=False)
    assert report["ok"], report["checks"]


def test_npz_path_tightened_doc_passes_real_verify(monkeypatch):
    import qldpc_verify

    calls = {"n": 0}

    def ris(HX, HZ, trials, seed):
        calls["n"] += 1
        if calls["n"] == 1:
            return (len(HEAVY_X), _vector(HEAVY_X))
        return (len(LIGHT_Z), _vector(LIGHT_Z))

    monkeypatch.setattr(hd, "ris_min_logical", ris)
    fast = _FakeFast(side="X", support=LIGHT_X)
    monkeypatch.setattr(hd, "_fast", fast)

    built = []

    def load_checks(_p):
        return (HX, HZ, None, None)

    monkeypatch.setattr(qldpc, "load_checks", load_checks)
    monkeypatch.setattr(qldpc, "attach_circuit_tier", lambda _d, _a: None)

    def fake_verify(doc, refute):
        built.append(doc)
        return {"ok": True, "checks": [], "computed": {}, "earned_distance": {}}

    monkeypatch.setattr(qldpc, "verify", fake_verify)
    rc = qldpc.main(["submit", "x.npz", "--authors", "@me", "--dry-run",
                     "--no-circuit", "--fast-trials", "300000", "--seed", "1"])
    assert rc == 0
    doc = built[0]

    report = qldpc_verify.verify(doc, refute=False)
    assert report["ok"], report["checks"]

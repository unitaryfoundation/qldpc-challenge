"""Guard witness preservation and deadline scoring, not implementation details."""

import json
import sys

import numpy as np
import pytest
from common import HERE, ROOT, benchmark_schema_status, code_target

sys.path.insert(0, str(HERE / "build"))

import submit
from corpus import supports_matrix, zsz
from submit import make_submission


@pytest.fixture
def code():
    document = json.loads((ROOT / "codes" / "72-12-6.json").read_text())
    hx = supports_matrix(document["checks"]["X"], document["n"])
    hz = supports_matrix(document["checks"]["Z"], document["n"])
    witnesses = {side: document["distance"][side]["witness"] for side in ("X", "Z")}
    return hx, hz, witnesses


def test_retained_witnesses_do_not_trigger_another_search(code, monkeypatch):
    hx, hz, witnesses = code

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Existing witnesses must not be rediscovered")

    monkeypatch.setattr(submit, "lightest_logical", forbidden)
    document = make_submission(hx, hz, name="test", construction="test", authors=["test"], witnesses=witnesses)
    assert document["distance"]["d"] == 6
    assert document["distance"]["X"]["witness"] == witnesses["X"]
    assert not submit.validate(document)


def test_schema_is_loaded_and_only_size_cap_is_exempt_for_benchmarks(code):
    hx, hz, witnesses = code
    document = make_submission(hx, hz, name="test", construction="test", authors=[], witnesses=witnesses)
    assert any("authors" in error for error in submit.validate(document))
    with pytest.raises(ValueError, match="schema error"):
        benchmark_schema_status(document)
    document["provenance"]["authors"] = ["test"]
    assert benchmark_schema_status(document) == "valid"
    document["n"] = 1000
    assert benchmark_schema_status(document) == "above_size_cap"
    document["provenance"]["construction"] = ""
    with pytest.raises(ValueError, match="schema error"):
        benchmark_schema_status(document)


def test_missing_schema_does_not_silently_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(submit, "_SCHEMA_PATH", tmp_path / "missing-schema.json")
    with pytest.raises(FileNotFoundError):
        submit.validate({})


def test_target_contract_preserves_stricter_code_and_paper_targets():
    case = {"reference": {"X": list(range(32)), "Z": list(range(34))}}
    assert code_target(case) == 32
    case["paper_target"] = 30
    assert code_target(case) == 30
    assert code_target({}) is None


def test_partial_study_cannot_be_reported_as_complete(tmp_path):
    from report import main

    source = tmp_path / "run"
    result = source / "one-case" / "cpp-s0"
    result.mkdir(parents=True)
    (source / "environment.json").write_text(json.dumps({"methods": ["cpp"], "seed_start": 0, "seeds": 2}))
    (source / "corpus.json").write_text(json.dumps({"cases": [{"id": "one-case"}]}))
    (result / "result.json").write_text(
        json.dumps({"case": "one-case", "method": "cpp", "seed": 0, "validation_status": "passed"})
    )
    with pytest.raises(ValueError, match="Incomplete"):
        main(source, tmp_path / "report")


@pytest.mark.parametrize("failure", ["duplicate", "out_of_range", "stabilizer", "wrong_syndrome", "missing_side"])
def test_retained_invalid_witness_is_rejected(code, failure):
    hx, hz, witnesses = code
    witnesses = {side: list(support) for side, support in witnesses.items()}
    if failure == "duplicate":
        witnesses["X"].append(witnesses["X"][0])
    elif failure == "out_of_range":
        witnesses["X"][0] = hx.shape[1]
    elif failure == "stabilizer":
        witnesses["X"] = np.flatnonzero(hx[0]).tolist()
    elif failure == "wrong_syndrome":
        witnesses["X"] = [0]
    else:
        del witnesses["Z"]
    with pytest.raises(ValueError):
        make_submission(hx, hz, name="test", construction="test", authors=[], witnesses=witnesses)


def test_deadline_miss_is_censored_but_witness_retained():
    pytest.importorskip("benchmark_native")
    from run import summarize_side

    event = {"seconds": 1.01, "weight": 6, "support": [1, 2, 3, 4, 5, 6]}
    workers = [{"events": [event], "trials": 100, "cpu_seconds": 1.2, "search_seconds": 1.01, "status": "completed"}]
    summary = summarize_side(workers, target=6, seconds=1)
    assert summary["target_hit"] is False
    assert summary["best_in_budget"] is None
    assert summary["best_returned"] == 6


def test_m4ri_nzlist_keeps_indices_and_checks_weight(tmp_path):
    pytest.importorskip("benchmark_native")
    from run import read_codewords

    path = tmp_path / "words.txt"
    path.write_text("%% NZLIST\n% generated\n3 1 4 7\n")
    assert read_codewords(path) == [[0, 3, 6]]
    path.write_text("2 1 4 7\n")
    with pytest.raises(ValueError):
        read_codewords(path)


def test_zsz_reconstruction_matches_existing_anchor():
    # Same representation and polynomials as the already committed 700-qubit
    # instance; compare stabilizer rowspaces to allow check row reordering.
    import gf2

    document = json.loads((ROOT / "codes" / "700-140-22.json").read_text())
    polynomials = [
        [[0, 0], [29, 1], [2, 2]],
        [[0, 0], [7, 1], [9, 1]],
        [[0, 0], [19, 0], [16, 1]],
        [[0, 0], [32, 2], [23, 3]],
    ]
    generated = zsz([35, 4, 8], polynomials)
    for side, actual in zip(("X", "Z"), generated, strict=True):
        expected = supports_matrix(document["checks"][side], document["n"])
        assert np.array_equal(gf2.rref(actual)[0], gf2.rref(expected)[0])

"""Tests for the optional provenance.search_budget block (schema 0.3).

The board records who found a code and with which model, but not what the
search cost. `qldpc submit` now fills `provenance.search_budget` from the
--budget-* flags or a --budget-json file; a document that carries the block
must declare schema_version 0.3, and one without it stays at 0.1.
"""

import json
import os

import jsonschema
import numpy as np
import pytest
import qldpc

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _steane():
    H = np.array([[1, 0, 1, 0, 1, 0, 1], [0, 1, 1, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1, 1]], dtype=np.uint8)
    return H.copy(), H.copy()


def _report():
    return {
        "ok": True,
        "checks": [],
        "computed": {
            "n": 7,
            "k": 1,
            "max_check_weight": 4,
            "weight_class": "weight-4",
            "locality_class": "unrestricted",
        },
        "earned_distance": {"d": {"value": 3, "tier": "upper_bound"}},
    }


def _submit(monkeypatch, capsys, tmp_path, *extra):
    """Run a dry-run submit on the Steane code.

    Returns the document it would write (the --json preview). The circuit
    tier is switched off: it is not what these tests are about, and with it
    on the document would carry a circuit block and schema 0.2.
    """
    HX, HZ = _steane()
    monkeypatch.setattr(qldpc, "load_checks", lambda _p: (HX, HZ, None, None))
    monkeypatch.setattr(qldpc, "verify", lambda _doc, refute: _report())
    rc = qldpc.main(
        [
            "submit",
            "x.npz",
            "--authors",
            "@me",
            "--dry-run",
            "--json",
            "--no-circuit",
            "--trials",
            "50",
            "--fast-trials",
            "0",
            "--out",
            str(tmp_path / "codes"),
            *extra,
        ]
    )
    assert rc == 0
    text = capsys.readouterr().out
    return json.loads(text[text.index("{") :])


def _schema():
    with open(os.path.join(_ROOT, "schema", "code.schema.json")) as f:
        return json.load(f)


def test_flags_fill_search_budget_and_bump_schema_version(monkeypatch, capsys, tmp_path):
    doc = _submit(
        monkeypatch,
        capsys,
        tmp_path,
        "--budget-candidates-screened",
        "12000",
        "--budget-ris-trials-per-side",
        "1000000",
        "--budget-cpu-hours",
        "6.5",
        "--budget-gpu-hours",
        "0",
        "--budget-llm-tokens",
        "GLM 5.3 Flash=1800000",
        "--budget-llm-tokens",
        "Claude Opus 4.8=250000",
        "--budget-wall-clock-hours",
        "9",
        "--budget-tool",
        "research/kit/search.py + gf2_fast",
        "--budget-notes",
        "two sweeps over orders 60-120",
    )
    assert doc["schema_version"] == "0.3"
    assert doc["provenance"]["search_budget"] == {
        "candidates_screened": 12000,
        "ris_trials_per_side": 1000000,
        "cpu_hours": 6.5,
        "gpu_hours": 0.0,
        "llm_tokens": {"GLM 5.3 Flash": 1800000, "Claude Opus 4.8": 250000},
        "wall_clock_hours": 9.0,
        "tool": "research/kit/search.py + gf2_fast",
        "notes": "two sweeps over orders 60-120",
    }
    jsonschema.Draft202012Validator(_schema()).validate(doc)


def test_without_budget_flags_document_stays_at_0_1(monkeypatch, capsys, tmp_path):
    doc = _submit(monkeypatch, capsys, tmp_path)
    assert doc["schema_version"] == "0.1"
    assert "search_budget" not in doc["provenance"]
    jsonschema.Draft202012Validator(_schema()).validate(doc)


def test_budget_json_file_with_flag_override(monkeypatch, capsys, tmp_path):
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"cpu_hours": 2.0, "tool": "kit", "llm_tokens": {"GLM 5.3 Flash": 100}}))
    doc = _submit(
        monkeypatch,
        capsys,
        tmp_path,
        "--budget-json",
        str(budget),
        "--budget-cpu-hours",
        "3.5",
        "--budget-llm-tokens",
        "Claude Opus 4.8=7",
    )
    assert doc["schema_version"] == "0.3"
    assert doc["provenance"]["search_budget"] == {
        "cpu_hours": 3.5,
        "tool": "kit",
        "llm_tokens": {"GLM 5.3 Flash": 100, "Claude Opus 4.8": 7},
    }


def test_budget_json_inline_object(monkeypatch, capsys, tmp_path):
    doc = _submit(monkeypatch, capsys, tmp_path, "--budget-json", '{"wall_clock_hours": 1.25}')
    assert doc["provenance"]["search_budget"] == {"wall_clock_hours": 1.25}


def test_budget_json_rejects_unknown_keys():
    args = type("A", (), {"budget_json": '{"tpu_hours": 1}'})()
    with pytest.raises(SystemExit, match=r"unknown key.*tpu_hours"):
        qldpc.search_budget_from_args(args)


def test_llm_tokens_requires_model_equals_count():
    args = type("A", (), {"budget_json": "", "budget_llm_tokens": ["Claude Opus 4.8"]})()
    with pytest.raises(SystemExit, match=r"MODEL=COUNT"):
        qldpc.search_budget_from_args(args)


def test_schema_ties_search_budget_to_version_0_3():
    v = jsonschema.Draft202012Validator(_schema())
    doc = {
        "schema_version": "0.1",
        "name": "x",
        "code_type": "CSS",
        "n": 7,
        "k": 1,
        "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
        "distance": {
            "d": 3,
            "X": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
            "Z": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
        },
        "provenance": {"authors": ["@me"], "construction": "c", "search_budget": {"cpu_hours": 1}},
    }
    assert not v.is_valid(doc)
    doc["schema_version"] = "0.3"
    assert v.is_valid(doc)
    doc["provenance"]["search_budget"]["tpu_hours"] = 1
    assert not v.is_valid(doc)


def test_0_3_document_may_carry_0_2_features():
    v = jsonschema.Draft202012Validator(_schema())
    doc = {
        "schema_version": "0.3",
        "name": "x",
        "code_type": "CSS",
        "n": 7,
        "k": 1,
        "checks": {"X": [[0, 1, 2, 3]], "Z": [[0, 1, 2, 3]]},
        "distance": {
            "d": 3,
            "X": {
                "value": 3,
                "confidence": "upper_bound",
                "witness": [0, 1, 2],
                "witness_provenance": {"found_by": ["@me"], "date": "2026-09-17", "found_at_samples": 10},
            },
            "Z": {"value": 3, "confidence": "upper_bound", "witness": [0, 1, 2]},
        },
        "provenance": {"authors": ["@me"], "construction": "c", "search_budget": {"gpu_hours": 0}},
    }
    assert v.is_valid(doc)
    del doc["provenance"]["search_budget"]
    doc["schema_version"] = "0.2"
    assert v.is_valid(doc)

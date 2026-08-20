"""Tests for gate_changed.classify_diff (issue #654): the refutation gate
prices the DIFF, so each diff class must be recognized from structural facts
alone, and anything else must fail closed to the full gate. Pure unit tests
on document dicts -- no git, no search."""

import copy
import os

import gate_changed as G

BASE = {
    "schema_version": "0.1",
    "name": "[[60,8,6]] synthetic test code",
    "code_type": "CSS",
    "n": 60, "k": 8,
    "checks": {"X": [[0, 1, 2]], "Z": [[3, 4, 5]]},
    "distance": {
        "d": 6,
        "X": {"value": 6, "confidence": "upper_bound",
              "witness": [0, 1, 2, 3, 4, 5]},
        "Z": {"value": 7, "confidence": "upper_bound",
              "witness": [0, 1, 2, 3, 4, 5, 6]},
    },
    "provenance": {"authors": ["@alice"], "construction": "synthetic",
                   "notes": "original."},
}


def _tightened(value=5):
    doc = copy.deepcopy(BASE)
    doc["name"] = f"[[60,8,{value}]] synthetic test code"
    doc["distance"]["X"] = {"value": value, "confidence": "upper_bound",
                            "witness": list(range(value)),
                            "witness_provenance": {
                                "found_by": ["@bob"], "date": "2026-08-20",
                                "found_at_samples": 10 ** 6}}
    doc["distance"]["d"] = min(value, doc["distance"]["Z"]["value"])
    doc["provenance"]["notes"] += " Refuted."
    return doc


def _with_layout(doc=None):
    doc = copy.deepcopy(doc or BASE)
    doc["schema_version"] = "0.2"
    doc["locality"] = {"coordinates": [[float(i), 0.0] for i in range(60)],
                       "layers": 2,
                       "contributed_by": {"by": ["@bob"],
                                          "date": "2026-08-20"}}
    doc["provenance"]["notes"] += " Layout added."
    return doc


def test_new_code():
    cls, _ = G.classify_diff(None, copy.deepcopy(BASE))
    assert cls == "new"


def test_layout_only():
    cls, _ = G.classify_diff(BASE, _with_layout())
    assert cls == "layout-only"


def test_metadata_only_is_layout_class():
    doc = copy.deepcopy(BASE)
    doc["provenance"]["notes"] += " Marked exact."
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "layout-only"


def test_tightening():
    cls, _ = G.classify_diff(BASE, _tightened())
    assert cls == "tightening"


def test_tightening_both_sides():
    doc = _tightened()
    doc["distance"]["Z"] = {"value": 6, "confidence": "upper_bound",
                            "witness": list(range(6))}
    doc["distance"]["d"] = 5
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "tightening"


def test_survival_stamp_added_goes_deep():
    doc = copy.deepcopy(BASE)
    doc["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@bob"], "date": "2026-08-20",
        "found_at_samples": 10 ** 6, "survived_samples": 10 ** 8}
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "stamp"


def test_survival_stamp_raised_goes_deep():
    base = copy.deepcopy(BASE)
    base["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@carol"], "date": "2026-08-01",
        "found_at_samples": 10 ** 6, "survived_samples": 10 ** 7}
    doc = copy.deepcopy(base)
    doc["distance"]["X"]["witness_provenance"]["survived_samples"] = 10 ** 9
    cls, _ = G.classify_diff(base, doc)
    assert cls == "stamp"


def test_stamp_riding_on_tightening_goes_deep():
    doc = _tightened()
    doc["distance"]["X"]["witness_provenance"]["survived_samples"] = 10 ** 8
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "stamp"


def test_unchanged_survival_stamp_is_not_a_stamp_diff():
    base = copy.deepcopy(BASE)
    base["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@carol"], "date": "2026-08-01",
        "found_at_samples": 10 ** 6, "survived_samples": 10 ** 7}
    doc = _with_layout(base)
    cls, _ = G.classify_diff(base, doc)
    assert cls == "layout-only"


def test_checks_change_is_full():
    doc = _with_layout()
    doc["checks"]["X"] = [[0, 1, 3]]
    cls, why = G.classify_diff(BASE, doc)
    assert cls == "full" and "checks" in why


def test_value_raised_is_full():
    doc = copy.deepcopy(BASE)
    doc["distance"]["X"]["value"] = 8
    doc["distance"]["X"]["witness"] = list(range(8))
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "full"


def test_mixed_layout_and_tightening_is_full():
    doc = _with_layout(_tightened())
    cls, why = G.classify_diff(BASE, doc)
    assert cls == "full" and "mixed" in why


def test_witness_weight_mismatch_is_full():
    doc = _tightened()
    doc["distance"]["X"]["witness"] = list(range(4))   # weight 4, value 5
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "full"


def test_witness_swap_at_same_value_is_full():
    doc = copy.deepcopy(BASE)
    doc["distance"]["X"]["witness"] = [0, 1, 2, 3, 4, 6]
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "full"


def test_exact_at_new_value_is_full():
    doc = _tightened()
    doc["distance"]["X"]["confidence"] = "exact"
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "full"


def test_bad_d_is_full():
    doc = _tightened()
    doc["distance"]["d"] = 6
    cls, _ = G.classify_diff(BASE, doc)
    assert cls == "full"


def test_garbage_fails_closed():
    cls, _ = G.classify_diff({"distance": None}, {"distance": {"d": 3}})
    assert cls == "full"


def test_base_doc_pairing(tmp_path):
    """base_doc_for must find the base doc for an in-place edit AND across a
    refutation rename; a genuinely new file must yield None (-> 'new')."""
    import json
    import subprocess
    td = str(tmp_path)

    def git(*args):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        *args], cwd=td, check=True, capture_output=True)

    os.makedirs(os.path.join(td, "codes"))

    def write(fname, doc):
        os.makedirs(os.path.join(td, "codes"), exist_ok=True)
        with open(os.path.join(td, "codes", fname), "w") as f:
            json.dump(doc, f, indent=1)

    git("init", "-q", "-b", "main")
    write("60-8-6.json", BASE)
    git("add", "codes")
    git("commit", "-q", "-m", "base")
    git("checkout", "-q", "-b", "change")

    # in-place layout addition
    lay = _with_layout()
    write("60-8-6.json", lay)
    git("add", "codes")
    git("commit", "-q", "-m", "layout")
    bd = G.base_doc_for("codes/60-8-6.json", lay, "main", td)
    assert bd is not None and G.classify_diff(bd, lay)[0] == "layout-only"

    # refutation rename 60-8-6 -> 60-8-5
    tight = _tightened()
    git("rm", "-q", "codes/60-8-6.json")
    write("60-8-5.json", tight)
    git("add", "codes")
    git("commit", "-q", "-m", "refute")
    bd = G.base_doc_for("codes/60-8-5.json", tight, "main", td)
    assert bd is not None and G.classify_diff(bd, tight)[0] == "tightening"

    # a brand-new code has no counterpart
    new = copy.deepcopy(BASE)
    new["n"], new["name"] = 61, "[[61,8,6]] other"
    write("61-8-6.json", new)
    git("add", "codes")
    git("commit", "-q", "-m", "new")
    assert G.base_doc_for("codes/61-8-6.json", new, "main", td) is None


def _grid_layout(n=60, layers=2, spacing=1.0):
    return {"coordinates": [[spacing * (i % 10), spacing * (i // 10)]
                            for i in range(n)],
            "layers": layers}


def test_tighter_class_guard_fires_on_honest_layout():
    doc = copy.deepcopy(BASE)
    doc["locality"] = _grid_layout()          # honest bilayer grid, small radius
    assert G.layout_entered_tighter_class(BASE, doc)


def test_tighter_class_guard_ignores_dishonest_layout():
    doc = copy.deepcopy(BASE)
    doc["locality"] = _grid_layout(spacing=0.1)   # violates unit spacing
    assert not G.layout_entered_tighter_class(BASE, doc)


def test_tighter_class_guard_ignores_unchanged_class():
    base = copy.deepcopy(BASE)
    base["locality"] = _grid_layout()
    doc = copy.deepcopy(base)
    doc["locality"]["coordinates"] = list(reversed(doc["locality"]["coordinates"]))
    assert not G.layout_entered_tighter_class(base, doc)


def test_structural_ok_ignores_candidate_pipeline_gates():
    """An in-place board edit self-matches dedup and advances nothing; only
    the verifier gate decides structural soundness (#674 regression)."""
    self_dup = {"passed": False,
                "gates": {"verify": {"ok": True, "failed_checks": []},
                          "dedup": {"exact_duplicate_of": "40-10-4.json"},
                          "novelty": {"board_advancing": False}}}
    assert G.structural_ok(self_dup)
    rejected = {"passed": False,
                "gates": {"verify": {"ok": False,
                                     "failed_checks": ["coordinates_cover_all_qubits"]}}}
    assert not G.structural_ok(rejected)
    assert not G.structural_ok({})

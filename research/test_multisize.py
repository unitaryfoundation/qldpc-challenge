"""The multi-size check lifts recipes by rule, judges each size on structure only, and stays current.

The gross code's monomials encode nothing one step off their torus and do
encode when a side is doubled or halved, which is what the lift exists to
show; a recipe with no rule or no kit module is labeled, not guessed; and
the committed table has to agree with a fresh run (issue #4031).
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

import multisize as ms  # noqa: E402

GROSS = {"l": 12, "m": 6, "A_terms": [[3, 0], [0, 2], [0, 1]], "B_terms": [[2, 0], [1, 0], [0, 3]]}


def test_the_bb_lift_names_the_neighbors_and_the_doublings():
    labels = [lab for lab, _ in ms.lift_bb(GROSS)]
    assert labels == ["l=11, m=6", "l=13, m=6", "l=12, m=5", "l=12, m=7", "l=24, m=6", "l=12, m=12",
                      "l=6, m=6", "l=12, m=3"]
    assert [lab for lab, _ in ms.lift_cyclic_gb({"m": 31, "a": [0, 1], "b": [0, 3]})] == ["m=30", "m=32"]


def test_the_gross_code_is_a_construction_under_doubling_not_under_one_step():
    by = {lab: ms.instance("bb.build_bb", p) for lab, p in ms.lift_bb(GROSS)}
    assert by["l=6, m=6"]["pass"] and (by["l=6, m=6"]["n"], by["l=6, m=6"]["k"]) == (72, 12)
    assert by["l=24, m=6"]["pass"] and by["l=24, m=6"]["k"] >= 1
    for lab in ("l=11, m=6", "l=13, m=6", "l=12, m=5", "l=12, m=7"):
        assert by[lab]["checks"]["commutes"] and not by[lab]["checks"]["encodes"], lab
    own = ms.instance("bb.build_bb", GROSS)
    assert own["pass"] and own["fingerprint"] == ms.entry_fingerprint("144-12-12")


def test_recipes_without_a_rule_or_a_module_are_labeled():
    rec = ms.analyze("128-8-9", json.load(open(os.path.join(_ROOT, "repro", "128-8-9.json"), encoding="utf-8")))
    assert rec["status"] == "no_lift_rule" and rec["own"]["pass"] and rec["reproduces_entry"] is True
    fake = {"stages": {"construction": {"status": "applicable",
                                        "args": ["--constructor", "nowhere.build", "--params", "{}"]}}}
    assert ms.analyze("x", fake)["status"] == "constructor_missing"
    assert ms.analyze("x", {"stages": {"construction": {"status": "not_reproducible"}}})["status"] == "no_recipe"


def test_compare_separates_drift_from_rows_the_table_has_not_caught_up_with():
    was = {"a": ("lifted", [True, False], True), "b": ("no_lift_rule", [], True), "d": ("no_recipe", [], None)}
    new = {"a": ("lifted", [False, False], True), "c": ("lifted", [True], True), "d": ("no_recipe", [], None)}
    assert ms.compare(new, was) == ({"a"}, {"c"}, {"b"})
    assert ms.compare(was, was) == (set(), set(), set())


def test_unchanged_ignores_the_date_and_head_of_a_run():
    with open(ms.TABLE, encoding="utf-8") as f:
        old = json.load(f)
    fresh = dict(old, date="1970-01-01", head="0" * 40)
    assert ms.unchanged(fresh, old)
    assert not ms.unchanged(dict(fresh, entries={}), old)
    assert not ms.unchanged(dict(fresh, lifts={}), old)


def test_the_committed_table_has_no_drift_from_a_fresh_run():
    """A verdict the table records must still come out of the kit.

    A manifest the table has not caught up with is not drift: a submission PR
    adds its own repro/<slug>.json and may not touch research/ (issue #3810),
    and site.yml regenerates the table on main after the merge. The scheduled
    reproduce run checks with --strict, where nothing should be pending.
    """
    with open(ms.TABLE, encoding="utf-8") as f:
        old = json.load(f)
    assert old["issue"] == 4031 and "no distance" in old["method"]
    drifted, _added, _removed = ms.compare(ms.verdicts(ms.build_table()), ms.verdicts(old))
    assert drifted == set(), drifted

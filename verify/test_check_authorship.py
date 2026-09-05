"""Tests for check_authorship.py, including the refutation binding (#611).

Builds a throwaway git repo, commits a code owned by @alice, then checks which
edits @bob can and cannot land: a clean refutation (rename + strictly lighter
witness credited to him in witness_provenance) binds; anything that also
touches the construction, authorship, or credit does not. The gate does no
code math, so the fixture code is synthetic.
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import check_authorship

BASE_DOC = {
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

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def git(td, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    *args], cwd=td, check=True, capture_output=True)


def write_code(td, fname, doc):
    os.makedirs(os.path.join(td, "codes"), exist_ok=True)
    with open(os.path.join(td, "codes", fname), "w") as f:
        json.dump(doc, f, indent=1)  # multi-line, like real board files


def make_repo(td, base_doc=None):
    git(td, "init", "-q", "-b", "main")
    write_code(td, "60-8-6.json", base_doc or BASE_DOC)
    git(td, "add", "codes")
    git(td, "commit", "-q", "-m", "base")
    git(td, "checkout", "-q", "-b", "change")


def refuted(with_wp=True, found_by="@bob"):
    doc = copy.deepcopy(BASE_DOC)
    doc["name"] = "[[60,8,5]] synthetic test code"
    doc["schema_version"] = "0.2"
    doc["distance"]["X"] = {"value": 5, "confidence": "upper_bound",
                            "witness": [0, 1, 2, 3, 4]}
    if with_wp:
        doc["distance"]["X"]["witness_provenance"] = {
            "found_by": [found_by], "date": "2026-08-19", "found_at_samples": 10 ** 9}
    doc["distance"]["d"] = 5
    doc["provenance"]["notes"] += " Refuted."
    return doc


def run_case(name, edit, expect_ok, author="bob", rename=True,
             base_doc=None):
    with tempfile.TemporaryDirectory() as td:
        make_repo(td, base_doc=base_doc)
        doc = edit()
        if rename:
            git(td, "rm", "-q", "codes/60-8-6.json")
            write_code(td, "60-8-5.json", doc)
        else:
            write_code(td, "60-8-6.json", doc)
        git(td, "add", "codes")
        git(td, "commit", "-q", "-m", "change")
        rc = check_authorship.main(
            ["--author", author, "--root", td, "--base", "main"])
        check(name, (rc == 0) == expect_ok)


def main():
    print("refutation binding (issue #611):")
    run_case("clean refutation by @bob binds", refuted, True)
    run_case("in-place (no rename) refutation binds",
             refuted, True, rename=False)
    run_case("owner @alice still binds via authors",
             refuted, True, author="alice")

    def no_wp():
        return refuted(with_wp=False)
    run_case("lighter witness without witness_provenance rejected",
             no_wp, False)

    def wrong_credit():
        return refuted(found_by="@carol")
    run_case("witness_provenance crediting someone else rejected",
             wrong_credit, False)

    def touches_checks():
        doc = refuted()
        doc["checks"]["X"] = [[0, 1, 3]]
        return doc
    run_case("refutation that also edits checks rejected", touches_checks,
             False)

    def appends_author():
        doc = refuted()
        doc["provenance"]["authors"].append("@bob")
        return doc
    run_case("refutation that also appends to authors rejected",
             appends_author, False)

    def swaps_author():
        doc = copy.deepcopy(BASE_DOC)
        doc["provenance"]["authors"] = ["@bob"]
        return doc
    run_case("author swap on someone else's code rejected", swaps_author,
             False, rename=False)

    def owner_adds_coauthor():
        doc = copy.deepcopy(BASE_DOC)
        doc["provenance"]["authors"] = ["@alice", "@carol"]
        return doc
    run_case("existing author may edit the author list",
             owner_adds_coauthor, True, author="alice", rename=False)

    def rewrites_notes():
        doc = refuted()
        doc["provenance"]["notes"] = "Mine now."
        return doc
    run_case("refutation that rewrites notes rejected", rewrites_notes, False)

    def loosens():
        doc = refuted()
        doc["distance"]["X"]["value"] = 8
        doc["distance"]["X"]["witness"] = list(range(8))
        doc["distance"]["d"] = 7
        doc["name"] = BASE_DOC["name"]
        return doc
    run_case("loosened bound rejected (no strict decrease)", loosens, False)

    def stamp_only():
        doc = copy.deepcopy(BASE_DOC)
        doc["schema_version"] = "0.2"
        doc["distance"]["X"]["witness_provenance"] = {
            "found_by": ["@bob"], "date": "2026-08-19", "found_at_samples": 10 ** 9}
        return doc
    run_case("survival stamp alone does not grant edit rights", stamp_only,
             False, rename=False)

    def stamp_riding_along():
        doc = refuted()
        doc["distance"]["Z"]["witness_provenance"] = {
            "found_by": ["@bob"], "date": "2026-08-19", "found_at_samples": 10 ** 9}
        return doc
    run_case("survival stamp riding on a real refutation binds",
             stamp_riding_along, True)

    print("\nexact-claim corrections (PR review round 2):")
    EXACT_BASE = copy.deepcopy(BASE_DOC)
    EXACT_BASE["distance"]["X"]["confidence"] = "exact"

    def demotes_exact():
        doc = refuted()
        doc["distance"]["X"]["confidence"] = "upper_bound"
        return doc
    run_case("refuted exact claim demoting to upper_bound binds",
             demotes_exact, True, base_doc=EXACT_BASE)

    def keeps_exact():
        doc = refuted()
        doc["distance"]["X"]["confidence"] = "exact"
        return doc
    run_case("refuted exact claim keeping 'exact' rejected",
             keeps_exact, False, base_doc=EXACT_BASE)

    def upgrades_to_exact():
        doc = refuted()
        doc["distance"]["X"]["confidence"] = "exact"
        return doc
    run_case("correction claiming 'exact' at the new value rejected",
             upgrades_to_exact, False)

    def stamp_upgrades_conf():
        doc = refuted()
        doc["distance"]["Z"]["confidence"] = "exact"
        doc["distance"]["Z"]["witness_provenance"] = {
            "found_by": ["@bob"], "date": "2026-08-19",
            "found_at_samples": 10 ** 9}
        return doc
    run_case("survival stamp that upgrades confidence rejected",
             stamp_upgrades_conf, False)

    print("\nbaselines (no @handle authors):")
    BASELINE = copy.deepcopy(BASE_DOC)
    BASELINE["provenance"]["authors"] = ["Kitaev"]

    def claims_baseline():
        doc = copy.deepcopy(BASELINE)
        doc["provenance"]["authors"] = ["Kitaev", "@bob"]
        doc["n"] = 61
        return doc
    run_case("first @handle claim on a baseline rejected",
             claims_baseline, False, rename=False, base_doc=BASELINE)

    def refutes_baseline():
        doc = refuted()
        doc["provenance"]["authors"] = ["Kitaev"]
        return doc
    run_case("pure refutation of a baseline still accepted (exempt)",
             refutes_baseline, True, base_doc=BASELINE)

    print("\nrename detection (a real refutation is ~98% similar, which git "
          "folds\ninto an R line unless the gate splits renames):")
    BIG = copy.deepcopy(BASE_DOC)
    BIG["checks"]["X"] = [[i, i + 1, i + 2] for i in range(500)]

    def refuted_big():
        doc = copy.deepcopy(BIG)
        doc["name"] = "[[60,8,5]] synthetic test code"
        doc["schema_version"] = "0.2"
        doc["distance"]["X"] = {"value": 5, "confidence": "upper_bound",
                                "witness": [0, 1, 2, 3, 4],
                                "witness_provenance": {
                                    "found_by": ["@bob"],
                                    "date": "2026-08-19",
                                    "found_at_samples": 10 ** 9}}
        doc["distance"]["d"] = 5
        doc["provenance"]["notes"] += " Refuted."
        return doc
    run_case("high-similarity rename: clean refutation still binds",
             refuted_big, True, base_doc=BIG)

    def refuted_big_tampered():
        doc = refuted_big()
        doc["provenance"]["authors"] = ["@bob"]
        return doc
    run_case("high-similarity rename: tampered refutation still caught",
             refuted_big_tampered, False, base_doc=BIG)

    print("\nlayout binding (first locality block):")
    LAYOUT = {"coordinates": [[float(i), 0.0] for i in range(60)], "layers": 2,
              "contributed_by": {"by": ["@bob"], "date": "2026-08-20"}}

    def adds_layout(base=BASE_DOC, credit=True):
        doc = copy.deepcopy(base)
        doc["locality"] = copy.deepcopy(LAYOUT)
        if not credit:
            del doc["locality"]["contributed_by"]
        doc["schema_version"] = "0.2"
        doc["name"] += ", two-layer layout"
        doc["provenance"]["notes"] += " Layout added."
        return doc
    run_case("layout addition credited in contributed_by binds",
             adds_layout, True, rename=False)
    run_case("layout addition on a no-handle baseline binds",
             lambda: adds_layout(base=BASELINE), True, rename=False,
             base_doc=BASELINE)

    def layout_no_credit():
        return adds_layout(credit=False)
    run_case("layout addition without contributed_by credit rejected",
             layout_no_credit, False, rename=False)

    def layout_wrong_credit():
        doc = adds_layout()
        doc["locality"]["contributed_by"]["by"] = ["@carol"]
        return doc
    run_case("layout addition crediting someone else rejected",
             layout_wrong_credit, False, rename=False)

    def layout_appends_author():
        doc = adds_layout()
        doc["provenance"]["authors"] = (
            list(doc["provenance"]["authors"]) + ["@bob"])
        return doc
    run_case("layout addition that also appends to authors rejected",
             layout_appends_author, False, rename=False)

    def layout_sets_model():
        doc = adds_layout()
        doc["provenance"]["model"] = "TestModel 1.0"
        return doc
    run_case("layout addition that also sets model rejected",
             layout_sets_model, False, rename=False)

    def layout_touches_checks():
        doc = adds_layout()
        doc["checks"]["X"] = [[0, 1, 3]]
        return doc
    run_case("layout addition that also edits checks rejected",
             layout_touches_checks, False, rename=False)

    def layout_touches_distance():
        doc = adds_layout()
        doc["distance"]["X"]["value"] = 5
        doc["distance"]["X"]["witness"] = [0, 1, 2, 3, 4]
        doc["distance"]["d"] = 5
        return doc
    run_case("layout addition that also edits distance rejected",
             layout_touches_distance, False, rename=False)

    def layout_rewrites_notes():
        doc = adds_layout()
        doc["provenance"]["notes"] = "Mine now."
        return doc
    run_case("layout addition that rewrites notes rejected",
             layout_rewrites_notes, False, rename=False)

    HAS_LAYOUT = copy.deepcopy(BASE_DOC)
    HAS_LAYOUT["locality"] = {"coordinates": LAYOUT["coordinates"],
                              "layers": 2}

    def layout_replaces():
        doc = copy.deepcopy(HAS_LAYOUT)
        doc["schema_version"] = "0.2"
        doc["locality"] = copy.deepcopy(LAYOUT)
        doc["locality"]["layers"] = 1
        doc["provenance"]["notes"] += " Better layout."
        return doc
    run_case("replacing an existing layout rejected",
             layout_replaces, False, rename=False, base_doc=HAS_LAYOUT)

    print("\nmerged-state escalation (the author list is the privilege "
          "boundary;\na merged binding must not widen the contributor's "
          "rights on the next PR):")

    def merged_state_case(name, followup_edit, expect_ok, merged_doc=None):
        with tempfile.TemporaryDirectory() as td:
            make_repo(td)                       # base on main, branch 'change'
            git(td, "checkout", "-q", "main")   # merge the binding into main
            write_code(td, "60-8-6.json", merged_doc or adds_layout())
            git(td, "add", "codes")
            git(td, "commit", "-q", "-m", "layout binding merged")
            git(td, "checkout", "-q", "-b", "followup")
            write_code(td, "60-8-6.json", followup_edit())
            git(td, "add", "codes")
            git(td, "commit", "-q", "-m", "followup")
            rc = check_authorship.main(
                ["--author", "bob", "--root", td, "--base", "main"])
            check(name, (rc == 0) == expect_ok)

    def bob_rewrites_after_merge():
        doc = adds_layout()
        doc["checks"]["X"] = [[0, 1, 3]]
        doc["distance"]["X"]["value"] = 9
        doc["distance"]["d"] = 7
        doc["provenance"]["construction"] = "bob's construction"
        return doc
    merged_state_case("after a merged layout binding, @bob still cannot "
                      "edit the code", bob_rewrites_after_merge, False)

    def bob_refutes_after_merge():
        doc = adds_layout()
        doc["name"] = "[[60,8,5]] synthetic test code, two-layer layout"
        doc["distance"]["X"] = {
            "value": 5, "confidence": "upper_bound",
            "witness": [0, 1, 2, 3, 4],
            "witness_provenance": {"found_by": ["@bob"],
                                   "date": "2026-08-20",
                                   "found_at_samples": 10 ** 9}}
        doc["distance"]["d"] = 5
        doc["provenance"]["notes"] += " Refuted."
        return doc
    merged_state_case("after a merged layout binding, a clean refutation "
                      "by @bob still binds", bob_refutes_after_merge, True)

    print("\nmalformed input:")
    missing_side = copy.deepcopy(BASE_DOC)
    del missing_side["distance"]["Z"]
    ok, why = check_authorship.refutation_binding(
        "bob", BASE_DOC, missing_side)
    check("missing side named in the rejection reason",
          not ok and "distance.Z is missing" in why)

    print("\nplain submissions (original binding):")
    def new_code():
        return copy.deepcopy(BASE_DOC)
    with tempfile.TemporaryDirectory() as td:
        make_repo(td)
        write_code(td, "61-9-6.json", new_code())
        git(td, "add", "codes")
        git(td, "commit", "-q", "-m", "new")
        rc = check_authorship.main(
            ["--author", "bob", "--root", td, "--base", "main"])
        check("new code by non-author still rejected", rc == 1)
        rc = check_authorship.main(
            ["--author", "alice", "--root", td, "--base", "main"])
        check("new code by its author still accepted", rc == 0)

    print("\nnew submissions must bind to a @handle:")

    # a genuinely new file (the base code stays, so nothing pairs it with a
    # base counterpart the way a rename would)
    def submit_new(td, authors, origin=None):
        doc = copy.deepcopy(BASE_DOC)
        doc["provenance"]["authors"] = authors
        if origin:
            doc["provenance"]["origin"] = origin
        write_code(td, "60-8-7.json", doc)
        git(td, "add", "codes")
        git(td, "commit", "-q", "-m", "new")
        return check_authorship.main(
            ["--author", "bob", "--root", td, "--base", "main"])

    with tempfile.TemporaryDirectory() as td:
        make_repo(td)
        check("new submission with no @handle rejected",
              submit_new(td, ["Jane Roe"]) == 1)
    with tempfile.TemporaryDirectory() as td:
        make_repo(td)
        check("new baseline submission with no @handle exempt",
              submit_new(td, ["Jane Roe"], origin="baseline") == 0)
    with tempfile.TemporaryDirectory() as td:
        make_repo(td)
        check("new submission with only a malformed handle rejected",
              submit_new(td, ["@bad!handle"]) == 1)

    print()
    if _fail:
        print(f"FAILED: {_fail}")
        return 1
    print("ok")
    return 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())

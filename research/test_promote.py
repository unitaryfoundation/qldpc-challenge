"""Tests for the submission-bundle assembler.

The module writes what a reviewer reads and what CI gates, so the properties
that matter are the ones a campaign's throwaway glue kept getting wrong
(issue #2328):

  * the report is a contract, not prose: a caller decides on ``ok`` and
    ``blocked_by`` and never parses a printed line;
  * the generated body passes ``verify/check_prose.py``'s scaffolding rule on
    a FRESH draft, which is exactly what ``./qldpc submit --open-pr`` cannot
    do, and the equivalence box is decided from the gate's own dedup rather
    than ticked to get past the checker;
  * reusing a validated witness instead of re-searching is refused unless the
    ladder already bought the depth the re-search would have, so the speedup
    never becomes a relaxation;
  * the note and the document cannot disagree, because both are rendered from
    one record.

The end-to-end test points the gate at an empty board directory so the run is
about this module and not about what happens to be on the board that day; the
verifier and its refutation are the real ones throughout.
"""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit"))
import escalation as E  # noqa: E402
import promote as P  # noqa: E402
from bb import KNOWN, build_bb  # noqa: E402
from submit import make_submission  # noqa: E402

ROOT = P._ROOT

# A settled ladder: the screen reads high, two fresh deep rungs agree at 6.
SETTLED = [{"trials": 20_000, "d": 8, "label": "screen"},
           {"trials": 1_000_000, "d": 6},
           {"trials": 2_000_000, "d": 6}]


def _evidence(**over):
    ev = {
        "headline": "bivariate bicycle on the 6 x 6 torus",
        "direction": "A weight-6 unrestricted cell with room at small n; the "
                     "torus family is the cheapest thing that lands there.",
        "searched": "40 sampled torus pairs screened at 120 RIS trials per "
                    "side, one carried forward.",
        "ladder": list(SETTLED),
        "frontier": "Fills a weight-6 unrestricted cell the board does not "
                    "carry at this blocklength.",
        "reproduction": "build_bb(6, 6, A, B) with the monomials recorded in "
                        "`research/kit/bb.py` under KNOWN.",
        "construction": "Bivariate bicycle on Z_6 x Z_6.",
        "dead_ends": ["Even lifts produced k = 0."],
        "tools": {"harness": "pytest", "modules": ["research/kit/bb.py"],
                  "compute": "seconds"},
    }
    ev.update(over)
    return {k: v for k, v in ev.items() if v is not None}


def _doc():
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    return make_submission(HX, HZ, name="[[72,12,6]] test", authors=["@tester"],
                           construction="Bivariate bicycle on Z_6 x Z_6.",
                           family="bivariate-bicycle", trials=1000)


@pytest.fixture(autouse=True)
def small_board(monkeypatch):
    """Compare against a fixed stand-in board rather than the live one.

    ``cli.frontier_summary`` is the board's own frontier code and runs
    unchanged here; handing it a fixed board keeps these tests about the bundle
    and off the several-thousand-entry structural pass the real one costs.
    """
    board = [{"slug": "80-4-8", "n": 80, "k": 4, "d": 8, "code_type": "CSS",
              "eff": 3.2, "w": 6, "locality_class": "unrestricted",
              "weight_class": "weight-6"}]
    monkeypatch.setattr(P.cli, "_load_board_entries", lambda: list(board))
    return board


def _farm(tmp_path):
    """Build a repo-shaped root for one bundle.

    The real verify/, research/ and site/ are linked in so a citation resolves
    against them, and codes/ and notes/ are fresh directories so nothing is
    written near the board.
    """
    root = tmp_path / "root"
    root.mkdir()
    for name in ("verify", "research", "site", "schema", "cli", "fieldnotes",
                 "docs", "decode", "certs", "circuits"):
        src = os.path.join(ROOT, name)
        if os.path.isdir(src):
            os.symlink(src, root / name)
    (root / "codes").mkdir()
    (root / "notes").mkdir()
    return str(root)


# ---------------------------------------------------------------- the ladder
def test_flat_rung_count_matches_the_escalation_gate():
    """Pin the two readings of a ladder to each other.

    A note and a budget decision must not disagree about whether a bound
    settled.
    """
    for ladder in (SETTLED,
                   [(20_000, 8), (100_000, 7), (1_000_000, 6)],
                   [(20_000, 6), (500_000, 6), (1_000_000, 6), (2_000_000, 6)]):
        facts = P.ladder_facts(ladder, claimed_d=min(r[1] if isinstance(r, tuple)
                                                     else r["d"] for r in ladder))
        brief = E.rung_brief(72, 12, ladder, bar=1.0)
        assert (facts["flat_fresh_rungs_at_best"]
                == brief["facts"]["flat_fresh_rungs_at_best"])
        assert (facts["cumulative_best_bound"]
                == brief["facts"]["cumulative_best_bound"])
        assert facts["trials_spent"] == brief["facts"]["trials_spent"]


def test_settled_ladder_clears_the_reuse_floor():
    facts = P.ladder_facts(SETTLED, claimed_d=6)
    assert P.ladder_blockers(facts, P.DEFAULT_MIN_DEEP_TRIALS) == []
    assert facts["deepest_fresh_trials"] == 2_000_000
    assert facts["flat_fresh_rungs_at_best"] == 2


def test_shallow_ladder_is_refused():
    """Refuse a screen-only ladder.

    Skipping the re-search is only sound if the ladder already paid for the
    depth.
    """
    facts = P.ladder_facts([(20_000, 6)], claimed_d=6)
    why = " ".join(P.ladder_blockers(facts, P.DEFAULT_MIN_DEEP_TRIALS))
    assert "deepest fresh-seed rung" in why
    assert "qldpc submit" in why


def test_unsettled_ladder_is_refused():
    ladder = [(1_000_000, 8), (2_000_000, 6)]
    facts = P.ladder_facts(ladder, claimed_d=6)
    why = " ".join(P.ladder_blockers(facts, P.DEFAULT_MIN_DEEP_TRIALS))
    assert f"{E.MIN_FLAT_RUNGS} are required" in why


def test_ladder_reading_below_the_claim_is_refused():
    """Refuse a document the ladder already knows better than.

    This is the 888-226-20 -> 888-226-18 shape.
    """
    facts = P.ladder_facts(SETTLED, claimed_d=8)
    why = " ".join(P.ladder_blockers(facts, P.DEFAULT_MIN_DEEP_TRIALS))
    assert "the document claims d = 8" in why
    assert facts["reads_below_claim"]


def test_a_rung_the_escalation_gate_would_reject_is_rejected_here():
    with pytest.raises(ValueError):
        P.ladder_facts([(0, 6)], claimed_d=6)


# ------------------------------------------------------------------ the note
def test_note_states_its_own_nkd_first_and_renders_the_ladder():
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    md = P.note_markdown(doc, _evidence(), facts)
    assert md.splitlines()[0].startswith(f"# [[{doc['n']},{doc['k']},"
                                         f"{doc['distance']['d']}]]")
    for heading in ("## Direction & hypothesis", "## What was searched",
                    "## Evidence trail", "## Dead ends", "## Tools",
                    "## Reproduction"):
        assert heading in md
    assert "| 2,000,000 | 6 |" in md
    assert "| 20,000 (screen) | 8 |" in md
    assert len(md.encode()) <= P.NOTE_CAP_BYTES


def test_note_is_hard_wrapped_like_the_notes_on_the_board():
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    long_para = ("A paragraph long enough to need wrapping. " * 8).strip()
    md = P.note_markdown(doc, _evidence(direction=long_para), facts)
    prose = [ln for ln in md.splitlines()
             if ln and not ln.startswith(("|", "    ", "#", "```"))]
    assert max(len(ln) for ln in prose) <= P.NOTE_WIDTH
    assert long_para.split(". ")[0] + "." in " ".join(prose)


def test_note_leaves_fenced_code_alone():
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    fenced = "Rebuild it with:\n\n```\n" + "x = " + "1" * 120 + "\n```"
    md = P.note_markdown(doc, _evidence(reproduction=fenced), facts)
    assert "x = " + "1" * 120 in md.splitlines()


def test_note_carries_the_peer_audit_when_one_was_run():
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    ev = _evidence(peer_audit={"decision": "credible: both claims held",
                               "trials": 2_000_000, "seeds": [51, 52]})
    flat = " ".join(P.note_markdown(doc, ev, facts).split())
    assert "credible: both claims held" in flat
    assert "2,000,000 trials" in flat
    assert "research/audits/leader_audit.py" in flat


def test_note_model_line_follows_provenance():
    doc = _doc()
    doc["provenance"]["model"] = "Claude Opus 4.8"
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    assert "Claude Opus 4.8" in P.note_markdown(doc, _evidence(), facts)


# ------------------------------------------------------------------ the body
def _verdict(dedup):
    return {"passed": True, "gates": {"dedup": dedup}, "labels": []}


def test_equivalence_box_is_ticked_from_the_gates_own_dedup():
    ticked, reason = P.equivalence_finding(
        _verdict({"exact_duplicate_of": None, "wl_equivalent_of": None}), _doc())
    assert ticked
    assert "fingerprint" in reason


def test_wl_equivalent_peer_without_a_note_is_a_blocker():
    ticked, reason = P.equivalence_finding(
        _verdict({"exact_duplicate_of": None, "wl_equivalent_of": "72-12-6.json"}),
        _doc())
    assert not ticked
    assert "72-12-6.json" in reason


def test_wl_equivalent_peer_with_a_note_is_ticked():
    doc = _doc()
    doc["provenance"]["notes"] = "Compared against 72-12-6.json; different code."
    ticked, reason = P.equivalence_finding(
        _verdict({"exact_duplicate_of": None, "wl_equivalent_of": "72-12-6.json"}),
        doc)
    assert ticked
    assert "provenance.notes" in reason


def test_fresh_body_carries_no_scaffolding_the_prose_gate_rejects():
    """Clear the scaffolding rule on a fresh draft.

    ``./qldpc submit --open-pr`` cannot, because it always emits an unticked
    box.
    """
    sys.path.insert(0, os.path.join(ROOT, "verify"))
    import check_prose

    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    report = P.qldpc_verify.verify(doc, refute=False)
    body = P.pr_body(doc, report,
                     _verdict({"exact_duplicate_of": None,
                               "wl_equivalent_of": None}),
                     _evidence(), facts,
                     code_rel="codes/72-12-6.json", note_rel="notes/72-12-6.md")
    for why, pat in check_prose.SCAFFOLDING:
        assert not pat.search(body), why
    assert "- [x] If this may be equivalent" in body
    assert "2,000,000 RIS trials per side" in body


def test_body_carries_the_boards_own_frontier_lines():
    """Carry the board's own frontier bullets.

    They are ``cli.frontier_summary``'s output, not a second opinion about the
    board.
    """
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    report = P.qldpc_verify.verify(doc, refute=False)
    body = P.pr_body(doc, report, _verdict({"exact_duplicate_of": None,
                                            "wl_equivalent_of": None}),
                     _evidence(), facts,
                     code_rel="codes/72-12-6.json", note_rel="notes/72-12-6.md")
    assert "Pareto frontier" in body
    assert _evidence()["frontier"] in body


def test_body_states_the_search_depth_behind_the_claim():
    doc = _doc()
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    report = P.qldpc_verify.verify(doc, refute=False)
    body = P.pr_body(doc, report, _verdict({"exact_duplicate_of": None,
                                            "wl_equivalent_of": None}),
                     _evidence(), facts,
                     code_rel="codes/72-12-6.json", note_rel="notes/72-12-6.md")
    assert "Search behind the claim" in body
    assert "literature novelty is unverified" in body


def test_title_and_note_header_carry_one_description():
    doc = _doc()
    ev = _evidence()
    title = P.bundle_title(doc, ev)
    assert title == f"Add [[72,12,6]] {ev['headline']}"
    facts = P.ladder_facts(SETTLED, doc["distance"]["d"])
    assert P.note_markdown(doc, ev, facts).startswith(f"# [[72,12,6]] "
                                                      f"{ev['headline']}")


def test_title_falls_back_to_the_clis_descriptor():
    doc = _doc()
    long_head = "a headline far too long to sit in a pull request title " * 2
    title = P.bundle_title(doc, _evidence(headline=long_head))
    assert title.startswith("Add [[72,12,6]] ")
    assert long_head not in title


# ------------------------------------------------------------- the contract
def test_check_prose_command_matches_what_ci_runs():
    cmd = P.check_prose_cmd("/repo", "/tmp/body.md",
                            ["codes/a.json", "notes/a.md"], pr_author="@vprusso")
    assert cmd[-2:] == ["--pr-author", "vprusso"]
    assert "--body-file" in cmd and "/tmp/body.md" in cmd
    assert P.check_prose_cmd("/repo", "/tmp/body.md", [])[-1] == "--files"


def test_commands_open_one_pr_per_code():
    cmds = P._git_commands("72-12-6", "Add [[72,12,6]]", "codes/72-12-6.json",
                           "notes/72-12-6.md", "/tmp/body.md")
    assert cmds[0] == "git checkout -b submit-72-12-6 main"
    assert cmds[1] == "git add codes/72-12-6.json notes/72-12-6.md"
    assert any(c.startswith("verify/prepush_prose_check.sh") for c in cmds)
    assert any(c.startswith("gh pr create") for c in cmds)
    # exactly one code file staged, so check_submission_scope.py's one-new-code
    # rule holds for a batch without the batch knowing about it
    assert cmds[1].count("codes/") == 1


def test_missing_evidence_blocks_before_anything_runs():
    rep = P.promote(_doc(), _evidence(direction=None), write=False)
    assert rep["ok"] is False
    assert any("evidence.direction" in b for b in rep["blocked_by"])
    assert rep["gates"] == {}


def test_candidate_without_a_witness_is_refused():
    doc = _doc()
    del doc["distance"]
    rep = P.promote(doc, _evidence(), write=False)
    assert any("no distance block" in b for b in rep["blocked_by"])


def test_unknown_evidence_key_is_refused():
    ev = _evidence()
    ev["laddr"] = []
    rep = P.promote(_doc(), ev, write=False)
    assert any("unknown evidence key" in b for b in rep["blocked_by"])


def test_placeholder_construction_is_refused():
    doc = _doc()
    doc["provenance"]["construction"] = P._CLI_DEFAULT_CONSTRUCTION
    rep = P.promote(doc, _evidence(construction=None), write=False)
    assert any("provenance.construction" in b for b in rep["blocked_by"])


def test_model_disagreement_between_note_and_provenance_is_refused():
    doc = _doc()
    doc["provenance"]["model"] = "Claude Opus 4.8"
    rep = P.promote(doc, _evidence(tools={"model": "MiMo-V2.6-Flash"}),
                    write=False)
    assert any("disagree" in b for b in rep["blocked_by"])


def test_script_skips_bundles_that_are_not_ready():
    ready = {"ok": True, "title": "Add [[72,12,6]]", "slug": "72-12-6",
             "body_file": "/tmp/body.md",
             "commands": ["git checkout -b submit-72-12-6 main"]}
    blocked = {"ok": False, "slug": "80-4-8", "blocked_by": ["ladder too shallow"]}
    script = P.script_for([ready, blocked])
    assert "git checkout -b submit-72-12-6 main" in script
    assert "# skipped 80-4-8: ladder too shallow" in script
    # a dry run has no body on disk, so it is never scripted either
    assert "# skipped 90-2-9: not ready" in P.script_for(
        [{"ok": True, "slug": "90-2-9", "commands": []}])
    assert "80-4-8" not in script.replace("# skipped 80-4-8: ladder too shallow", "")


# ------------------------------------------------------------------ end to end
@pytest.fixture
def empty_board(tmp_path, monkeypatch):
    """Point the gate's board read at an empty directory.

    Dedup and novelty are then vacuous, which is what makes this test about the
    assembler rather than about today's board. The verifier and its refutation
    are untouched.
    """
    board = tmp_path / "board"
    board.mkdir()
    monkeypatch.setattr(P.gate, "_CODES", str(board))
    return str(board)


def test_bundle_is_assembled_gated_and_written(tmp_path, empty_board):
    root = _farm(tmp_path)
    rep = P.promote(_doc(), _evidence(), root=root, authors=["@tester"],
                    body_dir=str(tmp_path / "bodies"), seed=7)
    assert rep["ok"], rep["blocked_by"]
    assert rep["schema"] == P.REPORT_SCHEMA
    assert rep["slug"] == "72-12-6"
    assert rep["branch"] == "submit-72-12-6"
    assert rep["files"] == {"code": "codes/72-12-6.json",
                            "note": "notes/72-12-6.md"}
    assert rep["gates"]["validate_candidate"]["passed"]
    assert rep["gates"]["check_prose"]["ok"], rep["gates"]["check_prose"]["output"]

    written = json.load(open(os.path.join(root, rep["files"]["code"])))
    assert written["provenance"]["authors"] == ["@tester"]
    assert written["provenance"]["search_budget"]["ris_trials_per_side"] == 2_000_000
    assert written["schema_version"] >= "0.3"
    note = open(os.path.join(root, rep["files"]["note"])).read()
    assert note.startswith("# [[72,12,6]] ")
    assert os.path.exists(rep["body_file"])
    assert [i["item"] for i in rep["needs_human"]]


def test_written_bundle_passes_the_real_verifier_on_disk(tmp_path, empty_board):
    root = _farm(tmp_path)
    rep = P.promote(_doc(), _evidence(), root=root, authors=["@tester"],
                    body_dir=str(tmp_path / "bodies"), seed=7)
    assert rep["ok"], rep["blocked_by"]
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, "verify", "qldpc_verify.py"),
         os.path.join(root, rep["files"]["code"])],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_existing_board_slug_is_not_overwritten(tmp_path, empty_board):
    root = _farm(tmp_path)
    kw = dict(root=root, authors=["@tester"], body_dir=str(tmp_path / "bodies"),
              seed=7)
    assert P.promote(_doc(), _evidence(), **kw)["ok"]
    again = P.promote(_doc(), _evidence(), **kw)
    assert not again["ok"]
    assert any("already exists" in b for b in again["blocked_by"])
    assert P.promote(_doc(), _evidence(), force=True, **kw)["ok"]


def test_plan_file_drives_a_batch(tmp_path, empty_board):
    root = _farm(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"candidate": _doc(), "evidence": _evidence()}]))
    plans = P.load_plan(str(plan))
    reports = P.promote_all(plans, root=root, authors=["@tester"],
                            body_dir=str(tmp_path / "bodies"), seed=7)
    assert len(reports) == 1 and reports[0]["ok"], reports[0]["blocked_by"]
    script = P.script_for(reports)
    assert "gh pr create" in script
    assert "git checkout -b submit-72-12-6" in script


# --------------------------------------------- the reproduction manifest (#2955)
#
# A candidate staged with `save_submission(doc, path, spec=...)` carries its
# recipe beside it, and the bundle turns that into `repro/<slug>.json` for the
# committed entry. Pinned here: the manifest binds the committed file, its
# construction stage runs the recipe, the git commands and the PR body carry
# it, a spec without a recipe gives an honest manifest, and a candidate
# without a spec gets no manifest at all. No PR author is passed: with one,
# check_prose diffs fieldnotes/ against origin/main, and the farm is not a
# git repository.

RECIPE_72 = {"constructor": "bb.build_bb",
             "params": {"l": 6, "m": 6, "A_terms": [[3, 0], [0, 1], [0, 2]],
                        "B_terms": [[0, 3], [1, 0], [2, 0]]},
             "family": "bivariate-bicycle"}


def _passing_verdict(doc, seed=None, **kw):
    """Return a gate verdict shaped like the real one, for a code the board already holds."""
    return {"passed": True,
            "labels": ["advances the weight-6 x unrestricted board",
                       "literature novelty UNVERIFIED"],
            "gates": {"verify": {"ok": True, "failed_checks": []},
                      "refute": {"refuted": False, "seed": 1, "detail": "none"},
                      "dedup": {"exact_duplicate_of": None, "wl_equivalent_of": None},
                      "novelty": {"board_advancing": True, "advances_by": ["n"],
                                  "d_only_gain": False, "d_only_peers": [],
                                  "dominated_by": []}},
            "validator": {"source_sha256": "test", "seed": 1}}


def test_a_recipe_becomes_a_manifest_bound_to_the_committed_file(tmp_path, monkeypatch):
    import hashlib

    import rebuild
    monkeypatch.setattr(P.gate, "validate_candidate", _passing_verdict)
    root = _farm(tmp_path)
    rep = P.promote(_doc(), _evidence(), recipe=RECIPE_72, root=root,
                    body_dir=str(tmp_path / "bodies"))
    assert rep["ok"], rep["blocked_by"]
    repro_rel = rep["files"]["repro"]
    assert repro_rel == os.path.join("repro", "72-12-6.json")
    with open(os.path.join(root, repro_rel), encoding="utf-8") as f:
        m = json.load(f)
    c = m["stages"]["construction"]
    assert c["status"] == "applicable" and c["args"][:2] == ["--constructor", "bb.build_bb"]
    assert m["spec_context"] == {"family": "bivariate-bicycle"}
    with open(os.path.join(root, rep["files"]["code"]), "rb") as f:
        assert m["artifact_sha256"] == hashlib.sha256(f.read()).hexdigest()
    # the recipe rebuilds the committed code, so `qldpc reproduce --construction` will match
    HX, HZ = rebuild.rebuild(RECIPE_72["constructor"], RECIPE_72["params"])
    with open(os.path.join(root, rep["files"]["code"]), encoding="utf-8") as f:
        assert rebuild.fingerprint_of(HX, HZ) == P.qldpc_verify.verify(json.load(f))["fingerprint"]
    add = next(cmd for cmd in rep["commands"] if cmd.startswith("git add "))
    assert add == f"git add codes/72-12-6.json notes/72-12-6.md {repro_rel}"
    with open(rep["body_file"], encoding="utf-8") as f:
        body = f.read()
    assert f"Reproduction manifest: `{repro_rel}`" in body
    assert "./qldpc reproduce 72-12-6 --construction" in body
    assert rep["gates"]["check_prose"]["ok"], rep["gates"]["check_prose"]


def test_a_spec_without_a_recipe_gives_an_honest_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(P.gate, "validate_candidate", _passing_verdict)
    root = _farm(tmp_path)
    rep = P.promote(_doc(), _evidence(), recipe={"note": "hand-built"}, root=root,
                    body_dir=str(tmp_path / "bodies"))
    assert rep["ok"], rep["blocked_by"]
    with open(os.path.join(root, rep["files"]["repro"]), encoding="utf-8") as f:
        assert json.load(f)["stages"]["construction"]["status"] == "not_reproducible"
    with open(rep["body_file"], encoding="utf-8") as f:
        assert "declared not reproducible" in f.read()


def test_without_a_recipe_no_manifest_is_written(tmp_path, monkeypatch):
    monkeypatch.setattr(P.gate, "validate_candidate", _passing_verdict)
    root = _farm(tmp_path)
    rep = P.promote(_doc(), _evidence(), root=root,
                    body_dir=str(tmp_path / "bodies"))
    assert rep["ok"], rep["blocked_by"]
    assert "repro" not in rep["files"] and not os.path.exists(os.path.join(root, "repro"))
    assert "git add codes/72-12-6.json notes/72-12-6.md" in rep["commands"]
    with open(rep["body_file"], encoding="utf-8") as f:
        assert "Reproduction manifest" not in f.read()


def test_an_existing_manifest_blocks_without_force(tmp_path, monkeypatch):
    monkeypatch.setattr(P.gate, "validate_candidate", _passing_verdict)
    root = _farm(tmp_path)
    os.makedirs(os.path.join(root, "repro"))
    with open(os.path.join(root, "repro", "72-12-6.json"), "w", encoding="utf-8") as f:
        f.write("{}\n")
    rep = P.promote(_doc(), _evidence(), recipe=RECIPE_72, root=root, write=False)
    assert not rep["ok"] and any("repro/72-12-6.json already exists" in b for b in rep["blocked_by"])


def test_load_plan_reads_the_recipe_kept_beside_the_candidate(tmp_path):
    from submit import save_submission
    cand = _doc()
    save_submission(cand, str(tmp_path / "72-12-6.json"), spec=RECIPE_72)
    plan = tmp_path / "plan.json"
    with open(plan, "w", encoding="utf-8") as f:
        json.dump([{"candidate": "72-12-6.json", "evidence": _evidence()},
                   {"candidate": "72-12-6.json", "evidence": _evidence(),
                    "recipe": {"note": "the plan's own recipe wins"}},
                   {"candidate": cand, "evidence": _evidence()}], f)
    plans = P.load_plan(str(plan))
    assert [p[2] for p in plans] == [RECIPE_72, {"note": "the plan's own recipe wins"}, None]
    assert plans[0][0] == cand


def test_promote_all_takes_plans_with_or_without_a_recipe():
    seen = []

    def fake(cand, ev, *, recipe=None, **kw):
        seen.append(recipe)
        return {"ok": True}

    from unittest import mock
    with mock.patch.object(P, "promote", fake):
        P.promote_all([({}, {}), ({}, {}, RECIPE_72)])
    assert seen == [None, RECIPE_72]

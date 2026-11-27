"""The note stub `qldpc submit` stages without --note-file is seeded, not blank (issue #7384).

PR #7379 made the stub; this seeds its "What was searched" and "Evidence
trail" sections from the budget the --budget-* flags recorded and from the
document's own witness ladder, and the header's one-line description from
--name. What the run cannot know stays a TODO line, so a reviewer sees it.
"""

import argparse

import qldpc


def _args(**over):
    base = {"name": "", "construction": "", "family": "", "authors": ["@someone"], "model": "", "harness": ""}
    base.update(over)
    return argparse.Namespace(**base)


def _doc(budget=None, provenance=True, exact=False):
    conf = "exact" if exact else "upper_bound"
    doc = {
        "n": 72,
        "k": 12,
        "checks": {"X": [[0, 1, 2, 3, 4, 5]] * 30, "Z": [[0, 1, 2, 3, 4, 5]] * 30},
        "distance": {
            "d": 6,
            "X": {
                "value": 6,
                "confidence": conf,
                "witness": [0, 1, 2, 3, 4, 5],
                "witness_provenance": {
                    "found_by": ["@someone"],
                    "date": "2026-11-27",
                    "found_at_samples": 20000,
                    "survived_samples": 2000000,
                    "tool": "gf2_fast",
                    "seeds": [7, 8],
                },
            },
            "Z": {"value": 7, "confidence": conf, "witness": [0, 1, 2, 3, 4, 5, 6]},
        },
        "family": "bivariate-bicycle",
    }
    if provenance:
        doc["provenance"] = {
            "authors": ["@someone"],
            "construction": "Bivariate bicycle, l=6 m=6, A = x^3 + y + y^2. Screened by the kit funnel.",
            "model": "Claude Fable 5.1",
            "harness": "Claude Code",
        }
        if budget is not None:
            doc["provenance"]["search_budget"] = budget
    return doc


REPORT = {"computed": {"max_check_weight": 6, "weight_class": "weight-6", "locality_class": "unrestricted"}}


def test_every_template_section_is_present_and_the_header_names_the_code():
    md = qldpc.note_stub(_doc(), REPORT, _args(), "72-12-6")
    assert md.startswith("# [[72,12,6]] ")
    for section in (
        "## Direction & hypothesis",
        "## What was searched",
        "## Evidence trail",
        "## Dead ends",
        "## Tools",
        "## Reproduction",
    ):
        assert section in md, section


def test_the_header_takes_name_then_construction_then_a_default():
    assert "# [[72,12,6]] — the gross code" in qldpc.note_stub(_doc(), REPORT, _args(name="the gross code"), "s")
    # a --name that is only the parameters adds nothing, so the construction leads
    md = qldpc.note_stub(_doc(), REPORT, _args(name="[[72,12,6]]"), "s")
    assert md.splitlines()[0] == "# [[72,12,6]] — Bivariate bicycle, l=6 m=6, A = x^3 + y + y^2"
    bare = _doc()
    bare["provenance"]["construction"] = "contributed via qldpc submit"
    assert qldpc.note_stub(bare, REPORT, _args(), "s").splitlines()[0] == "# [[72,12,6]] — submitted via qldpc submit"


def test_the_budget_seeds_what_was_searched():
    budget = {
        "candidates_screened": 13200,
        "ris_trials_per_side": 1500,
        "cpu_hours": 12.5,
        "gpu_hours": 0,
        "wall_clock_hours": 1.25,
        "tool": "research/kit/search.py + gf2_fast",
        "llm_tokens": {"Claude Fable 5.1": 1800000},
        "notes": "the GPU figure is the ladder only",
    }
    md = qldpc.note_stub(_doc(budget=budget), REPORT, _args(), "s")
    searched = md.split("## What was searched\n\n")[1].split("\n\n## ")[0]
    assert "13,200 candidates were built and screened before this one." in searched
    assert "Screening ran to 1,500 RIS trials per side at the deepest." in searched
    assert "Search harness: research/kit/search.py + gf2_fast." in searched
    assert "Compute: 12 CPU core-hours, 0 GPU-hours, 1.2 h of wall clock." in searched
    assert "Model tokens: Claude Fable 5.1 1,800,000." in searched
    assert "Budget notes: the GPU figure is the ladder only" in searched
    # the numbers do not say what was tried, so that stays a TODO
    assert searched.rstrip().endswith("the screening method, and the seeds.") and "TODO" in searched
    tools = md.split("## Tools\n\n")[1].split("\n\n## ")[0]
    assert "Max check weight: 6." in tools and "Search harness: research/kit/search.py + gf2_fast." in tools
    assert "TODO" not in tools


def test_without_a_budget_the_sections_stay_todo():
    md = qldpc.note_stub(_doc(), REPORT, _args(), "s")
    searched = md.split("## What was searched\n\n")[1].split("\n\n## ")[0]
    assert searched == "TODO: constructions, sweep sizes, screening method, trial counts, seeds."
    tools = md.split("## Tools\n\n")[1].split("\n\n## ")[0]
    assert "TODO: tooling used" in tools


def test_the_witness_ladder_seeds_the_evidence_trail():
    md = qldpc.note_stub(_doc(), REPORT, _args(), "s")
    evidence = md.split("## Evidence trail\n\n")[1].split("\n\n## ")[0].splitlines()
    assert evidence[0] == (
        "X side: d_X <= 6 (upper_bound); lightest logical found has weight 6, "
        "found at 20,000 samples and survived 2,000,000 (gf2_fast, seeds 7, 8)."
    )
    assert evidence[1] == "Z side: d_Z <= 7 (upper_bound); lightest logical found has weight 7."
    assert evidence[2] == "The claim d = 6 is a witness-backed upper bound, not an exact value."
    assert evidence[3].startswith("TODO: near-miss candidates")
    exact = qldpc.note_stub(_doc(exact=True), REPORT, _args(), "s")
    assert "X side: d_X = 6 (exact)" in exact and "The claim d = 6 is certified exact." in exact


def test_the_cell_and_the_check_weight_come_from_the_verifier_report():
    md = qldpc.note_stub(_doc(), REPORT, _args(), "s")
    assert "Track cell as the verifier computed it: weight-6 x unrestricted." in md
    # without a report the weight is read off the checks and the cell line is left out
    md = qldpc.note_stub(_doc(), {}, _args(), "s")
    assert "Max check weight: 6." in md and "Track cell" not in md


def test_a_stabilizer_shaped_distance_block_is_handled():
    doc = _doc()
    doc["distance"] = {"d": 3, "P": {"value": 3, "confidence": "upper_bound", "witness": [1, 2, 3]}}
    md = qldpc.note_stub(doc, {}, _args(), "s")
    assert "P side: d_P <= 3 (upper_bound); lightest logical found has weight 3." in md
    assert "# [[72,12,3]]" in md

"""The `qldpc submit` PR body now auto-fills the "what frontier does this
advance?" section by reusing the site's computed-cell + Pareto logic. This
checks the helper that shapes a candidate into a board entry, and that the
summary runs against the real board without crashing and reports the candidate's
cells.

The frontier comparison is intentionally board-relative and read-only: it never
writes, and it degrades to an empty summary (leaving the PR body's TODO) if the
site builder cannot be imported.
"""

import json
import os
import sys

import qldpc  # noqa: E402
import qldpc_verify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_fail = []


def check(label, cond):
    print(f"  {'OK ' if cond else 'FAIL'} {label}")
    if not cond:
        _fail.append(label)


def main():
    # --- _entry_for shapes a candidate like the site's load_entries ---------
    doc = {
        "n": 98,
        "k": 6,
        "distance": {"d": 12, "X": {"value": 12}, "Z": {"value": 12}},
    }
    report = {
        "computed": {"max_check_weight": 6, "locality_class": "unrestricted", "weight_class": "weight-6"},
        "earned_distance": {"d": {"value": 12, "tier": "upper_bound"}},
    }
    e = qldpc._entry_for(doc, report)
    check("entry carries n/k/d", (e["n"], e["k"], e["d"]) == (98, 6, 12))
    check(
        "entry carries w and classes",
        (e["w"], e["locality_class"], e["weight_class"]) == (6, "unrestricted", "weight-6"),
    )
    check("eff = kd^2/n rounded", e["eff"] == round(6 * 12 * 12 / 98, 3))

    # --- frontier_summary runs against the real board -----------------------
    p = os.path.join(ROOT, "codes", "98-6-12.json")
    if os.path.exists(p):
        with open(p) as f:
            bdoc = json.load(f)
        brep = qldpc_verify.verify(bdoc, refute=False)
        check("board code verifies", brep["ok"])
        lines = qldpc.frontier_summary(bdoc, brep)
        check("summary reports at least one cell", len(lines) >= 1)
        check("summary lines mention a cell", any(" / " in ln for ln in lines))
    else:
        print("  (codes/98-6-12.json absent; skipping board-dependent checks)")

    # --- graceful degradation when the board is unavailable -----------------
    # _load_board_entries returns [] on import failure; frontier_summary then
    # returns [] so the PR body keeps its TODO rather than crashing.
    orig = qldpc._load_board_entries
    qldpc._load_board_entries = lambda: []
    try:
        lines = qldpc.frontier_summary(doc, report)
        check("empty board -> empty summary", lines == [])
    finally:
        qldpc._load_board_entries = orig

    print(f"\n{'PASS' if not _fail else 'FAIL: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


def test_main():
    """Pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())

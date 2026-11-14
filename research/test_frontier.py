"""The board-advancing rule as a refusal (issue #5700).

``kit/frontier.py`` is one rule for two packaging paths, so what is pinned here
is the rule itself: the gate's cell filter, dominance with one strict axis and
no dominance on a tie, the opt-in that clears a dominated code and nothing
else, and agreement with ``research/does_it_advance.py``, the other mirror of
the gate's novelty block.
"""
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, _HERE)

import does_it_advance  # noqa: E402
import frontier as F  # noqa: E402


def row(n, k, d, w, *, slug=None, lc="unrestricted", code_type="CSS"):
    return {"n": n, "k": k, "d": d, "w": w, "code_type": code_type,
            "weight_class": does_it_advance.weight_class(w), "locality_class": lc,
            "slug": slug or f"{n}-{k}-{d}"}


CAND = row(72, 12, 6, 6, slug="cand")


def test_an_entry_better_on_one_axis_and_no_worse_elsewhere_dominates():
    for better in (row(70, 12, 6, 6), row(72, 14, 6, 6), row(72, 12, 7, 6), row(72, 12, 6, 4)):
        assert F.dominators(CAND, [better]) == [F.describe(better)]


def test_a_tie_on_every_axis_is_not_dominance():
    twin = row(72, 12, 6, 6, slug="72-12-6-b")
    assert F.dominators(CAND, [twin]) == []
    assert F.blockers([], True) == []


def test_an_entry_worse_on_any_axis_does_not_dominate():
    for mixed in (row(60, 12, 5, 6), row(72, 16, 6, 8), row(80, 12, 8, 6)):
        assert F.dominators(CAND, [mixed]) == []


def test_only_a_cell_no_looser_than_the_candidates_is_a_rival():
    heavy = row(60, 20, 8, 10)                       # weight-9plus beats it on n, k, d
    assert not F.in_cell(CAND, heavy) and F.dominators(CAND, [heavy]) == []
    planar = row(60, 20, 8, 6, lc="local-2d-single")  # a stricter cell is a rival
    assert F.dominators(CAND, [planar]) == [F.describe(planar)]
    local_cand = dict(CAND, locality_class="local-2d-single")
    free = row(60, 20, 8, 6)                         # an unrestricted entry is not
    assert F.dominators(local_cand, [free]) == []


def test_the_stabilizer_board_and_the_css_board_do_not_mix():
    stab = row(60, 20, 8, 6, code_type="stabilizer")
    assert F.dominators(CAND, [stab]) == []
    assert F.dominators(dict(CAND, code_type="stabilizer"), [stab]) == [F.describe(stab)]


def test_a_row_without_a_weight_is_skipped_on_either_side():
    assert F.dominators(CAND, [dict(row(60, 20, 8, 6), w=None)]) == []
    assert F.dominators(dict(CAND, w=None), [row(60, 20, 8, 6)]) == []


def test_describe_matches_the_gates_wording_and_names_an_unslugged_row():
    assert F.describe(row(72, 6, 6, 6)) == "[[72,6,6]] w=6 72-6-6.json"
    assert F.describe({"n": 72, "k": 6, "d": 6, "w": 6, "name": "codes/72-6-6.json"}) \
        == "[[72,6,6]] w=6 72-6-6.json"
    assert F.describe({"n": 9, "k": 1, "d": 3, "w": 4}) == "[[9,1,3]] w=4 9-1-3.json"


def test_blockers_name_the_dominators_the_rule_and_the_opt_in():
    doms = ["[[72,12,7]] w=6 72-12-7.json"]
    block, = F.blockers(doms, False, attach="re-run with --allow-non-frontier")
    assert block.startswith("not board-advancing: dominated in its track cell by "
                            "[[72,12,7]] w=6 72-12-7.json")
    assert F.RULE in block and "non-frontier result" in block
    assert block.endswith("; re-run with --allow-non-frontier")
    block, = F.blockers([], False)
    assert "board_advancing: false" in block


def test_the_opt_in_clears_a_dominated_code_and_not_a_missing_label():
    doms = ["[[72,12,7]] w=6 72-12-7.json"]
    assert F.blockers(doms, False, allowed=True) == []
    block, = F.blockers([], None, allowed=True)
    assert "never decided" in block and "re-run verify/validate_candidate.py" in block
    assert F.blockers([], None) == F.blockers([], None, allowed=True)


def test_the_body_line_names_the_dominators_and_the_flag():
    line = F.body_line(["[[72,12,7]] w=6 72-12-7.json", "[[70,12,6]] w=6 70-12-6.json"])
    assert line.startswith("- Non-frontier result: dominated in its track cell by "
                           "[[72,12,7]] w=6 72-12-7.json, [[70,12,6]] w=6 70-12-6.json.")
    assert F.FLAG in line and "not as a frontier claim" in line


def test_within_batch_names_who_dominates_whom_and_keeps_ties():
    batch = [row(72, 12, 6, 6, slug="a"), row(72, 12, 7, 6, slug="b"),
             row(72, 12, 6, 6, slug="c"), row(90, 10, 6, 6, slug="d"),
             row(60, 20, 8, 10, slug="e")]
    out = F.within_batch(batch)
    # a and c tie and both lose to b; d loses to a, b, and c; e is in another cell
    assert set(out) == {0, 2, 3}
    assert out[0] == out[2] == ["[[72,12,7]] w=6 b.json"]
    assert out[3] == ["[[72,12,6]] w=6 a.json", "[[72,12,7]] w=6 b.json",
                      "[[72,12,6]] w=6 c.json"]
    assert F.within_batch([]) == {} and F.within_batch([batch[0]]) == {}


def test_the_rule_agrees_with_does_it_advance_on_random_boards():
    """Two mirrors of the gate's novelty block must not disagree with each other."""
    rng = random.Random(5700)
    classes = list(does_it_advance.LOCAL_ORDER)
    for _ in range(300):
        board = []
        for i in range(rng.randint(0, 12)):
            n = rng.randint(10, 40)
            k = rng.randint(1, 10)
            w = rng.choice([4, 6, 8, 12])
            board.append(dict(row(n, k, rng.randint(1, 8), w, slug=f"e{i}",
                                  lc=rng.choice(classes),
                                  code_type=rng.choice(["CSS", "stabilizer"])),
                              name=f"e{i}.json"))
        cand = row(rng.randint(10, 40), rng.randint(1, 10), rng.randint(1, 8),
                   rng.choice([4, 6, 8, 12]), lc=rng.choice(classes),
                   code_type=rng.choice(["CSS", "stabilizer"]))
        mirror = does_it_advance.novelty(board, cand["n"], cand["k"], cand["d"], cand["w"],
                                         code_type=cand["code_type"],
                                         lc=cand["locality_class"])
        assert sorted(F.dominators(cand, board)) == \
            sorted(F.describe(b) for b in mirror["dominated_by"])
        assert (not F.dominators(cand, board)) == mirror["board_advancing"]

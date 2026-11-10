"""The budget gate's locality mirror must agree with the verifier (fast tests).

``gate_changed._locality_rank`` re-derives the locality class to pick the
refutation budget, while ``site/build.py`` and ``validate_candidate`` read the
verifier's ``computed.locality_class``. The mirror historically omitted the
verifier's 1e-9 float tolerances and its planar-only rule; on the 2026-09-29
board that demoted 27 honest local-2d-bilayer entries to unrestricted and
flipped the record status of 17 of them -- 14 starred entries were refuted
with the fast pass instead of the deep battery.

Each fast test pins one of the verifier's classification rules, one per
historical divergence, by comparing the mirror against ``verify()`` itself on
a crafted fixture. The board-wide audit (all three frontier implementations,
every entry) lives in verify/board_frontier_audit.py and runs in the weekly
refute job, not here: a full structural pass over codes/ is minutes, and this
file stays in the PR gate at seconds.
"""
import copy
import json
import os

import gate_changed as G
import pytest
import qldpc_verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RANK_TO_CLASS = {0: "local-2d-single", 1: "local-2d-bilayer",
                 2: "unrestricted"}


def _fixture():
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        return json.load(f)


def _layout_doc(scale=1.0, layers=None, dim=2):
    """Return the fixture's layout, scaled/reshaped to target one rule."""
    doc = copy.deepcopy(_fixture())
    loc = doc["locality"]
    loc["coordinates"] = [([x * scale for x in c[:2]]
                           + [0.0] * (dim - 2)) for c in loc["coordinates"]]
    if layers is not None:
        loc["layers"] = layers
    return doc


def _assert_mirror_matches_verifier(doc, expected=None):
    want = qldpc_verify.verify(doc, refute=False)["computed"]["locality_class"]
    got = RANK_TO_CLASS[G._locality_rank(doc)]
    assert got == want, f"_locality_rank says {got}, verifier says {want}"
    if expected is not None:
        assert want == expected, f"fixture drifted: verifier says {want}"


def test_mirror_accepts_honest_layout():
    # baseline: the fixture is an honest local-2d-bilayer layout
    _assert_mirror_matches_verifier(_layout_doc(),
                                    expected="local-2d-bilayer")


def test_mirror_accepts_float_noise_on_unit_spacing():
    # spacing computes to 1.0 - 1e-12: honest to the verifier (within 1e-9),
    # and must not demote to unrestricted here -- this was the 27-entry bug
    _assert_mirror_matches_verifier(_layout_doc(scale=1 - 1e-12),
                                    expected="local-2d-bilayer")


def test_mirror_rejects_subunit_spacing():
    _assert_mirror_matches_verifier(_layout_doc(scale=0.5),
                                    expected="unrestricted")


def test_mirror_rejects_crammed_sites():
    # layers=1 with 2 qubits per site fails the verifier's occupancy rule,
    # so no class is earned even though the radius fits every cap
    _assert_mirror_matches_verifier(_layout_doc(layers=1),
                                    expected="unrestricted")


def test_mirror_requires_planar_layout():
    # an honest 3D layout is unrestricted by the verifier's rule (the 2d
    # classes need planar coordinates) and must rank the same here
    _assert_mirror_matches_verifier(_layout_doc(dim=3),
                                    expected="unrestricted")


@pytest.mark.board
def test_mirror_matches_the_verifier_on_a_board_sample():
    # spot-check real layouts the fixtures may not resemble; the exhaustive
    # per-entry comparison is the weekly audit's job
    codes = os.path.join(ROOT, "codes")
    try:
        slugs = sorted(os.path.splitext(f)[0] for f in os.listdir(codes)
                       if f.endswith(".json"))
    except OSError:
        pytest.skip("codes/ is not present")
    if not slugs:
        pytest.skip("codes/ is empty")
    sample = slugs[::max(1, len(slugs) // 20)][:20]
    bad = []
    for slug in sample:
        with open(os.path.join(codes, slug + ".json")) as f:
            doc = json.load(f)
        rep = qldpc_verify.verify(doc, refute=False)
        want = rep["computed"].get("locality_class", "unrestricted")
        got = RANK_TO_CLASS[G._locality_rank(doc)]
        if got != want:
            bad.append(f"{slug}: _locality_rank={got}, verifier={want}")
    assert not bad, ("_locality_rank diverges from the verifier:\n  "
                     + "\n  ".join(bad))

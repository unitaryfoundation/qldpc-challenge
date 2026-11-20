"""The equivalence checklist box must not be answered by the candidate itself.

`qldpc submit` writes ``codes/<slug>.json`` and only then asks
``board_dedup`` whether the code is already on the board. Before the fix that
comparison included the file the run had just written, so every submission
matched itself on its own fingerprint: the box came out unticked naming
``<slug>.json``, and ``verify/check_prose.py`` -- which rejects an unticked box
-- refused the push. An unedited ``--open-pr`` draft could never complete.

These tests pin the two halves of the fix:

* the candidate's own entry is excluded, so a fresh run reports no match and
  the box is ticked with the evidence;
* a genuinely equivalent entry under a *different* name is still reported, so
  the exclusion does not become a way to file the same code twice.
"""

import os

import numpy as np
import pytest
import qldpc

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _steane():
    H = np.array([[1, 0, 1, 0, 1, 0, 1], [0, 1, 1, 0, 0, 1, 1], [0, 0, 0, 1, 1, 1, 1]], dtype=np.uint8)
    return H.copy(), H.copy()


def _board_entry(name, fps, sigs):
    return {
        "name": name,
        "fingerprint": next(iter(fps)),
        "sig": next(iter(sigs)),
        "css_fingerprints": [],
        "css_sigs": [],
    }


@pytest.fixture
def dedup_env(monkeypatch):
    """Pin the board the dedup sees and the identities the candidate has."""
    state = {"board": []}
    fps, sigs = {"cand-fp"}, {"cand-sig"}

    def fake_identities():
        return state["board"], lambda report: (fps, sigs)

    monkeypatch.setattr(qldpc, "_board_identities", fake_identities)
    return state


def test_own_entry_is_not_a_match(dedup_env):
    """The file this run just wrote must not count as an existing entry."""
    dedup_env["board"] = [_board_entry("7-1-3.json", {"cand-fp"}, {"cand-sig"})]
    got = qldpc.board_dedup({}, exclude="7-1-3.json")
    assert got == {"checked": True, "match": None, "kind": None}, got


def test_self_entry_name_needs_the_board_directory(monkeypatch, tmp_path):
    """A scratch --out must not get the exclusion.

    Writing outside the board's own directory means an entry sharing the
    candidate's basename is a *different* file, and reporting it is the point.
    """
    monkeypatch.setattr(qldpc, "_board_codes_dir", lambda: str(tmp_path / "codes"))
    # same directory -> the candidate would match itself
    assert qldpc._self_entry_name(str(tmp_path / "codes"), str(tmp_path / "codes" / "7-1-3.json")) == "7-1-3.json"
    # a scratch directory -> no exclusion, whatever the basename
    import pathlib

    for other in (tmp_path / "scratch", tmp_path, pathlib.Path("/tmp")):
        assert qldpc._self_entry_name(str(other), str(other / "7-1-3.json")) is None


def test_unreadable_board_dir_leaves_the_exclusion_off(monkeypatch):
    """If the board's directory cannot be resolved, exclude nothing."""

    def boom():
        raise RuntimeError("no validate_candidate")

    monkeypatch.setattr(qldpc, "_board_codes_dir", boom)
    assert qldpc._self_entry_name("/anywhere", "/anywhere/7-1-3.json") is None


def test_other_equivalent_entry_is_still_reported(dedup_env):
    """Excluding the candidate must not hide a real duplicate under a new name."""
    dedup_env["board"] = [_board_entry("7-1-3.json", {"cand-fp"}, {"cand-sig"})]
    got = qldpc.board_dedup({}, exclude="7-1-3-renamed.json")
    assert got["match"] == "7-1-3.json", got
    assert got["kind"] == "exact fingerprint", got


def test_wl_match_survives_exclusion(dedup_env):
    """The WL arm reports a signature match too, not only exact fingerprints."""
    dedup_env["board"] = [_board_entry("other.json", {"unrelated"}, {"cand-sig"})]
    got = qldpc.board_dedup({}, exclude="7-1-3.json")
    assert got["match"] == "other.json", got
    assert got["kind"] == "WL signature", got


def test_box_is_ticked_when_nothing_matched(dedup_env):
    """No match -> ticked, so the prose gate's unticked-box rule passes."""
    dedup_env["board"] = [_board_entry("other.json", {"unrelated"}, {"unrelated"})]
    box = qldpc._equivalence_box(qldpc.board_dedup({}, exclude="7-1-3.json"))
    assert box.startswith("- [x]"), box
    assert "[ ]" not in box, box


def test_box_stays_unticked_on_a_real_match(dedup_env):
    """A real duplicate keeps the box open, which is the whole point of it."""
    dedup_env["board"] = [_board_entry("7-1-3.json", {"cand-fp"}, {"cand-sig"})]
    box = qldpc._equivalence_box(qldpc.board_dedup({}, exclude="renamed.json"))
    assert box.startswith("- [ ]"), box
    assert "7-1-3.json" in box, box


def test_no_board_to_check_leaves_it_unticked(monkeypatch):
    """An unreadable board must not produce a ticked box nobody can back."""

    def boom():
        raise RuntimeError("board unavailable")

    monkeypatch.setattr(qldpc, "_board_identities", boom)
    got = qldpc.board_dedup({}, exclude="7-1-3.json")
    assert got == {"checked": False, "match": None, "kind": None}, got
    box = qldpc._equivalence_box(got)
    assert box.startswith("- [ ]"), box


def test_written_file_is_named_as_the_exclusion(monkeypatch, tmp_path):
    """End to end: after a real submit the box is ticked, not self-matched.

    This is the regression that mattered -- the ordering of the write and the
    dedup, not the exclusion arithmetic. It asserts that the candidate's file is
    already on disk when the dedup runs (which is what used to make it match
    itself) and that the dedup is nonetheless told to ignore it.
    """
    HX, HZ = _steane()
    monkeypatch.setattr(qldpc, "load_checks", lambda _p: (HX, HZ, None, None))
    monkeypatch.setattr(
        qldpc,
        "verify",
        lambda _doc, refute: {
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
        },
    )
    monkeypatch.setattr(qldpc, "_load_board_entries", lambda: [])
    # the candidate is written into the directory the board is read from, and
    # the board already lists it -- what the real board looks like by the time
    # the dedup runs, since the write happens first
    monkeypatch.setattr(qldpc, "_board_codes_dir", lambda: str(out))
    monkeypatch.setattr(
        qldpc,
        "_board_identities",
        lambda: (
            [{"name": "7-1-3.json", "fingerprint": "f", "sig": "s", "css_fingerprints": [], "css_sigs": []}],
            lambda report: ({"f"}, {"s"}),
        ),
    )

    out = tmp_path / "codes"
    out.mkdir()
    rc = qldpc.main(
        [
            "submit",
            "x.npz",
            "--authors",
            "@me",
            "--no-circuit",
            "--trials",
            "50",
            "--fast-trials",
            "0",
            "--out",
            str(out),
            "--json",
        ]
    )
    assert rc == 0
    written = out / "7-1-3.json"
    assert written.exists(), "the submit did not write codes/7-1-3.json"
    assert qldpc._self_entry_name(str(out), str(written)) == "7-1-3.json"
    # the candidate is on disk *and* on the board the dedup sees, and the
    # verdict is still "no equivalent entry" -- because the box asks about
    # other entries, and this file is the entry this run adds.
    got = qldpc.board_dedup({}, exclude="7-1-3.json")
    assert got == {"checked": True, "match": None, "kind": None}, got
    box = qldpc._equivalence_box(got)
    assert box.startswith("- [x]"), box

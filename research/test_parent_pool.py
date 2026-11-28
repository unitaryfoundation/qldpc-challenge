"""The parent-pool manifest (issue #7440): one export of board entries that a code-calculus consumer loads as parents.

The board is a small directory of real entries copied into a temp checkout,
so the records are the verifier's own; the schema is checked with
jsonschema; the code-calculus half (every parent record loads as a
``CodeState`` through the bridge) is skipped without a checkout.
"""

import json
import os
import shutil
import subprocess
import sys

import calculus_bridge as CB
import parent_pool as PP
import pytest
import qldpc_verify

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
SLUGS = ("12-4-2", "7-1-3", "4-2-2", "10-2-4", "72-12-6")  # four CSS entries and one stabilizer entry


@pytest.fixture(scope="module")
def board(tmp_path_factory):
    """Make a git checkout holding five entries, the last one added in a second commit."""
    root = tmp_path_factory.mktemp("board")
    codes = root / "codes"
    codes.mkdir()
    (root / "certs").mkdir()
    for slug in SLUGS[:-1]:
        shutil.copy(os.path.join(ROOT, "codes", f"{slug}.json"), codes / f"{slug}.json")
    cert = os.path.join(ROOT, "certs", "12-4-2.json")
    if os.path.exists(cert):
        shutil.copy(cert, root / "certs" / "12-4-2.json")
    env = dict(
        os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"
    )

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)

    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "four entries")
    first = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    shutil.copy(os.path.join(ROOT, "codes", f"{SLUGS[-1]}.json"), codes / f"{SLUGS[-1]}.json")
    git("add", "-A")
    git("commit", "-q", "-m", "one more")
    return {"root": str(root), "codes": str(codes), "certs": str(root / "certs"), "first": first}


def _build(board, **kw):
    return PP.build(codes_dir=board["codes"], certs_dir=board["certs"], root=board["root"], **kw)


def test_the_manifest_lists_every_ok_entry_with_the_verifiers_classes(board):
    m = _build(board)
    assert m["schema_version"] == 1 and m["count"] == 5 and m["codes"] == "codes"
    assert m["board_commit"] and len(m["board_commit"]) == 40
    by = {r["slug"]: r for r in m["parents"]}
    assert set(by) == set(SLUGS) and [r["n"] for r in m["parents"]] == sorted(r["n"] for r in m["parents"])
    bb = by["72-12-6"]
    assert (bb["n"], bb["k"], bb["d"], bb["w"]) == (72, 12, 6, 6) and bb["weight_class"] == "weight-6"
    assert bb["family"] == "bivariate-bicycle" and bb["locality_class"] in (
        "unrestricted",
        "local-2d-bilayer",
        "local-2d-single",
    )
    assert bb["checks_sha256"] == qldpc_verify.checks_sha256(
        json.load(open(os.path.join(board["codes"], "72-12-6.json")))
    )
    assert bb["distance"]["tier"] in PP.TIERS and set(bb["distance"]) >= {"d", "tier", "lower_bound", "X", "Z"}
    assert bb["provenance"]["construction"] and bb["kd2_over_n"] == 6.0
    stab = by["10-2-4"]
    assert stab["code_type"] == "stabilizer" and "S" in stab["checks"] and "X" not in stab["checks"]


def test_the_filters_select_by_parameters_family_type_and_tier(board):
    assert {r["slug"] for r in _build(board, n_max=12)["parents"]} == {"12-4-2", "7-1-3", "4-2-2", "10-2-4"}
    assert {r["slug"] for r in _build(board, n_min=10, k_min=3)["parents"]} == {"12-4-2", "72-12-6"}
    assert {r["slug"] for r in _build(board, families=["bivariate-bicycle"])["parents"]} == {"12-4-2", "72-12-6"}
    assert {r["slug"] for r in _build(board, code_types=["stabilizer"])["parents"]} == {"10-2-4"}
    assert {r["slug"] for r in _build(board, d_min=3, w_max=4)["parents"]} <= {"7-1-3", "10-2-4"}
    m = _build(board, tiers=["upper_bound", "exact", "lower_bounded"])
    assert m["count"] == 5 and m["filters"]["tiers"] == ["exact", "lower_bounded", "upper_bound"]
    assert _build(board, slugs=["7-1-3"])["parents"][0]["slug"] == "7-1-3"
    assert "checks" not in _build(board, include_checks=False)["parents"][0]


def test_since_commit_keeps_the_entries_added_after_it(board):
    m = _build(board, since_commit=board["first"])
    assert [r["slug"] for r in m["parents"]] == ["72-12-6"] and m["filters"]["since_commit"] == board["first"]
    assert _build(board, since_commit=board["first"], n_max=50)["count"] == 0
    with pytest.raises(ValueError, match="could not diff"):
        _build(board, since_commit="0000000")


def test_the_manifest_validates_against_the_schema(board):
    pytest.importorskip("jsonschema")
    m = _build(board)
    assert PP.validate(m) == []
    broken = json.loads(json.dumps(m))
    broken["parents"][0]["checks_sha256"] = "nope"
    del broken["parents"][1]["distance"]["tier"]
    problems = PP.validate(broken)
    assert any("checks_sha256" in p for p in problems) and any("tier" in p for p in problems)


def test_every_parent_record_is_a_presentation_the_bridge_accepts(board):
    m = _build(board, code_types=["CSS"])
    for r in m["parents"]:
        pres = CB.css_document(r)  # n, k, checks: the CodeState.from_challenge shape
        assert pres["n"] == r["n"] and pres["k"] == r["k"]
        assert qldpc_verify.checks_sha256(r) == r["checks_sha256"]


@pytest.mark.skipif(not CB.available(), reason=f"code-calculus not found (set {CB.ENV} to a checkout)")
def test_every_css_parent_loads_as_a_code_state(board):
    calculus = CB.load()
    for r in _build(board, code_types=["CSS"])["parents"]:
        state = CB.state_from_entry(r, calculus=calculus)
        assert (state.n(), state.k(), state.w()) == (r["n"], r["k"], r["w"])
        assert CB.binding_hash(r, calculus=calculus) == r["checks_sha256"]


def test_the_cli_writes_and_validates_a_manifest(board, tmp_path):
    out = tmp_path / "parents.json"
    proc = subprocess.run(
        [
            sys.executable,
            os.path.join(_HERE, "kit", "parent_pool.py"),
            "--codes",
            board["codes"],
            "--n-max",
            "12",
            "--validate",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    m = json.loads(out.read_text())
    assert m["count"] == 4 and "wrote 4 parents" in proc.stderr
    text = subprocess.run(
        [sys.executable, os.path.join(_HERE, "kit", "parent_pool.py"), "--codes", board["codes"], "--summary"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert text.returncode == 0 and "parent pool: 5 entries" in text.stdout and "72-12-6" in text.stdout

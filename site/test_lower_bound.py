"""The board's proven lower bound (issue #4230): the interval mark and what earns it."""
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_lower_bound", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOC = {"n": 8, "k": 2, "code_type": "CSS", "checks": {"X": [[0, 1, 2, 3]], "Z": [[4, 5, 6, 7]]},
       "distance": {"d": 20, "X": {"value": 21}, "Z": {"value": 20}}}


def test_the_badge_reads_as_an_interval_below_the_witness():
    build = load_site_build()
    assert build.badge("exact") == '<span class="b exact">d =</span>' == build.badge("exact", 7)
    assert 'class="b ub"' in build.badge("ub") and 'class="b ub"' in build.badge("ub", None)
    assert 'class="b ub"' in build.badge("ub", 1), "d >= 1 is the trivial bound and earns nothing"
    mark = build.badge("ub", 7)
    assert 'class="b lb"' in mark and mark.endswith(">7 &le; d &le;</span>")


def test_a_partial_certificate_is_honored_by_its_binding_hash_not_by_the_claim():
    build = load_site_build()
    cert = {"d": 25, "d_exact": False, "d_lower": 7,
            "sides": {"X": {"proved_min": 9}, "Z": {"proved_min": 7}},
            "verification": {"level": "solver", "checks_sha256": build.checks_sha256(DOC)}}
    # the certificate was made against a claim of 25 that has since been corrected to 20: the bound survives
    assert build.cert_lower_bounds(cert, DOC) == {"d": 7, "X": 9, "Z": 7}
    other = dict(cert, verification={"level": "solver", "checks_sha256": "0" * 64})
    assert build.cert_lower_bounds(other, DOC) == {"d": None, "X": None, "Z": None}
    above = dict(cert, d_lower=21)
    assert build.cert_lower_bounds(above, DOC) == {"d": None, "X": None, "Z": None}, \
        "a bound above the verified witness is a contradiction, not a board update"
    trivial = dict(cert, d_lower=1)
    assert build.cert_lower_bounds(trivial, DOC)["d"] is None
    assert build.cert_lower_bounds(None, DOC)["d"] is None
    stab = dict(DOC, code_type="stabilizer")
    assert build.cert_lower_bounds(cert, stab)["d"] is None
    # an honored exact certificate proves d on every side; a stale one proves nothing
    exact = {"d": 20, "d_exact": True, "sides": {"X": {"value": 21, "exact": True}, "Z": {"value": 20, "exact": True}}}
    assert build.cert_lower_bounds(exact, DOC) == {"d": 20, "X": 20, "Z": 20}
    assert build.cert_lower_bounds(dict(exact, d=19), DOC)["d"] is None


def test_the_per_side_marks_show_the_side_bounds():
    build = load_site_build()
    e = {"tier_X": "ub", "tier_Z": "exact", "d_X": 21, "d_Z": 20, "lb_X": 9, "lb_Z": 20, "w_X": 4, "w_Z": 4}
    assert build.asym_detail(e) == "9 &le; d_X &le; 21, d_Z = 20 &middot; w_X = 4, w_Z = 4"
    e.update(lb_X=None)
    assert build.asym_detail(e).startswith("d_X &le; 21")

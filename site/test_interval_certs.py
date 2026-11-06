"""An interval certificate shows its proved lower bound on the code page and upgrades nothing (issue #4718)."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_interval", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_certificate_row_reads_exact_interval_or_none():
    build = load_site_build()
    doc = {"distance": {"d": 16, "X": {"value": 16}, "Z": {"value": 16}}}
    interval = {"d": 16, "d_exact": False, "interval": True, "solver": "tropidist 0123456789ab exhaustive search",
                "sides": {"X": {"value": 16, "exact": True, "status": "UNSAT"},
                          "Z": {"value": 16, "exact": False, "status": "TIMEOUT", "lower_bound": 14}}}
    assert build.cert_lower_bounds(interval) == {"X": 16, "Z": 14}
    assert build.side_tiers(interval, doc) == {"X": "ub", "Z": "ub"}, "an interval upgrades no side"
    row = build.certificate_row(interval, doc, 16, stab=False)
    assert "certified lower bound d &ge; 14" in row and "d_X &ge; 16, d_Z &ge; 14" in row
    assert "d &le; 16" in row and "tropidist" in row and "cert-ok" not in row
    # a stale interval (the entry's distance changed) shows nothing
    assert "none yet" in build.certificate_row(dict(interval, d=17), doc, 16, stab=False)
    exact = {"d": 16, "d_exact": True, "solver": "s",
             "sides": {"X": {"value": 16, "exact": True}, "Z": {"value": 16, "exact": True}}}
    assert "cert-ok" in build.certificate_row(exact, doc, 16, stab=False)
    assert build.cert_lower_bounds(exact) == {"X": 16, "Z": 16}
    none = build.certificate_row(None, doc, 16, stab=True)
    assert "none yet" in none and "tropidist" in none

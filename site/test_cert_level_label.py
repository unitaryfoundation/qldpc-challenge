"""A certificate row says what its verdict is worth; a stabilizer entry without one names the backend (issue #4939)."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location("site_build_cert_level", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_level_has_a_label_and_solver_is_called_a_verdict():
    build = load_site_build()
    assert set(build.CERT_LEVEL_LABELS) == {"solver", "proof_log", "formal"}
    solver = build.cert_level_label("solver")
    assert "solver verdict" in solver and "machine-checked" not in solver.split("no artifact")[0]
    assert "drat-trim" in build.cert_level_label("proof_log")
    assert "machine-checked proof" in build.cert_level_label("formal")
    assert build.cert_level_label("mystery") == '<span class=claimed>level mystery</span>'

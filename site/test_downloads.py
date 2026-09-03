"""Download artifacts addressed by code ID (issue #556)."""

import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_downloads", os.path.join(ROOT, "site", "build.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_with_one_code(tmp_path):
    """Run the full build against a one-code board.

    Stale artifacts are pre-planted in docs/codes to exercise pruning.
    """
    build = load_site_build()
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        doc = json.load(f)
    codes = tmp_path / "codes"
    codes.mkdir()
    with open(codes / "72-6-6.json", "w") as f:
        json.dump(doc, f)

    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    os.makedirs(os.path.join(build.DOCS, "codes"), exist_ok=True)
    for stale in ("12-2-3.html", "12-2-3.json"):
        with open(os.path.join(build.DOCS, "codes", stale), "w") as f:
            f.write("stale")
    build.build()
    return build


def test_every_code_is_served_by_id(tmp_path):
    build = _build_with_one_code(tmp_path)
    with open(os.path.join(build.DOCS, "codes", "72-6-6.json")) as f:
        served = json.load(f)
    with open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")) as f:
        assert served == json.load(f)

    with open(os.path.join(build.DOCS, "codes", "72-6-6.html")) as f:
        page = f.read()
    # the page lives in docs/codes/, so the artifact link is same-directory
    assert '<a href="72-6-6.json" download' in page
    assert "Code ID</b> <code>72-6-6</code>" in page


def test_index_manifest_lists_every_id(tmp_path):
    build = _build_with_one_code(tmp_path)
    with open(os.path.join(build.DOCS, "codes", build.INDEX_MANIFEST)) as f:
        index = json.load(f)
    assert index["codes"] == [
        {"id": "72-6-6", "n": 72, "k": 6, "d": 6, "tier": index["codes"][0]["tier"]}
    ]
    # tiers are the board's short labels: "ub" (upper bound) or "exact"
    assert index["codes"][0]["tier"] in ("ub", "exact")


def test_manifest_filename_cannot_be_a_code_id(tmp_path):
    # the manifest stem must fail _SAFE_SLUG, so a code named "index" (or any
    # other slug) can never have its submission artifact overwritten by the
    # manifest
    build = load_site_build()
    assert build._SAFE_SLUG.fullmatch(build.INDEX_MANIFEST[: -len(".json")]) is None


def test_stale_artifacts_are_pruned_but_manifest_kept(tmp_path):
    build = _build_with_one_code(tmp_path)
    leftovers = os.listdir(os.path.join(build.DOCS, "codes"))
    assert "12-2-3.html" not in leftovers
    assert "12-2-3.json" not in leftovers
    assert build.INDEX_MANIFEST in leftovers
    assert set(leftovers) == {"72-6-6.html", "72-6-6.json", build.INDEX_MANIFEST}

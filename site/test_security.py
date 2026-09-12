"""Adversarial regression tests for the static site's untrusted data."""

import copy
import glob
import importlib.util
import json
import os
import re

import pytest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_SCRIPT = re.compile(
    r'<script id="([A-Za-z][A-Za-z0-9_-]*)" '
    r'type="application/json">(.*?)</script>', re.DOTALL)


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build_security", os.path.join(ROOT, "site", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def unrestricted_string_paths(node, path=()):
    """Find free-form schema strings that must stay covered by the XSS test."""
    found = set()
    if (isinstance(node, dict) and node.get("type") == "string"
            and not {"enum", "const", "pattern"}.intersection(node)):
        found.add("/".join(path))
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                found.update(unrestricted_string_paths(value, path + (key,)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.update(unrestricted_string_paths(value, path + (str(index),)))
    return found


def test_free_form_schema_fields_are_deliberately_covered():
    with open(os.path.join(ROOT, "schema", "code.schema.json")) as f:
        schema = json.load(f)

    assert unrestricted_string_paths(schema) == {
        "properties/circuit/properties/notes",
        "properties/name",
        "properties/provenance/properties/authors/items",
        "properties/provenance/properties/construction",
        "properties/provenance/properties/model/oneOf/0",
        "properties/provenance/properties/model/oneOf/1/items",
        "properties/provenance/properties/notes",
        "properties/provenance/properties/references/items",
        # Deprecated and ignored by the site, but intentionally classified.
        "properties/tracks/items",
        "$defs/sideDistance/properties/witness_provenance/properties/tool",
        # One entry covers both use sites of the shared credit block
        # (locality.contributed_by and circuit.contributed_by).
        "$defs/contributedBy/properties/method",
    }


def test_context_helpers_reject_active_content():
    build = load_site_build()
    payload = '</script><script>globalThis.qldpcXssRegression=1</script>\u2028&<>'

    encoded = build.json_for_html({"future_field": payload})
    assert "</script>" not in encoded.lower()
    assert "\u2028" not in encoded
    assert "\\u003c/script\\u003e" in encoded.lower()
    assert json.loads(encoded)["future_field"] == payload

    assert 'href="https://arxiv.org/abs/2504.08887v2"' in build.cite(
        "arXiv:2504.08887v2")
    malformed = build.cite('arxiv:\"><img src=x onerror=alert(1)>')
    assert "href=" not in malformed
    assert "<img" not in malformed

    with pytest.raises(ValueError, match="unsafe URL scheme"):
        build.safe_url("javascript:alert(1)")


def test_code_filenames_must_be_safe_slugs(tmp_path):
    build = load_site_build()
    codes = tmp_path / "codes"
    codes.mkdir()
    (codes / 'unsafe"name.json').write_text("{}")
    build.ROOT = str(tmp_path)

    with pytest.raises(ValueError, match="unsafe code filename"):
        build.load_entries()


@pytest.mark.parametrize("model_as_list", [False, True])
def test_free_text_submission_payloads_render_inert(tmp_path, model_as_list):
    build = load_site_build()
    fixture = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")
    with open(fixture) as f:
        doc = copy.deepcopy(json.load(f))

    close_script = (
        '</script><script>globalThis.qldpcXssRegression=1</script>')
    attr_breakout = (
        '\"><img src=x onerror=globalThis.qldpcXssRegression=2>')
    doc["name"] = f"Future code {attr_breakout}"
    model = f"Model 5.1 {close_script}\u2028"
    doc["provenance"].update({
        "authors": ["@safe-author", f"Alice {close_script}"],
        "construction": f"New construction {attr_breakout}",
        "model": [model, "Model 6.0"] if model_as_list else model,
        "references": [f"arxiv:{attr_breakout}"],
        "notes": f"Notes {attr_breakout}",
    })
    doc["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@safe-author"],
        "date": "2026-08-20",
        "found_at_samples": 1,
        "tool": f"tool {attr_breakout}",
    }
    doc["locality"]["contributed_by"] = {
        "by": ["@safe-author"],
        "date": "2026-08-20",
        "method": f"layout method {attr_breakout}",
    }
    doc["circuit"] = {
        "d_circ": {
            side: {"value": 1, "confidence": "upper_bound", "witness": [0]}
            for side in ("X", "Z")
        },
        "rounds": 6,
        "stim_version": "1.15.0",
        "notes": f"circuit notes {close_script}",
        "contributed_by": {
            "by": ["@safe-author"],
            "date": "2026-09-11",
            "method": f"schedule method {attr_breakout}",
        },
    }
    doc["tracks"] = [close_script]
    doc["schema_version"] = "0.2"

    codes = tmp_path / "codes"
    codes.mkdir()
    with open(codes / "72-6-6.json", "w") as f:
        json.dump(doc, f)

    build.ROOT = str(tmp_path)
    build.DOCS = str(tmp_path / "docs")
    build.CERTS = str(tmp_path / "certs")
    build.build()

    pages = []
    for path in glob.glob(os.path.join(build.DOCS, "**", "*.html"),
                          recursive=True):
        with open(path) as f:
            pages.append(f.read())

    rendered = "\n".join(pages)
    index = (tmp_path / "docs" / "index.html").read_text()
    data = {match.group(1): json.loads(match.group(2))
            for match in DATA_SCRIPT.finditer(index)}

    assert pages
    assert close_script not in rendered
    assert attr_breakout not in rendered
    assert "<script>globalThis.qldpcXssRegression" not in rendered
    assert "<img src=x onerror=" not in rendered
    assert "\\u003c/script\\u003e" in index.lower()
    assert {"cmdata", "lbwdata", "rcdata", "rcseries"} <= data.keys()
    assert "qldpcXssRegression" in json.dumps(data["rcdata"])

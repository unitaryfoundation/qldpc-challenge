"""A CSS entry is deduped up to local Hadamards, as a stabilizer entry already was.

Before this, the relation a submission was deduped under depended on the
`code_type` the submitter wrote: a Hadamard relabelling of a board entry was
caught when typed `stabilizer`, because the verifier filed it under its CSS
image, and missed when typed `CSS`, because the fingerprint keys on the RREF
and the relabelling changes it. These tests pin the symmetry.
"""

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

from qldpc_verify import (  # noqa: E402
    _matrix,
    css_fingerprint,
    css_local_hadamard_images,
    signature,
    verify,
)


def load(slug):
    with open(os.path.join(_ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        return json.load(f)


def swap_of(doc):
    """Return the X/Z swap, the only image a connected CSS code admits."""
    images, capped = css_local_hadamard_images(doc)
    assert not capped
    assert len(images) == 1, f"a connected code has one image, got {len(images)}"
    return images[0]


def test_a_connected_css_code_admits_exactly_the_swap():
    """Admit exactly the swap: purity forces h to be a union of components."""
    doc = load("144-12-12")
    image = swap_of(doc)
    assert sorted(map(sorted, image["checks"]["X"])) == sorted(map(sorted, doc["checks"]["Z"]))
    assert sorted(map(sorted, image["checks"]["Z"])) == sorted(map(sorted, doc["checks"]["X"]))


def test_the_swap_is_filed_with_the_entry_so_a_relabelling_collides():
    """Close the gap: a relabelling collides with the entry it came from.

    The twin's own fingerprint differs from the parent's, which is why the
    decisive check missed it, but one of the twin's images matches.
    """
    doc = load("144-12-12")
    n = doc["n"]
    twin = dict(doc, name="twin", checks=swap_of(doc)["checks"])

    fp_parent = css_fingerprint(_matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n))
    fp_twin = css_fingerprint(_matrix(twin["checks"]["X"], n), _matrix(twin["checks"]["Z"], n))
    assert fp_parent != fp_twin, "if these matched there would be nothing to fix"

    images, _ = css_local_hadamard_images(twin)
    fps = {css_fingerprint(_matrix(i["checks"]["X"], n), _matrix(i["checks"]["Z"], n)) for i in images}
    sigs = {signature(i)["hash"] for i in images}
    assert fp_parent in fps
    assert signature(doc)["hash"] in sigs


def test_verify_reports_the_images_for_a_css_entry():
    """Populate css_equivalent for a CSS entry too.

    verify_all files an entry under report['css_equivalent'], so the CSS branch
    has to fill it the way the stabilizer branch does.
    """
    rep = verify(load("144-12-12"))
    ceq = rep.get("css_equivalent") or {}
    assert ceq.get("of") == "css"
    assert ceq.get("images") == 1
    assert ceq.get("enumeration_capped") is False
    assert len(ceq.get("fingerprints") or []) == 1
    assert len(ceq.get("signatures") or []) == 1
    assert any(c["check"] == "local_hadamard_css_images" and c["ok"] for c in rep["checks"])


def test_a_disconnected_code_admits_one_image_per_nonempty_component_set():
    """Enumerate one image per nonempty set of components.

    Two independent blocks give three images, not one: the swap of each block
    alone and of both. This is the case a connectivity shortcut gets wrong, so
    the components are enumerated rather than assumed away.
    """
    doc = {"n": 4, "k": 2, "code_type": "CSS", "distance": {"d": 1}, "checks": {"X": [[0, 1]], "Z": [[2, 3]]}}
    images, capped = css_local_hadamard_images(doc)
    assert not capped
    assert len(images) == 3
    shapes = {
        (tuple(sorted(map(tuple, i["checks"]["X"]))), tuple(sorted(map(tuple, i["checks"]["Z"])))) for i in images
    }
    assert len(shapes) == 3, "the three images are distinct"


def test_the_identity_is_not_returned_as_an_image():
    """Omit the identity from the images.

    The entry is already filed under its own fingerprint, so returning the
    identity too would make every entry collide with itself.
    """
    doc = load("144-12-12")
    n = doc["n"]
    fp = css_fingerprint(_matrix(doc["checks"]["X"], n), _matrix(doc["checks"]["Z"], n))
    images, _ = css_local_hadamard_images(doc)
    fps = {css_fingerprint(_matrix(i["checks"]["X"], n), _matrix(i["checks"]["Z"], n)) for i in images}
    assert fp not in fps

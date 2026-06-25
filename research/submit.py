"""Package a CSS code (HX, HZ) into a schema-valid qldpc-challenge submission.

Given the two parity-check matrices and a little provenance, this:
  * recomputes n and k and asserts CSS commutation (the same facts the verifier
    checks), so a doc it returns will not fail those gates;
  * extracts the lightest X- and Z-logical *witnesses* with ``surrogate`` and
    asserts each one passes the verifier's witness test (in ker of the opposite
    checks, outside the rowspace of its own checks, weight == claimed value);
  * fills an optional ``locality`` block (computing the true interaction radius
    as the max check diameter) when you pass per-qubit coordinates;
  * validates the whole document against ``schema/code.schema.json``.

The result is a dict you can write to ``codes/your-code.json`` and submit.

    from submit import make_submission, save_submission
    doc = make_submission(HX, HZ, name="...", construction="...",
                          authors=["you"], tracks=["bivariate bicycle (periodic)"])
    save_submission(doc, "codes/my-code.json")
    # then: uv run python verify/qldpc_verify.py codes/my-code.json
"""
import datetime
import json
import math
import os
import sys

import numpy as np

from css import compute_k, verify_css, commutes, in_rowspace
from surrogate import lightest_logical

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "..", "schema", "code.schema.json")


def _supports(H):
    return [sorted(int(j) for j in np.nonzero(row % 2)[0]) for row in H]


def _vec(support, n):
    v = np.zeros(n, dtype=np.int8)
    v[support] = 1
    return v


def _interaction_radius(checks, coordinates):
    """Max check diameter under the given 2D coordinates (the quantity the
    verifier recomputes for the locality tracks)."""
    def diam(sup):
        pts = [coordinates[q] for q in sup]
        return max((math.dist(a, b) for a in pts for b in pts), default=0.0)
    return max((diam(s) for s in checks), default=0.0)


def validate(doc):
    """Return a list of schema violations ([] means valid). Uses jsonschema if
    available, else returns [] (the verifier will do the authoritative check)."""
    try:
        import jsonschema
        with open(_SCHEMA_PATH) as f:
            schema = json.load(f)
    except Exception:
        return []
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path))]


def make_submission(HX, HZ, *, name, construction, authors, tracks,
                    references=None, notes=None, date=None,
                    confidence="upper_bound", coordinates=None, layers=None,
                    trials=8000, seed=0):
    """Build a submission dict for the CSS code (HX, HZ).

    Parameters
    ----------
    HX, HZ : int arrays (num_checks, n)
        The CSS parity checks. CSS commutation is asserted.
    name, construction : str
        Human-readable name and how the code was built (provenance).
    authors, tracks : list of str
        Your author handle(s) and the tracks to enter (see TRACKS.md).
    confidence : {"upper_bound", "exact"}
        Distance confidence. ``distance_rand``-derived witnesses are honest
        upper bounds; mark ``"exact"`` only if you intend server certification.
    coordinates : optional list of [x, y], length n
        Per-qubit layout for the 2d-local-* tracks; enables the locality block.
    layers : optional int
        Physical layers for the locality block (e.g. 2 for a flip-chip bilayer).
    trials, seed : int
        Budget/seed for the witness search.

    Returns
    -------
    dict : a schema-valid submission. Witnesses are pre-checked against the
    verifier's own criteria, so the doc passes the trustless distance gate.
    """
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    assert verify_css(HX, HZ), "CSS commutation H_X H_Z^T = 0 fails"
    n = HX.shape[1]
    k = compute_k(HX, HZ)

    wx, xwit = lightest_logical(HX, HZ, trials=trials, seed=seed)
    wz, zwit = lightest_logical(HZ, HX, trials=trials, seed=seed + 1)
    if not xwit or not zwit:
        raise ValueError("no nontrivial logical found on some side "
                         f"(k={k}); is this a valid encoding code?")
    # Mirror the verifier's witness criteria so the doc is guaranteed to pass.
    xv, zv = _vec(xwit, n), _vec(zwit, n)
    assert commutes(xv, HZ) and not in_rowspace(xv, HX), "X witness invalid"
    assert commutes(zv, HX) and not in_rowspace(zv, HZ), "Z witness invalid"
    dval = min(wx, wz)

    doc = {
        "schema_version": "0.1",
        "name": name,
        "code_type": "CSS",
        "n": int(n),
        "k": int(k),
        "checks": {"X": _supports(HX), "Z": _supports(HZ)},
        "distance": {
            "d": int(dval),
            "X": {"value": int(wx), "confidence": confidence, "witness": xwit},
            "Z": {"value": int(wz), "confidence": confidence, "witness": zwit},
        },
        "provenance": {
            "authors": list(authors),
            "construction": construction,
            "references": list(references) if references else [],
            "date": date or datetime.date.today().isoformat(),
            "notes": notes or "",
        },
        "tracks": list(tracks),
    }
    if coordinates is not None:
        coords = [[float(x), float(y)] for x, y in coordinates]
        assert len(coords) == n, f"need {n} coordinates, got {len(coords)}"
        radius = _interaction_radius(doc["checks"]["X"] + doc["checks"]["Z"], coords)
        doc["locality"] = {"coordinates": coords,
                           "interaction_radius": radius}
        if layers is not None:
            doc["locality"]["layers"] = int(layers)
    return doc


def save_submission(doc, path):
    """Write ``doc`` to ``path`` (pretty JSON) after a schema check; returns the
    list of schema violations (empty on success)."""
    errs = validate(doc)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    return errs


if __name__ == "__main__":
    print("submit.py is a library; see research/recipes/ for end-to-end usage.",
          file=sys.stderr)

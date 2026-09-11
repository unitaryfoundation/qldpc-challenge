"""Package a CSS code (HX, HZ) into a schema-valid qldpc-challenge submission.

Given the two parity-check matrices and a little provenance, this:
  * recomputes n and k and asserts CSS commutation (the same facts the verifier
    checks), so a doc it returns will not fail those gates;
  * extracts the lightest X- and Z-logical *witnesses* with ``surrogate`` and
    asserts each one passes the verifier's witness test (in ker of the opposite
    checks, outside the rowspace of its own checks, weight == claimed value);
  * fills an optional ``locality`` block (computing the true interaction radius
    as the max check diameter) when you pass per-qubit coordinates;
  * lets ``save_submission`` report violations of ``schema/code.schema.json``.

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
from css import commutes, compute_k, in_rowspace, verify_css
from surrogate import lightest_logical

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "..", "..", "schema", "code.schema.json")


def _supports(H):
    return [sorted(int(j) for j in np.nonzero(row % 2)[0]) for row in H]


def _vec(support, n):
    v = np.zeros(n, dtype=np.int8)
    v[support] = 1
    return v


def _interaction_radius(checks, coordinates):
    """Compute the max check diameter used by the locality-track verifier."""
    def diam(sup):
        pts = [coordinates[q] for q in sup]
        return max((math.dist(a, b) for a in pts for b in pts), default=0.0)
    return max((diam(s) for s in checks), default=0.0)


def validate(doc):
    """Return a list of schema violations ([] means valid).

    Uses jsonschema if available, else returns [] (the verifier will do the
    authoritative check). Missing or unreadable schema files are errors.
    """
    try:
        import jsonschema
    except ImportError:
        return []
    with open(_SCHEMA_PATH) as f:
        schema = json.load(f)
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path))]


def make_submission(HX, HZ, *, name, construction, authors, family=None,
                    references=None, notes=None, date=None, tracks=(),
                    confidence="upper_bound", coordinates=None, layers=None,
                    trials=8000, seed=0, witnesses=None):
    """Build a submission dict for the CSS code (HX, HZ).

    Parameters
    ----------
    HX, HZ : int arrays (num_checks, n)
        The CSS parity checks. CSS commutation is asserted.
    name, construction : str
        Human-readable name and how the code was built (provenance).
    authors : list of str
        Your author handle(s).
    family : optional str
        The Layer-2 construction-family tag (e.g. "bivariate-bicycle"; see the
        schema enum / TRACKS.md). A filterable tag only -- it is never ranked,
        and the primary track membership (locality + weight class) is computed by
        the verifier from H and the layout, not declared here.
    confidence : {"upper_bound", "exact"}
        Distance confidence. ``distance_rand``-derived witnesses are honest
        upper bounds; mark ``"exact"`` only if you intend server certification.
    coordinates : optional list of [x, y], length n
        Per-qubit layout; enables the locality block, from which the verifier
        derives the 2d-local track membership.
    layers : optional int
        Physical layers for the locality block (e.g. 2 for a flip-chip bilayer).
    tracks : optional list of str
        DEPRECATED and ignored for ranking; retained only for backward
        compatibility. Track membership is computed by the verifier. Leave unset.
    trials, seed : int
        Budget/seed for the witness search.
    witnesses : optional dict with keys "X" and "Z"
        Already-found logical supports. Each is checked using the same GF(2)
        routines as searched witnesses. Supplying both avoids a second search
        that could fail to rediscover an expensive accelerator result.

    Returns
    -------
    dict : a submission with individually validated logical witnesses.
    ``save_submission`` reports schema errors; the full candidate gate remains
    necessary and can refute the claimed bound by finding a lighter logical.
    """
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    assert verify_css(HX, HZ), "CSS commutation H_X H_Z^T = 0 fails"
    n = HX.shape[1]
    k = compute_k(HX, HZ)

    if witnesses is None:
        wx, xwit = lightest_logical(HX, HZ, trials=trials, seed=seed)
        wz, zwit = lightest_logical(HZ, HX, trials=trials, seed=seed + 1)
    else:
        if set(witnesses) != {"X", "Z"}:
            raise ValueError("witnesses must contain both X and Z supports")
        supports = {}
        for side in ("X", "Z"):
            support = list(witnesses[side])
            if (not support or any(not isinstance(q, (int, np.integer))
                                   or isinstance(q, (bool, np.bool_))
                                   or q < 0 or q >= n for q in support)
                    or len(set(support)) != len(support)):
                raise ValueError(f"{side} witness must have distinct qubit indices in [0, n)")
            supports[side] = sorted(int(q) for q in support)
        xwit, zwit = supports["X"], supports["Z"]
        wx, wz = len(xwit), len(zwit)
    if not xwit or not zwit:
        raise ValueError("no nontrivial logical found on some side "
                         f"(k={k}); is this a valid encoding code?")
    # Check individual witnesses; this does not certify the distance claim.
    xv, zv = _vec(xwit, n), _vec(zwit, n)
    if not (commutes(xv, HZ) and not in_rowspace(xv, HX)):
        raise ValueError("X witness invalid")
    if not (commutes(zv, HX) and not in_rowspace(zv, HZ)):
        raise ValueError("Z witness invalid")
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
    }
    if family is not None:
        doc["family"] = family            # Layer-2 tag (filterable, never ranked)
    if tracks:
        doc["tracks"] = list(tracks)      # deprecated; only if explicitly passed
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
    """Write ``doc`` to ``path`` (pretty JSON) after a schema check.

    Return the list of schema violations (empty on success).
    """
    errs = validate(doc)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    return errs


if __name__ == "__main__":
    print("submit.py is a library; see research/test_smoke.py for end-to-end usage.",
          file=sys.stderr)

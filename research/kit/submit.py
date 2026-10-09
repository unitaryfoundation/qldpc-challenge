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
import re
import sys

import numpy as np
from coordination import CandidateCollision, holds_same_candidate
from css import commutes, compute_k, in_rowspace, verify_css
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
    """Return the max check diameter under the given 2D or 3D coordinates.

    The quantity the verifier recomputes for the locality tracks.
    """
    def diam(sup):
        pts = [coordinates[q] for q in sup]
        return max((math.dist(a, b) for a in pts for b in pts), default=0.0)
    return max((diam(s) for s in checks), default=0.0)


def validate(doc):
    """Return a list of schema violations ([] means valid).

    Uses jsonschema if available, else returns [] (the verifier will do the
    authoritative check).
    """
    try:
        import jsonschema
        with open(_SCHEMA_PATH) as f:
            schema = json.load(f)
    except Exception:
        return []
    v = jsonschema.Draft202012Validator(schema)
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path))]



_HANDLE = re.compile(r"^@[A-Za-z0-9-]+$")


def _handles(names):
    """Return ``names`` as schema-valid ``@handles``, dropping what cannot be one."""
    out = []
    for name in names or ():
        h = "@" + str(name).strip().lstrip("@")
        if _HANDLE.match(h) and h not in out:
            out.append(h)
    return out


def make_submission(HX, HZ, *, name, construction, authors, family=None,
                    references=None, notes=None, date=None, tracks=(),
                    confidence="upper_bound", coordinates=None, layers=None,
                    trials=8000, seed=0, found_by=None):
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
    coordinates : optional list of [x, y] or [x, y, z], length n
        Per-qubit layout; enables the locality block, from which the verifier
        derives the 2d-local track membership.
    layers : optional int
        Physical layers for the locality block (e.g. 2 for a flip-chip bilayer).
    tracks : optional list of str
        DEPRECATED and ignored for ranking; retained only for backward
        compatibility. Track membership is computed by the verifier. Leave unset.
    trials, seed : int
        Budget/seed for the witness search. Both are recorded on each side's
        ``witness_provenance`` (issue #2779): ``found_at_samples`` and
        ``survived_samples`` are ``trials``, since the search runs its whole
        budget and keeps the lightest operator it saw, so nothing lighter was
        found in ``trials`` samples; ``seeds`` are the X and Z seeds.
    found_by : optional list of str
        ``@``-handles credited with the witnesses. Defaults to ``authors``,
        which is right when this call ran the search, as it does: the budget
        was spent under the caller's name. Pass it explicitly when the
        operators came from somewhere else. Credit lives on the witness and
        not in ``provenance.authors`` because refutation credit is per
        operator (issue #611), and ``verify/check_authorship.py`` reads it
        there. Handles that do not fit the schema's ``@name`` pattern are
        dropped; with none left the block is omitted rather than invented.

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

    today = date or datetime.date.today().isoformat()
    handles = _handles(found_by if found_by is not None else authors)

    def _provenance(side_seed):
        return {"found_by": handles, "date": today,
                "found_at_samples": int(trials),
                "survived_samples": int(trials),
                "tool": "research/kit/surrogate.lightest_logical",
                "seeds": [int(side_seed)]}

    doc = {
        # 0.2 is the version that introduced witness_provenance; the schema
        # refuses the block under 0.1 so the version stays meaningful.
        "schema_version": "0.2" if handles else "0.1",
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
            "date": today,
            "notes": notes or "",
        },
    }
    if handles:
        doc["distance"]["X"]["witness_provenance"] = _provenance(seed)
        doc["distance"]["Z"]["witness_provenance"] = _provenance(seed + 1)
    if family is not None:
        doc["family"] = family            # Layer-2 tag (filterable, never ranked)
    if tracks:
        doc["tracks"] = list(tracks)      # deprecated; only if explicitly passed
    if coordinates is not None:
        coords = [[float(v) for v in row] for row in coordinates]
        assert len(coords) == n, f"need {n} coordinates, got {len(coords)}"
        assert all(len(row) in (2, 3) for row in coords), \
            "coordinates must be [x, y] or [x, y, z]"
        radius = _interaction_radius(doc["checks"]["X"] + doc["checks"]["Z"], coords)
        doc["locality"] = {"coordinates": coords,
                           "interaction_radius": radius}
        if layers is not None:
            doc["locality"]["layers"] = int(layers)
    return doc


def save_submission(doc, path, *, on_collision="error"):
    """Write ``doc`` to ``path`` as pretty JSON, after a schema check.

    Returns the list of schema violations (empty on success).

    A found low-weight logical is the most expensive data this kit produces, so
    this refuses by default to write over a *different* candidate already at
    ``path``. Several sessions now stage into ``research/candidates/`` at once
    and the flat ``<n>-<k>-<d>.json`` convention gives two of them that find the
    same parameters the same filename; before this the second write simply
    deleted the first one's witness. Re-writing the same candidate is not a
    collision and still succeeds, so re-running a search is unaffected.

    ``on_collision`` is ``"error"`` (raise
    :class:`coordination.CandidateCollision`) or ``"overwrite"`` (the old
    behavior, for a caller that means to replace the file). To keep both
    candidates instead, stage under ``coordination.staging_dir()`` or pass the
    path through ``coordination.unique_path(path, doc)`` first.
    """
    if on_collision not in ("error", "overwrite"):
        raise ValueError(f"on_collision: unknown mode {on_collision!r}; "
                         "use 'error' or 'overwrite'")
    if on_collision == "error" and os.path.exists(path) \
            and not holds_same_candidate(path, doc):
        raise CandidateCollision(
            f"{path} already holds a different candidate. Overwriting it would "
            "destroy a witness no one can recompute cheaply. Stage under "
            "coordination.staging_dir(), or pass "
            "coordination.unique_path(path, doc), or pass "
            "on_collision='overwrite' if replacing it is what you mean.")
    errs = validate(doc)
    with open(path, "w") as f:
        json.dump(doc, f, indent=2)
    return errs


if __name__ == "__main__":
    print("submit.py is a library; see research/test_smoke.py for end-to-end usage.",
          file=sys.stderr)


# -- reproduction manifests for `qldpc reproduce` (#2955, item 3) --------------

REPRO_MANIFEST_VERSION = "1"


def recipe_from_spec(spec):
    """The `{constructor, params}` recipe inside a screening spec, or None."""
    if not isinstance(spec, dict):
        return None
    c, p = spec.get("constructor"), spec.get("params")
    if not isinstance(c, str) or "." not in c or not isinstance(p, dict):
        return None
    return {"constructor": c, "params": p}


def write_repro_manifest(doc, slug, spec, *, repro_dir, artifact_path=None,
                         budget_seconds=300, notes=""):
    """Write <repro_dir>/<slug>.json. Construction stage runs rebuild.py with
    the recipe from spec, or is declared not_reproducible; other stages follow
    what the entry carries. Returns the path."""
    import hashlib
    recipe = recipe_from_spec(spec)
    if recipe:
        construction = {
            "status": "applicable",
            "script": "research/kit/rebuild.py",
            "args": ["--constructor", recipe["constructor"],
                     "--params", json.dumps(recipe["params"], separators=(",", ":"))],
            "budget_seconds": int(budget_seconds),
        }
    else:
        construction = {"status": "not_reproducible",
                        "reason": "the spec recorded for this entry carries no "
                                  "{constructor, params} recipe the kit can replay"}
    circ = doc.get("circuit") or {}
    stages = {
        "verify": {"status": "applicable"},
        "construction": construction,
        "certify": {"status": "applicable", "tlim_seconds": 600} if doc.get("n", 10**9) <= 144
        else {"status": "not_applicable", "reason": "above the certifier's demonstrated range"},
        "circuits": {"status": "applicable"} if circ.get("d_circ")
        else {"status": "not_applicable", "reason": "the entry has no circuit block"},
        "ler": {"status": "applicable", "tolerance": "ci95"} if circ.get("ler")
        else {"status": "not_applicable", "reason": "the entry has no measured rate"},
    }
    manifest = {
        "manifest_version": REPRO_MANIFEST_VERSION,
        "slug": slug,
        "stages": stages,
        "environment": {"extras": ["research"]},
        "notes": notes or ("Emitted by research/kit/submit.write_repro_manifest from the "
                           "screening spec; the construction stage replays the recipe with "
                           "research/kit/rebuild.py and compares fingerprints."),
    }
    if spec is not None:
        extra = {k: v for k, v in spec.items() if k not in ("constructor", "params")} \
            if isinstance(spec, dict) else None
        if extra:
            manifest["spec_context"] = extra
    if artifact_path and os.path.exists(artifact_path):
        with open(artifact_path, "rb") as f:
            manifest["artifact_sha256"] = hashlib.sha256(f.read()).hexdigest()
    os.makedirs(repro_dir, exist_ok=True)
    out = os.path.join(repro_dir, f"{slug}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return out

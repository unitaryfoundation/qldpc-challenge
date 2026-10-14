"""Confirm a candidate's distance beyond the screening upper bound -- by reusing
the repo's existing server-side certifiers on a code you are still building,
without hand-writing a submission first.

The screening number from ``surrogate.distance_rand`` is an upper bound. Before
you claim a distance, confirm it. Two independent confirmations, both built on
tools the repo already ships:

* ``exact_distance``  -> ``verify/certify.py`` (scipy/HiGHS MILP, the ``d=``
  tier): proves no lighter nontrivial logical exists, per side. Needs **scipy**.
* ``sat_exact_distance`` -> ``verify/sat_certify.py`` (SAT, the same ``d=``
  tier): the same proof by a different route, and the one to reach for as k
  grows. Needs **pycryptosat** and **python-sat**.
* ``decoder_distance`` -> ``decode/distance.py`` (BP+OSD residual witnesses): an
  independent upper-bound mechanism (a decoder's mistakes, not linear algebra);
  agreement with the surrogate strengthens corroboration. Needs **ldpc**.

These dependencies are optional (see the ``research`` extra in pyproject.toml).
If one is missing, the call raises a clear ImportError telling you how to get it
(``uv run --extra research python ...``). Both take raw ``(HX, HZ)`` and build
the throwaway submission doc the certifiers consume via ``submit.make_submission``.
"""
import importlib.util
import os

import numpy as np

from submit import make_submission

_HERE = os.path.dirname(os.path.abspath(__file__))
_VERIFY = os.path.join(_HERE, "..", "..", "verify")
_DECODE = os.path.join(_HERE, "..", "..", "decode")


def _load_module(path, name):
    """Import a module by explicit file path (avoids the name clash between this
    file and decode/distance.py, and lets the target's own sys.path inserts for
    gf2 take effect)."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _throwaway_doc(HX, HZ, trials, seed):
    """A minimal, schema-shaped doc (with witnesses and per-side distance values)
    for a code under construction -- enough for the certifiers, no provenance."""
    return make_submission(
        HX, HZ, name="(in-progress)", construction="(in-progress)",
        authors=["?"], tracks=[], trials=trials, seed=seed,
    )


def exact_distance(HX, HZ, tlim=600, trials=4000, seed=0, d_upper=None):
    """Exact distance certification via ``verify/certify.py`` (scipy MILP).

    Proves, per side, whether any nontrivial logical lighter than the claimed
    value exists. The claim defaults to a surrogate upper bound found with
    ``trials`` random restarts; pass ``d_upper={"X": wx, "Z": wz}`` to skip that
    and certify against values you already trust. **Raise ``trials`` until the
    upper bound has converged first** -- certifying against a loose bound proves
    a weaker statement.

    Returns the ``certify()`` dict: per-side ``exact`` True/False/timeout and the
    overall ``d_exact`` flag. Requires scipy.
    """
    try:
        certify = _load_module(os.path.join(_VERIFY, "certify.py"), "_qldpc_certify")
    except ImportError as e:
        raise ImportError(
            "exact_distance needs scipy (verify/certify.py), part of the `research` "
            "extra: `uv run --extra research python your_script.py`. "
            f"Underlying error: {e}")
    doc = _throwaway_doc(HX, HZ, trials, seed)
    if d_upper:
        for side, val in d_upper.items():
            if side in doc["distance"]:
                doc["distance"][side]["value"] = int(val)
        doc["distance"]["d"] = int(min(doc["distance"][s]["value"]
                                       for s in ("X", "Z") if s in doc["distance"]))
    return certify.certify(doc, tlim=tlim)


def sat_exact_distance(HX, HZ, tlim=600, trials=4000, seed=0, d_upper=None):
    """Exact distance certification via ``verify/sat_certify.py`` (SAT).

    Same question and same contract as :func:`exact_distance`, different
    machinery: parity constraints go to a SAT solver as native XOR clauses and
    only the weight bound is encoded. Prefer this one as k grows. The MILP path
    and the per-generator SAT form both pay a solve per logical generator per
    side, while this asks once using selector variables, and on board entries at
    W = d - 1 that is 2.5x at k = 6, 5.5x at k = 8, and the difference between
    closing and not closing at k = 28.

    Returns the same shape as :func:`exact_distance`, plus a per-side ``status``
    and, when a claim is refuted, the witness that refutes it. Requires
    pycryptosat and python-sat.
    """
    try:
        sat_certify = _load_module(os.path.join(_VERIFY, "sat_certify.py"),
                                   "_qldpc_sat_certify")
    except ImportError as e:
        raise ImportError(
            "sat_exact_distance needs pycryptosat and python-sat "
            "(verify/sat_certify.py), part of the `research` extra: "
            "`uv run --extra research python your_script.py`. "
            f"Underlying error: {e}")
    doc = _throwaway_doc(HX, HZ, trials, seed)
    if d_upper:
        for side, val in d_upper.items():
            if side in doc["distance"]:
                doc["distance"][side]["value"] = int(val)
        doc["distance"]["d"] = int(min(doc["distance"][s]["value"]
                                       for s in ("X", "Z") if s in doc["distance"]))
    return sat_certify.certify(doc, tlim=tlim)


def decoder_distance(HX, HZ, trials=200000, seed=0, max_seconds=None,
                     witness_trials=2000):
    """Independent decoder-based distance evidence via ``decode/distance.py``
    (BP+OSD residual witnesses).

    Injects random errors, decodes with a pinned BP+OSD decoder, and reports the
    lightest nontrivial logical the decoder's residuals reveal -- an upper bound
    from a different mechanism than the linear-algebra surrogate. ``verdict`` is
    relative to a surrogate seed claim; the useful output is ``d_heuristic`` and
    the per-side witnesses. Requires ldpc (``uv run --extra research ...``).
    """
    try:
        decdist = _load_module(os.path.join(_DECODE, "distance.py"), "_qldpc_decdist")
    except ImportError as e:
        raise ImportError(
            "decoder_distance needs ldpc (decode/distance.py), part of the `research` "
            "extra: `uv run --extra research python your_script.py`. "
            f"Underlying error: {e}")
    doc = _throwaway_doc(HX, HZ, witness_trials, seed)
    return decdist.estimate(doc, trials=trials, seed=seed, max_seconds=max_seconds)


if __name__ == "__main__":
    # Confirm a small known code both ways (each is a no-op if its dep is absent).
    from bb import build_bb, KNOWN
    p = KNOWN["[[72,12,6]]"]
    HX, HZ = build_bb(p["l"], p["m"], p["A"], p["B"])
    print("code [[72,12,6]] -- confirming distance two ways:")
    try:
        res = exact_distance(HX, HZ, tlim=120, trials=2000)
        print("  exact (scipy MILP):", {k: v.get("exact") if isinstance(v, dict) else v
                                        for k, v in res.get("sides", {}).items()},
              "d_exact=", res.get("d_exact"))
    except ImportError as e:
        print("  exact: skipped --", str(e).splitlines()[0])
    try:
        res = decoder_distance(HX, HZ, trials=20000, max_seconds=30)
        print("  decoder (BP+OSD):", res.get("d_heuristic"), res.get("verdict"))
    except ImportError as e:
        print("  decoder: skipped --", str(e).splitlines()[0])

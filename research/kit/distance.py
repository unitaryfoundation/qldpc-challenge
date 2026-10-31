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
import functools
import importlib.util
import os
import sys

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


# ---------------------------------------------------------------------------
# Qubitserf (https://github.com/Quantinuum/Qubitserf) -- OPTIONAL, OUT-OF-BAND.
#
# A C++/GPU library that returns the EXACT distance, or nothing. It is not a
# certificate and never becomes one: verify/ is the trust anchor, and a number
# from outside this repo cannot populate ``confidence: "exact"``. Two uses it is
# genuinely better at than the surrogates here:
#
#   1. Ranking candidates on true distance instead of a Monte Carlo bound.
#      distance_rand inflates -- AUTORESEARCH.md notes "a high d at low trials
#      usually means the search hasn't found the light logical yet". This has
#      no such failure mode: it either proves d or returns nothing.
#   2. Triaging where sat_exact_distance() is worth its budget.
#
# Measured on this board (8-core CPU box, 2026-10): cc agrees with the board's
# own certifiers on 211/211 sampled certified entries spanning d=2..14, and is
# 600-4000x faster than them on the same entries. Its REACH is not better --
# every d>=16 code tried stalled past 280s, including k=2 ones. Cost tracks
# the search depth d, not n, k, or check weight.
# ---------------------------------------------------------------------------


def _qsf_import():
    # An in-tree build keeps the native lib at Qubitserf/python/qubitserf/_lib,
    # so the checkout's python/ directory has to be importable. Honour an
    # explicit path rather than making everyone pip-install the wheel.
    _p = os.environ.get("QUBITSERF_PYTHON")
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)
    try:
        from qubitserf import distfind as _df
    except ImportError as e:
        raise ImportError(
            "Qubitserf is not importable. It is an out-of-band C++ build, not a "
            "pip dependency of this repo: `git clone "
            "https://github.com/Quantinuum/Qubitserf && cd Qubitserf && "
            "python -m pip install .` (needs CMake >= 3.20 and a C++17 "
            "compiler; CUDA/Metal optional and NOT recommended for qLDPC -- on "
            "sparse codes CPU connected-cluster beats GPU Brouwer-Zimmerman by "
            "orders of magnitude). For an in-tree build, set "
            "QUBITSERF_PYTHON=/path/to/Qubitserf/python. "
            f"Underlying error: {e}")
    return _df


_QSF_SUBPROCESS_SRC = r"""
import os, sys
import numpy as np
sys.path.insert(0, os.environ.get("QUBITSERF_PYTHON", ""))
from qubitserf import distfind as df
HX = np.load(sys.argv[1])["HX"]
HZ = np.load(sys.argv[2])["HZ"]
print("RESULT", df.css_distance(HX, HZ, method=sys.argv[3], which=sys.argv[4],
                                threads=int(sys.argv[5])))
"""


def _qsf_subprocess(HX, HZ, method, which, threads, tlim):
    """Timeout by real process kill for callers that cannot fork.

    A ``multiprocessing.Pool`` worker is daemonic and may not have children, so
    the fork path in :func:`qubitserf_distance` is unavailable under
    ``screen(workers=N)``. ``subprocess`` sidesteps the daemon flag and still
    gives a genuine kill rather than an abandoned thread.
    """
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        fx = os.path.join(td, "HX.npz")
        fz = os.path.join(td, "HZ.npz")
        np.savez_compressed(fx, HX=np.asarray(HX, dtype=np.uint8))
        np.savez_compressed(fz, HZ=np.asarray(HZ, dtype=np.uint8))
        env = dict(os.environ)
        env.setdefault("OMP_NUM_THREADS", str(max(1, int(threads))))
        try:
            r = subprocess.run(
                [sys.executable, "-c", _QSF_SUBPROCESS_SRC, fx, fz,
                 method, which, str(threads)],
                capture_output=True, text=True, timeout=tlim, env=env,
                check=False)  # rc surfaces via the no-RESULT RuntimeError below
        except subprocess.TimeoutExpired:
            return None
        for line in r.stdout.splitlines():
            if line.startswith("RESULT "):
                out = int(line.split()[1])
                return None if out == -1 else out
        raise RuntimeError(
            f"qubitserf subprocess produced no result "
            f"(rc={r.returncode}): {r.stderr.strip()[-300:]}")


def qubitserf_distance(HX, HZ, method="cc", which="min", threads=0, tlim=600):
    """Exact CSS distance via Qubitserf, or ``None`` if it did not finish.

    ``method="cc"`` (connected cluster) is the one for sparse qLDPC codes and
    the only one to try first; ``"mitm"`` is an independent cross-check on
    small codes. ``"bz"`` targets dense codes, is the only GPU-capable one, and
    was NOT reproducible here -- it stalled past 90s on the [[144,12,12]] gross
    code where its own docs claim 3.87s.

    ``tlim`` is a wall-clock budget enforced by a real process kill, because a C
    extension never yields to SIGALRM. A killed run returns ``None``, kept
    deliberately distinct from any answer: only a returned integer counts.
    """
    _df = _qsf_import()
    import multiprocessing as mp

    ctx = mp.get_context("fork")

    def _run(q):
        try:
            q.put(_df.css_distance(HX, HZ, method=method, which=which,
                                   threads=threads))
        except Exception as e:  # noqa: BLE001 -- surfaced to the parent
            q.put(f"error:{type(e).__name__}: {e}")

    q = ctx.Queue()
    p = ctx.Process(target=_run, args=(q,))
    try:
        p.start()
    except AssertionError:
        # Daemonic caller (a Pool worker): it cannot fork a child of its own.
        p.close()
        return _qsf_subprocess(HX, HZ, method, which, threads, tlim)
    p.join(tlim)
    if p.is_alive():
        p.terminate()
        p.join(5)
        if p.is_alive():
            p.kill()
            p.join()
        return None
    try:
        out = q.get_nowait()
    except Exception:
        return None
    if isinstance(out, str):
        raise RuntimeError(f"qubitserf: {out}")
    return None if out == -1 else int(out)


def qubitserf_screen(HX, HZ, trials=None, seed=0, backend=None, threads=1,
                     method="cc", tlim=120, **_):
    """Screen a code with Qubitserf's connected-cluster exact distance.

    Signature-compatible with ``surrogate.distance_rand`` so it drops into
    ``screen(..., distance=qubitserf_screen)`` unchanged. ``trials`` and
    ``backend`` are accepted and ignored -- there are no random restarts to run,
    and ``backend`` means the bit-packed RIS backend to ``distance_rand``, not
    Qubitserf's cpu/gpu selector.

    Returns ``float("inf")`` when a code does not finish in ``tlim``, which is
    exactly what ``distance_rand`` returns when it finds no logical, so screen
    drops the candidate. A returned value is exact *as far as Qubitserf is
    concerned*, which is not a claim about your code: label anything you submit
    ``upper_bound`` and let the gate speak.
    """
    d = qubitserf_distance(HX, HZ, method=method, threads=threads, tlim=tlim)
    return float("inf") if d is None else d


SCREENS = ("rand", "qubitserf")


def resolve_screen(name="qubitserf", *, fallback=True, **overrides):
    """Resolve a ``search.screen`` distance backend by name: ``"rand"`` or ``"qubitserf"``.

    ``"qubitserf"`` resolves to :func:`qubitserf_screen` with ``tlim``
    defaulting to 30 -- the measured knee of 2026-10: over 279 board codes a
    30 s cap returned the large majority of the answers for a small fraction
    of the compute -- and any keyword given here overrides that default.
    ``"rand"`` resolves to ``surrogate.distance_rand``, the Monte Carlo upper
    bound that is and stays the kit's default estimator.

    With ``fallback=True`` (the default), a machine without the Qubitserf
    build degrades to ``distance_rand`` instead of raising, so a sweep runs
    anywhere -- but a degraded run is a BOUND, not exact, and its records
    carry whatever the surrogate returns, inflated upward. Pass
    ``fallback=False`` to require the exact backend.

    Either backend returns ``float("inf")`` for a code it cannot resolve in
    budget, and ``screen`` drops that candidate. Dropped means *unknown, not
    refuted*: a family swept away by a small ``tlim`` has not been shown
    empty, so never treat a screen drop as the last word on a family.
    """
    if name == "rand":
        from surrogate import distance_rand
        return distance_rand
    if name == "qubitserf":
        try:
            _qsf_import()
        except ImportError:
            if not fallback:
                raise
            from surrogate import distance_rand
            return distance_rand
        overrides.setdefault("tlim", 30)
        return functools.partial(qubitserf_screen, **overrides)
    raise ValueError(f"unknown screen backend {name!r}; expected one of {SCREENS}")


def verify_with_cc(HX, HZ, *, tlim_qsf=300, tlim_sat=600, trials=4000,
                   seed=0, which="both"):
    """Two-stage verification: connected cluster proposes, the repo decides.

    This is the same division of labor ``escalation.exact_first`` already makes
    -- try a cheap exact check *before* spending a deep RIS ladder, and let
    anything that fails fall through -- with the caps raised. That function is
    bounded to ``n <= 90, d <= 8`` because it calls ``verify/certify.py``
    (MILP) directly, and MILP is what stops there. ``cc`` reaches n=937,
    d=14 at a ~0.03s median, so it can decide whether the expensive stage is
    worth starting at all.

    Stage 1 -- ``qubitserf_distance`` per side. Exact or nothing.
    Stage 2 -- ``verify/sat_certify.py``, unchanged. **It is the authority**;
    cc only decides whether stage 2 starts and where each side aims. Measured
    2026-10-14: the tight bound does NOT make the SAT solve cheaper -- within
    2% of a loose screening bound on entries spanning k=1..68 -- so this
    wrapper exists for experimentation, not for speed.

    Returns::

        {"outcome": "exact" | "refuted" | "timeout" | "unverified",
         "cc_d": int or None, "cc_X": .., "cc_Z": ..,
         "sat": verify/sat_certify.py's dict, or None if stage 2 was skipped}

    * ``exact``   -- stage 2 confirmed ``d_exact``. A real certificate; the
      maintainer re-runs the same certifier.
    * ``refuted`` -- stage 2 found a logical lighter than the claim. cc caught
      the over-claim in the sense that it existed to catch it; do not trust it.
    * ``timeout`` -- cc produced nothing and stage 2 did not close either.
      **Never a result.** No amount of care turns it into one.
    * ``unverified`` -- cc returned nothing, so no tight bound was available
      and stage 2 was not run.

    cc is deliberately not consulted in the verdict: its answer only decides
    whether stage 2 starts and where it aims.
    """
    cc_x = cc_z = None
    cc_d = None
    if which in ("both", "x"):
        cc_x = qubitserf_distance(HX, HZ, which="x", tlim=tlim_qsf)
    if which in ("both", "z"):
        cc_z = qubitserf_distance(HX, HZ, which="z", tlim=tlim_qsf)
    sides = [v for v in (cc_x, cc_z) if v is not None]
    if sides:
        cc_d = min(sides)
        # The bound stage 2 tests: per-side, so each solve aims at the value
        # that side actually achieved rather than the weaker minimum.
        d_up = {"X": cc_x if cc_x is not None else cc_d,
                "Z": cc_z if cc_z is not None else cc_d}
        sat = sat_exact_distance(HX, HZ, tlim=tlim_sat, trials=trials,
                                 seed=seed, d_upper=d_up)
        if sat.get("d_exact"):
            outcome = "exact"
        elif any("REFUTED" in ((v or {}).get("note") or "")
                 for v in (sat.get("sides") or {}).values()):
            outcome = "refuted"
        else:
            outcome = "timeout"
        return {"outcome": outcome, "cc_d": cc_d, "cc_X": cc_x, "cc_Z": cc_z,
                "sat": sat}
    # No tight bound from stage 1: fall through to the ladder rather than
    # guessing. Reporting None keeps that decision the caller's.
    return {"outcome": "unverified", "cc_d": None, "cc_X": None,
            "cc_Z": None, "sat": None}


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


# ---------------------------------------------------------------------------
# SAT-based lower bounds for screening (issue: "use SAT estimators as lower
# bounds instead of exact bounds")
# ---------------------------------------------------------------------------

def _gf2():
    """Lazy import of verify/gf2.py (GF(2) rank)."""
    import os, sys
    _v = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "verify")
    if _v not in sys.path:
        sys.path.insert(0, _v)
    import gf2 as _g
    return _g


def weight_one_logical_exists(HX, HZ):
    """Cheap, exact linear-algebra check for a distance-1 code.

    A weight-1 logical on the X side exists iff some qubit ``q`` has a zero
    column in ``HZ`` (so ``e_q`` commutes with every Z check) and ``e_q`` is
    not a product of X checks (not in rowspace(HX)). The Z side is symmetric.

    This is the whole content of "can we show d >= 2": a SAT instance at
    ``W = 1`` asks exactly this question, and the linear-algebra answer is
    both cheaper and exact. Returns ``True`` when at least one side has a
    weight-1 logical, i.e. when the code's distance is 1.
    """
    HX = np.asarray(HX, dtype=np.int8) % 2
    HZ = np.asarray(HZ, dtype=np.int8) % 2
    n = int(HX.shape[1])
    gf2 = _gf2()
    for side_self, side_opp in ((HX, HZ), (HZ, HX)):
        for q in range(n):
            if int(side_opp[:, q].sum()) != 0:
                continue
            v = np.zeros(n, dtype=np.int8)
            v[q] = 1
            # in rowspace iff rank does not grow
            if gf2.rank(np.vstack([side_self, v.reshape(1, -1)])) \
                    == gf2.rank(side_self):
                continue  # stabilizer, trivial
            return True
    return False


def sat_lower_bound(HX, HZ, min_d=2, tlim=60.0, trials=200, seed=0):
    """Use the SAT certifier as a *lower*-bound screen.

    Claims ``d = min_d`` (so ``W = min_d - 1``) and runs
    ``verify/sat_certify.py`` unchanged. The outcome is about whether a
    nontrivial logical of weight ``< min_d`` exists:

      * ``"proved"``    -- UNSAT on both sides: no logical lighter than
        ``min_d``, so the true distance is ``>= min_d``. Safe to keep.
      * ``"refuted"``   -- SAT on at least one side: a logical of weight
        ``<= min_d - 1`` exists; carries it as ``witness``. Drop the code
        (its distance is below ``min_d``).
      * ``"timeout"``   -- the solver ran out of budget on (at least) one
        side. **Inconclusive, not a refutation**: the code may still have
        ``d >= min_d``. Do not drop on a timeout; treat it as "unresolved".
      * ``"error"``     -- the certifier raised (bad pairing set, missing
        dep, ...); details in ``detail``.

    This is the screening analogue of ``sat_exact_distance`` with a shallow
    claim: cheap (seconds for ``min_d`` up to ~6 on board-sized codes) and
    it only ever says "definitely too light" or "definitely not too light",
    never an exact distance. A code that is "proved" here still needs the
    full gate / exact certification before anything is claimed.

    Returns a dict with ``min_d``, ``outcome``, ``d_exact``, ``sides``,
    ``witness`` (when refuted), ``secs`` and, on timeout, which side timed
    out.
    """
    import time
    t0 = time.monotonic()
    try:
        res = sat_exact_distance(HX, HZ, tlim=tlim, trials=trials, seed=seed,
                                 d_upper={"X": int(min_d), "Z": int(min_d)})
    except Exception as e:  # noqa: BLE001 -- reported, not raised
        return {"min_d": int(min_d), "outcome": "error",
                "detail": f"{type(e).__name__}: {e}",
                "secs": round(time.monotonic() - t0, 2)}
    sides = res.get("sides") or {}
    secs = round(time.monotonic() - t0, 2)
    witness = None
    timed_out = [s for s, b in sides.items()
                 if (b or {}).get("status") == "TIMEOUT"]
    refuted = [s for s, b in sides.items()
               if (b or {}).get("status") == "SAT"]
    for s in refuted:
        w = (sides[s] or {}).get("witness")
        if w is not None:
            witness = {"side": s, "support": list(w)}
            break
    if refuted:
        outcome = "refuted"
    elif timed_out:
        outcome = "timeout"
    elif res.get("d_exact"):
        outcome = "proved"
    else:
        outcome = "timeout"
    out = {"min_d": int(min_d), "outcome": outcome,
           "d_exact": bool(res.get("d_exact")),
           "sides": sides, "secs": secs}
    if witness is not None:
        out["witness"] = witness
    if timed_out:
        out["timed_out_sides"] = timed_out
    return out


def sat_screen(HX, HZ, *, min_d=2, tlim=60.0, trials=200, seed=0):
    """Screen predicate built on :func:`sat_lower_bound`.

    Returns ``True`` when the code is *shown* to have distance ``< min_d``
    (drop it), ``False`` when it is shown to have distance ``>= min_d``
    (keep it), and ``None`` when the solver timed out (inconclusive -- the
    caller decides, but the safe default is to keep and let the surrogate /
    gate speak). This is the shape a ``search.screen`` filter can consume.

    Note the asymmetry with ``surrogate.distance_rand``: the surrogate is an
    upper bound that drops on a *found* logical; this is a lower bound that
    drops on a *proved* low logical. Timeouts never drop.
    """
    r = sat_lower_bound(HX, HZ, min_d=min_d, tlim=tlim, trials=trials,
                        seed=seed)
    if r["outcome"] == "refuted":
        return True
    if r["outcome"] == "proved":
        return False
    return None

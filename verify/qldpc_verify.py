"""
qldpc-challenge submission verifier (Phase 0: structural + cheap semantic +
self-certifying distance upper bounds).

Usage:
    python verify/qldpc_verify.py codes/your-code.json

Exit code 0 if every required check passes, 1 otherwise. Prints a JSON report
to stdout. This covers the *trustless* tier: everything here is either a hard
arithmetic fact (CSS commutation, rank/k, witness validity) or a layout
measurement. It does NOT attempt to prove distance lower bounds / exactness;
that is the server-certification tier (Phase 5, separate solver stack).

What "verified" means per field:
  n           matches the qubit count implied by the checks
  k           = n - rank(H_X) - rank(H_Z), matches the claim exactly
  CSS         H_X H_Z^T = 0 over GF(2)
  distance    each provided side witness is a nontrivial logical operator of
              the claimed Pauli type and weight -> certifies d_side <= value
              as an UPPER BOUND. 'exact' claims are downgraded to upper_bound
              here and flagged for server certification.
  locality    for a 2d-local-* track: a layout (coordinates for all n qubits
              plus the number of physical `layers`) is required; at most
              `layers` qubits per site and distinct sites
              >= 1 apart (no cramming a small radius); measured interaction
              radius (max check diameter) within the track cap. Reports layout
              diagnostics (radius, qubits/site, spacing, density, bbox).
"""

import json
import re
import math
import os
import secrets
import sys

import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import gf2

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "..", "schema", "code.schema.json")
try:
    import jsonschema
    with open(_SCHEMA_PATH) as _f:
        _SCHEMA = json.load(_f)
except Exception:
    jsonschema = None
    _SCHEMA = None

# minimal required structure, used when jsonschema is unavailable
_REQUIRED = ["schema_version", "name", "code_type", "n", "k", "checks",
             "distance", "provenance"]

# Layer-2 family vocabulary. Self-declared (not recoverable from H), used only as
# a filterable tag. Validated here too, so enforcement holds even when jsonschema
# is unavailable and the minimal structure check runs instead.
_FAMILIES = {"bivariate-bicycle", "generalized-bicycle", "2bga-coset",
             "hypergraph-product", "lifted-product", "balanced-product",
             "quantum-tanner", "tile", "topological", "other"}
_NOVELTY = {"unknown", "known_parameters", "new_parameters"}

# Public CI resource limits. Finite by design so malformed or hostile JSON
# cannot force unbounded work. MAX_N is also the blocklength cap from the
# verification-budget rule (issue #249): above it the adaptive gate and MILP
# certification cannot stand behind a claim, so the board is a finite-length
# benchmark. Raise-only, as the tooling improves.
MAX_SUBMISSION_BYTES = 5_000_000
MAX_N = 700
MAX_CHECKS_PER_SIDE = 10_000
MAX_CHECK_WEIGHT = 32
MAX_TOTAL_SUPPORT = 200_000
MAX_COORDINATES = MAX_N
MAX_DENSE_MATRIX_CELLS = 50_000_000
MAX_COMMUTATION_CELLS = 50_000_000


def file_size_error(path):
    """Return a validation error string if a JSON submission file is too large."""
    try:
        size = os.path.getsize(path)
    except OSError as e:
        return f"could not stat file: {e}"
    if size > MAX_SUBMISSION_BYTES:
        return f"file has {size} bytes, limit is {MAX_SUBMISSION_BYTES}"
    return ""


def resource_errors(doc):
    """Resource caps checked before dense matrices are allocated."""
    n = doc["n"]
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    supports = X + Z
    errs = []
    if n > MAX_N:
        errs.append(f"n={n} exceeds the blocklength cap {MAX_N} "
                    f"(verification-budget rule, issue #249; the pipeline "
                    f"cannot stand behind a distance claim above it)")
    if len(X) > MAX_CHECKS_PER_SIDE:
        errs.append(f"checks.X has {len(X)} rows, limit is {MAX_CHECKS_PER_SIDE}")
    if len(Z) > MAX_CHECKS_PER_SIDE:
        errs.append(f"checks.Z has {len(Z)} rows, limit is {MAX_CHECKS_PER_SIDE}")
    total_support = sum(len(s) for s in supports)
    if total_support > MAX_TOTAL_SUPPORT:
        errs.append(f"total support entries {total_support} exceeds limit "
                    f"{MAX_TOTAL_SUPPORT}")
    max_weight = max((len(s) for s in supports), default=0)
    if max_weight > MAX_CHECK_WEIGHT:
        errs.append(f"max check weight {max_weight} exceeds limit {MAX_CHECK_WEIGHT}")
    for label, rows in (("H_X", len(X)), ("H_Z", len(Z))):
        cells = rows * n
        if cells > MAX_DENSE_MATRIX_CELLS:
            errs.append(f"{label} dense allocation would have {cells} cells, "
                        f"limit is {MAX_DENSE_MATRIX_CELLS}")
    comm_cells = len(X) * len(Z)
    if comm_cells > MAX_COMMUTATION_CELLS:
        errs.append(f"H_X H_Z^T commutation check would have {comm_cells} cells, "
                    f"limit is {MAX_COMMUTATION_CELLS}")
    loc = doc.get("locality") or {}
    coords = loc.get("coordinates") or []
    if len(coords) > MAX_COORDINATES:
        errs.append(f"locality.coordinates has {len(coords)} points, limit is "
                    f"{MAX_COORDINATES}")
    return errs


def structure_errors(doc):
    """Return a list of human-readable structural problems, or [] if the doc
    conforms. Uses jsonschema when installed, else a minimal key/type check."""
    if not isinstance(doc, dict):
        return ["top-level value is not a JSON object"]
    if jsonschema is not None and _SCHEMA is not None:
        v = jsonschema.Draft202012Validator(_SCHEMA)
        errs = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
                for e in sorted(v.iter_errors(doc), key=lambda e: list(e.path))]
    else:
        errs = [f"missing field: {k}" for k in _REQUIRED if k not in doc]
        if "checks" in doc and not (isinstance(doc["checks"], dict)
                                    and "X" in doc["checks"] and "Z" in doc["checks"]):
            errs.append("checks must have X and Z support lists")
        if "distance" in doc and not (isinstance(doc["distance"], dict)
                                      and all(k in doc["distance"] for k in ("d", "X", "Z"))):
            errs.append("distance must have d, X, and Z witness blocks")
        if "locality" in doc and not (isinstance(doc["locality"], dict)
                                      and "coordinates" in doc["locality"]
                                      and "layers" in doc["locality"]):
            errs.append("locality must have coordinates and layers")
    if errs:
        return errs
    return resource_errors(doc)


def signature(doc):
    """Permutation-invariant fingerprint via Weisfeiler-Leman color refinement
    on the Tanner graph (qubits + X-checks + Z-checks). Two codes equal up to a
    qubit permutation must share this hash; differing hashes are provably
    inequivalent. A collision only FLAGS a possible duplicate (WL is a strong
    necessary condition, not a complete equivalence test). Much finer than a
    plain degree multiset: it propagates neighborhood structure several hops."""
    import hashlib
    n = doc["n"]
    X, Z = doc["checks"]["X"], doc["checks"]["Z"]
    mx = len(X)
    # node ids: qubit q -> q; X-check i -> n+i; Z-check j -> n+mx+j
    nbr = [[] for _ in range(n + mx + len(Z))]
    for i, s in enumerate(X):
        for q in s:
            nbr[q].append(n + i)
            nbr[n + i].append(q)
    for j, s in enumerate(Z):
        for q in s:
            nbr[q].append(n + mx + j)
            nbr[n + mx + j].append(q)
    # initial colors by node type: qubit=0, X-check=1, Z-check=2
    color = [0] * n + [1] * mx + [2] * len(Z)
    for _ in range(min(6, len(nbr))):
        keyed = [(color[v], tuple(sorted(color[u] for u in nbr[v])))
                 for v in range(len(nbr))]
        order = {k: idx for idx, k in enumerate(sorted(set(keyed)))}
        newc = [order[k] for k in keyed]
        if newc == color:
            break
        color = newc
    cert = sorted(color)  # permutation-invariant multiset of final colors
    payload = json.dumps([n, doc["k"], doc["distance"]["d"], cert])
    return {"hash": hashlib.sha256(payload.encode()).hexdigest()[:16],
            "n": n, "k": doc["k"], "d": doc["distance"]["d"]}


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def _vec(support, n):
    v = np.zeros(n, dtype=np.int8)
    for q in support:
        v[q] ^= 1
    return v


def verify(doc, refute=False, seed=None):
    """Verify a submission. If ``refute`` is set, run the distance refutation with
    ``seed`` -- when ``seed is None`` a fresh RANDOM seed is drawn, so the gate is
    non-deterministic by design (an over-claim cannot reliably evade one fixed
    search). The seed used is reported in the ``distance_not_refuted`` detail, so a
    failing run is reproducible (re-run with that seed). Pass an explicit ``seed``
    to reproduce a run or for a deterministic test."""
    report = {"name": doc.get("name") if isinstance(doc, dict) else None,
              "checks": [], "ok": True, "computed": {}, "earned_distance": {}}

    def record(label, ok, detail=""):
        report["checks"].append({"check": label, "ok": bool(ok),
                                  "detail": detail})
        if not ok:
            report["ok"] = False

    # structural validation first: a malformed doc fails cleanly here rather
    # than crashing the arithmetic below.
    serr = structure_errors(doc)
    record("schema_valid", not serr, "; ".join(serr[:4]))
    if serr:
        return report
    # index bounds, gated before anything that indexes by qubit (signature,
    # matrix building) so an out-of-range index is reported here, cleanly,
    # rather than crashing into the generic guard below.
    n = doc["n"]
    sup = doc["checks"]["X"] + doc["checks"]["Z"]
    max_idx = max((max(s) for s in sup if s), default=-1)
    in_range = 0 <= max_idx < n
    record("qubit_indices_in_range", in_range, f"max index {max_idx}, n={n}")
    if not in_range:
        return report
    try:
        report["signature"] = signature(doc)
        return _verify_semantic(doc, report, record, refute, seed)
    except Exception as e:  # never crash on a hostile submission
        record("verifier_ran", False, f"{type(e).__name__}: {e}")
        return report


def _verify_semantic(doc, report, record, refute=False, seed=None):

    n = doc["n"]
    # index bounds already gated in verify(); safe to build matrices.
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)

    # exact-duplicate fingerprint: the reduced row echelon forms pin the
    # stabilizer GROUP (invariant to row recombination/reordering, sensitive
    # to qubit relabeling). Equal fingerprint => identical code, not just
    # equivalent. Permuted copies are caught by the WL signature instead.
    import hashlib
    fp = (gf2.rref(HX)[0].tobytes() + b"|" + gf2.rref(HZ)[0].tobytes())
    report["fingerprint"] = hashlib.sha256(fp).hexdigest()[:16]

    # checks have distinct supports per row (no repeated qubit within a row
    #    would have been XORed away; flag any that collapsed)
    empty_rows = [i for i, s in enumerate(doc["checks"]["X"] + doc["checks"]["Z"])
                  if len(set(s)) != len(s)]
    record("no_repeated_qubits_in_a_check", not empty_rows,
           f"rows with repeats: {empty_rows[:5]}")

    # 3. CSS commutation
    css = not bool(((HX @ HZ.T) % 2).any())
    record("css_commutation", css, "H_X H_Z^T = 0 over GF(2)")

    # 4. logical dimension k
    rx, rz = gf2.rank(HX), gf2.rank(HZ)
    k_computed = n - rx - rz
    report["computed"].update(n=n, rank_HX=rx, rank_HZ=rz, k=k_computed)
    record("k_matches_claim", k_computed == doc["k"],
           f"computed k={k_computed}, claimed {doc['k']}")
    # A code must encode at least one logical qubit; k<=0 is degenerate (nothing
    # to protect) and has no distance, so reject it outright.
    record("k_at_least_1", k_computed >= 1,
           f"computed k={k_computed}; a submission must encode >= 1 logical qubit")

    # 5. check weights (for the weight-bounded tracks)
    wmax = max((len(s) for s in doc["checks"]["X"] + doc["checks"]["Z"]),
               default=0)
    report["computed"]["max_check_weight"] = wmax
    # Layer-1 weight class (computed, nested: weight-4 < weight-6 < weight-8).
    # The tightest cap the max check weight fits under; ">8" for anything heavier
    # so every code still has a home on the weight axis.
    report["computed"]["weight_class"] = (
        "weight-4" if wmax <= 4 else "weight-6" if wmax <= 6
        else "weight-8" if wmax <= 8 else "weight-9plus")
    # Sparsity backstop: LDPC means a bounded, small check weight. The cap is far
    # above any plausible qLDPC code on this board (weights run to ~10), so it
    # only rejects a dense matrix submitted as a "code", not a real entry.
    record("check_weight_is_ldpc", wmax <= MAX_CHECK_WEIGHT,
           f"max check weight {wmax} far exceeds LDPC sparsity "
           f"(cap {MAX_CHECK_WEIGHT})"
           if wmax > MAX_CHECK_WEIGHT else f"max check weight {wmax}")

    # The model field is self-reported and unverifiable, but if one is claimed it
    # must name a specific version, not a bare vendor name: "Claude" tells a reader
    # nothing reproducible, "Claude Opus 4.8" does. Omitting it (a human or unknown
    # author) is fine; "human" is the explicit non-model sentinel.
    model = (doc.get("provenance") or {}).get("model")
    if isinstance(model, (list, tuple)):
        # an ensemble of models: every named member must carry a version
        model = ", ".join(str(x) for x in model)
    if model and model.strip() and model.strip().lower() != "human":
        specific = all(any(ch.isdigit() for ch in part)
                       for part in model.split(",") if part.strip())
        record("model_version_specified", specific,
               model if specific else
               f"'{model}' names no version; give the exact model, e.g. "
               "'Claude Opus 4.8', or omit the field")

    # Layer-2 family tag: optional, but if present must be from the vocabulary.
    family = doc.get("family")
    if family is not None:
        known = family in _FAMILIES
        # A genuinely new construction should not be forced into "other" just
        # because the vocabulary has not caught up. Accept a well-formed new tag
        # and flag it for review; the family is a filter, never a ranking input.
        wellformed = bool(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(family)))
        record("family_in_vocabulary", known or wellformed,
               family if known
               else f"'{family}' is a new family tag, accepted but not yet in "
                    "the vocabulary; please open an issue so the tracks and the "
                    "site labels can follow"
               if wellformed
               else f"'{family}' is malformed; use a lowercase-hyphenated tag, "
                    f"e.g. one of {sorted(_FAMILIES)}")

    novelty = (doc.get("provenance") or {}).get("novelty")
    if novelty is not None:
        record("novelty_in_vocabulary", novelty in _NOVELTY,
               novelty if novelty in _NOVELTY
               else f"'{novelty}' is not a known novelty status; use one of "
               f"{sorted(_NOVELTY)}")

    # 6. distance witnesses (self-certifying upper bounds)
    dist = doc["distance"]
    earned_d = []
    earned_sides = set()
    for side, opp_H, own_H in (("X", HZ, HX), ("Z", HX, HZ)):
        if side not in dist:
            record(f"distance_{side}_present", False,
                   "both X and Z distance witnesses are required")
            continue
        sd = dist[side]
        v = _vec(sd["witness"], n)
        wt = int(v.sum())
        in_ker = gf2.commutes(v, opp_H)          # commutes with opposite checks
        nontrivial = not gf2.in_rowspace(v, own_H)  # not a stabilizer product
        good = (wt == sd["value"]) and in_ker and nontrivial
        record(f"distance_{side}_witness", good,
               f"weight={wt} (claim {sd['value']}), in_ker={in_ker}, "
               f"nontrivial={nontrivial}")
        if good:
            tier = "upper_bound"  # 'exact' must be earned by server cert
            report["earned_distance"][side] = {"value": sd["value"],
                                               "tier": tier}
            earned_d.append(sd["value"])
            earned_sides.add(side)
            if sd["confidence"] == "exact":
                record(f"distance_{side}_exact_flagged", True,
                       "exact claim accepted as upper_bound pending server "
                       "certification")

    # 7. code distance consistency
    if earned_sides == {"X", "Z"}:
        d_earned = min(earned_d)
        matches = d_earned == dist["d"]
        record("d_matches_min_side", matches,
               f"min earned side = {d_earned}, claimed d = {dist['d']}")
        if matches:
            report["earned_distance"]["d"] = {"value": dist["d"],
                                              "tier": "upper_bound"}
    else:
        record("distance_global_earned", False,
               "valid X and Z witnesses are required to earn a global distance")

    # 8. independent distance refutation. A bounded RIS search must not find a
    #    logical lighter than the claimed distance. This is SOUND -- any hit is a
    #    checkable lighter logical, so a real over-claim -- but not complete (a
    #    clean pass is "no over-claim found at this budget", not a proof). Opt-in
    #    (`refute=True`): the per-submission gate runs it; fast/non-gate callers
    #    (site build, verify_all, research recipes) pass refute=False.
    #
    #    NON-DETERMINISTIC BY DESIGN: the seed is random unless one is passed, so an
    #    over-claim cannot reliably evade a single fixed search -- a re-run draws a
    #    new seed and gets another chance to catch it. The trade-off is that a
    #    re-run can change the verdict; the seed is always reported so a failing run
    #    is reproducible (verify(doc, refute=True, seed=<that seed>)).
    #
    #    FAILS CLOSED: if the refuter cannot run, that is recorded as a FAILURE, not
    #    a silent pass -- a gate that fails open is no gate.
    if refute and "d" in report["earned_distance"]:
        run_seed = seed if seed is not None else secrets.randbelow(2**31)
        try:
            import heuristic_distance
            refuted, d_found, wit, ntr = heuristic_distance.refute_check(doc, seed=run_seed)
            record("distance_not_refuted", not refuted,
                   (f"found weight-{d_found} logical < claimed {dist['d']} "
                    f"(seed {run_seed}); witness={wit}" if refuted
                    else f"no lighter logical in {ntr} RIS trials (seed {run_seed})"))
        except Exception as e:
            record("distance_not_refuted", False,
                   f"refutation could not run ({type(e).__name__}: {e}; seed "
                   f"{run_seed}); failing closed -- manual review required")

    # 9. locality / geometric 2D embedding. The locality CLASS is computed from
    #    the layout, never trusted from a self-declared track. A class is earned
    #    only by an honest layout:
    #      (a) a coordinate for every qubit;
    #      (b) no cramming: at most `layers` qubits may share a site (the
    #          flip-chip stack) and any two distinct sites are >= 1 apart, so a
    #          check of diameter r genuinely spans r grid units and a small
    #          radius cannot be faked by collapsing qubits onto a point;
    #      (c) short range: the measured interaction radius (largest check
    #          diameter) is within the class cap.
    #    Codes that fail (b)/(c), or carry no layout, are simply `unrestricted`
    #    (no 2D-local class), not rejected. "Short range" means a bounded,
    #    n-independent check diameter. The bilayer cap admits the weight-8 planar
    #    (tile-code) family: bulk checks span ~5.83, open-boundary corners ~6.71,
    #    both constant in n; 7.0 covers the family while rejecting layouts whose
    #    range grows with the code. Nesting: local-2d-single < local-2d-bilayer <
    #    unrestricted (the tighter class also qualifies for the looser ones; the
    #    site derives that). See TRACKS.md.
    LOCALITY_CLASSES = [   # tightest first
        ("local-2d-single",  1, 4.0),
        ("local-2d-bilayer", 2, 7.0),
    ]
    locality_class = "unrestricted"
    loc = doc.get("locality")
    if loc is not None:
        coords = loc["coordinates"]
        layers = loc.get("layers", 1)
        cover = len(coords) == n
        record("coordinates_cover_all_qubits", cover,
               f"{len(coords)} coords, n={n}")
        if cover:
            pts = [tuple(c) for c in coords]

            def diam(sup):
                ps = [coords[q] for q in sup]
                return max((math.dist(a, b) for a in ps for b in ps),
                           default=0.0)
            radius = max((diam(s) for s in doc["checks"]["X"]
                          + doc["checks"]["Z"]), default=0.0)

            from collections import Counter
            mult = Counter(pts)
            max_mult = max(mult.values())
            sites = sorted(mult)
            min_spacing = min((math.dist(a, b)
                               for i, a in enumerate(sites)
                               for b in sites[i + 1:]), default=float("inf"))
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = [round(max(xs) - min(xs), 4), round(max(ys) - min(ys), 4)]
            area = bbox[0] * bbox[1]
            report["computed"]["locality"] = {
                "interaction_radius": round(radius, 4),
                "layers": layers,
                "max_qubits_per_site": max_mult,
                "min_site_spacing": (round(min_spacing, 4)
                                     if min_spacing != float("inf") else None),
                "qubits_per_unit_area": round(len(pts) / area, 4) if area else None,
                "bbox": bbox,
            }
            if "interaction_radius" in loc:
                record("interaction_radius_within_claim",
                       radius <= loc["interaction_radius"] + 1e-9,
                       f"measured {radius:.4f} <= claim "
                       f"{loc['interaction_radius']}")
            honest = max_mult <= layers and min_spacing >= 1.0 - 1e-9
            if honest:
                for cls, max_layers, cap in LOCALITY_CLASSES:
                    if layers <= max_layers and radius <= cap + 1e-9:
                        locality_class = cls
                        break
    # Layer-1 locality class (computed) + Layer-3 flags (verifier-proven only;
    # the exact-d flag is added at site-build time from certs/, since exactness
    # is certified separately, not by this trustless check).
    report["computed"]["locality_class"] = locality_class
    report["computed"]["flags"] = {
        "css": bool(report["checks"] and
                    all(c["ok"] for c in report["checks"]
                        if c["check"] == "css_commutation")),
        "locality_class": locality_class,
    }

    return report


def main(path):
    ferr = file_size_error(path)
    if ferr:
        print(json.dumps({"name": None,
                          "checks": [{"check": "file_size_within_limit",
                                      "ok": False, "detail": ferr}],
                          "ok": False, "computed": {}, "earned_distance": {}},
                         indent=2))
        return 1
    try:
        with open(path) as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"could not open {path}: file not found", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"could not parse {path}: not valid JSON ({e})", file=sys.stderr)
        return 2
    report = verify(doc, refute=True)   # the per-submission CLI runs the gate
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python qldpc_verify.py <submission.json>",
              file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))

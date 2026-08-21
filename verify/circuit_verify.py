"""
Circuit-tier verifier (RFC 0001, issue #505): the deterministic fast path.

Usage:
    python verify/circuit_verify.py codes/your-code.json [circuits-dir]

Exit code 0 iff every check passes for both bases. Prints a JSON report to
stdout, in the shape of qldpc_verify's. The circuits directory defaults to
circuits/<slug>/ next to the codes/ tree the JSON lives in.

Checks, per basis (RFC 0001 numbering):
  1. validity       the noiseless skeleton's detectors and observables are
                    deterministic (stim rejects an extraction that fails to
                    measure the stabilizer group faithfully)
  2. noise recipe   the circuit is exactly apply_noise(strip_noise(circuit))
                    at the reference rate, and every TICK layer is genuinely
                    parallel (no qubit operated on twice in a layer). Layer
                    count controls idle-data noise, so without the second half
                    deleting TICKs -- pure annotations -- would shed fault
                    mechanisms and inflate d_circ (vprusso's #646 review);
                    with it, merging layers is legal exactly when a device
                    could run them simultaneously (circuit_tools docstring)
  3. code binding   observables = the code's k declared-basis logicals on the
                    final transversal readout; closure detectors match the
                    declared check matrix rows; data qubits are 0..n-1; the
                    declared round count is what the circuit performs
  5. witness        the committed .dem re-derives from the committed .stim
                    under the pinned stim, mechanism-for-mechanism (exact
                    structure and file order; probabilities to float
                    tolerance -- their last ulps are architecture-sensitive
                    and the distance tier never reads them), and the claimed
                    witness is an undetected logical fault set of the claimed
                    weight in it, with value <= d (penalty-only clamp)

Step 4 (circuit locality, geometric tier) is Phase B. Step 6, the adversarial
refutation search, runs in the CI gate (gate_changed.py), not here: this file
is the milliseconds half, the search is the expensive half. Trust layering as
for d: stim is trusted only to produce the committed DEM artifact -- which is
re-derived and diffed, never taken on faith -- and the arithmetic that accepts
the witness is the board's own.
"""

import json
import os
import sys
from collections import Counter

import numpy as np
import stim

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2
import circuit_tools as ct
from qldpc_verify import _matrix

MAX_CIRCUIT_FILE_BYTES = 5_000_000

# Verification-budget cap for the circuit tier (the RFC's "cap the tier by
# n*rounds", enforced on the actual cost driver): the refutation gate searches
# ker(H_dem) by RIS, and per-trial cost fits ~2e-13 * mechanisms^3 seconds
# with the in-C++ trial loop (gf2_fast.dem_rand_witness, measured 2026-08-21;
# the 2026-08-20 numpy-orchestrated loop this cap was first sized against was
# ~6x slower). At the cap a trial is ~3.1 s, so the gate's 120 s/basis target
# buys ~38 trials -- searchable at full depth, keeping a circuit entry within
# the same ~10-minute budget a deep code claim gets. Raise-only, as the
# search stack improves (GPU RIS is the known route up).
MAX_DEM_MECHANISMS = 25_000

SIDE_FILES = {"X": "memory_x", "Z": "memory_z"}
SIDE_READOUT = {"X": "MX", "Z": "M"}


def _resolve_records(flat):
    """Measurement bookkeeping for a flat noiseless circuit: the list of
    measured qubits in record order, each detector's absolute record indices,
    and each observable's. Record references are relative to the measurement
    count at the annotation's position, so annotations may appear anywhere."""
    meas = []
    detectors = []
    observables = {}
    for inst in flat:
        name = inst.name
        if name in ct.MEASURES:
            meas.extend((t.qubit_value, name) for t in inst.targets_copy())
        elif name == "DETECTOR":
            detectors.append([len(meas) + t.value
                              for t in inst.targets_copy()])
        elif name == "OBSERVABLE_INCLUDE":
            j = int(inst.gate_args_copy()[0])
            observables.setdefault(j, []).extend(
                len(meas) + t.value for t in inst.targets_copy())
    return meas, detectors, observables


def _binding_errors(skel, basis, doc):
    """RFC step 3: [] plus display metadata iff the circuit is a memory
    experiment OF THIS CODE in this basis. Anchors: data qubits are 0..n-1,
    read out transversally in the protected basis after the last ancilla
    measurement; the k observables are independent declared-basis logicals on
    that readout; every closure detector's data support is a declared check
    row and every row appears; the declared round count is the maximum number
    of times any single qubit is measured mid-circuit (ancilla reuse -- the
    standard extraction shape; a gadget outside it needs a spec extension)."""
    n, k = doc["n"], doc["k"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    own_H, opp_H = (HZ, HX) if basis == "Z" else (HX, HZ)
    flat = skel.flattened()
    meas, detectors, observables = _resolve_records(flat)
    errs = []
    meta = {}

    total_q = flat.num_qubits
    meta["total_qubits"] = total_q
    meta["ancillas"] = total_q - n
    if total_q <= n:
        errs.append(f"circuit uses {total_q} qubits; a memory experiment for "
                    f"n={n} needs data 0..{n - 1} plus ancillas above them")
        return errs, meta
    anc_coords = (doc.get("circuit") or {}).get("ancilla_coordinates")
    if anc_coords is not None and len(anc_coords) != total_q - n:
        errs.append(f"ancilla_coordinates has {len(anc_coords)} entries but "
                    f"the circuit uses {total_q - n} non-data qubits")

    last_anc = max((i for i, (q, _) in enumerate(meas) if q >= n), default=-1)
    final = list(range(last_anc + 1, len(meas)))
    final_qubits = [meas[i][0] for i in final]
    if sorted(final_qubits) != list(range(n)):
        errs.append("final transversal readout after the last ancilla "
                    "measurement must measure each data qubit 0..n-1 exactly "
                    "once")
        return errs, meta
    want_readout = SIDE_READOUT[basis]
    bad_basis = [meas[i][1] for i in final if meas[i][1] != want_readout]
    if bad_basis:
        errs.append(f"final readout must be {want_readout} for a {basis}-basis "
                    f"memory; found {sorted(set(bad_basis))}")

    rounds_measured = max(Counter(meas[i][0]
                                  for i in range(last_anc + 1)).values(),
                          default=0)
    meta["rounds_measured"] = rounds_measured
    declared = (doc.get("circuit") or {}).get("rounds")
    if declared is not None and rounds_measured != declared:
        errs.append(f"declared rounds={declared} but the circuit performs "
                    f"{rounds_measured} (max mid-circuit measurements of any "
                    f"single qubit)")

    final_set = set(final)
    if sorted(observables) != list(range(k)):
        errs.append(f"circuit includes observables {sorted(observables)}; "
                    f"a memory experiment must include exactly 0..{k - 1}")
    V = np.zeros((len(observables), n), dtype=np.int8)
    for row, j in enumerate(sorted(observables)):
        recs = observables[j]
        if len(set(recs)) != len(recs) or not set(recs) <= final_set:
            errs.append(f"observable {j} must be a product of distinct final-"
                        f"readout measurements")
            continue
        for i in recs:
            V[row, meas[i][0]] = 1
        if not gf2.commutes(V[row], opp_H):
            errs.append(f"observable {j} does not commute with the declared "
                        f"{'X' if basis == 'Z' else 'Z'} checks: not a "
                        f"{basis}-type logical of this code")
        elif gf2.in_rowspace(V[row], own_H):
            errs.append(f"observable {j} is a product of declared {basis} "
                        f"stabilizers: trivial, protects nothing")
    if len(observables) == k and not errs:
        joint = gf2.rank(np.vstack([own_H, V]))
        if joint != gf2.rank(own_H) + k:
            errs.append(f"the {k} observables are not independent modulo the "
                        f"declared {basis} stabilizers")

    closure = [ds for ds in detectors if any(i in final_set for i in ds)]
    got = Counter(frozenset(meas[i][0] for i in ds if i in final_set)
                  for ds in closure)
    want = Counter(frozenset(int(q) for q in np.flatnonzero(row))
                   for row in own_H)
    if got != want:
        missing = list(want - got)
        extra = list(got - want)
        errs.append(f"closure-detector data supports must match the declared "
                    f"{basis}-check rows exactly; "
                    f"missing {sorted(map(sorted, missing))[:3]}, "
                    f"unexpected {sorted(map(sorted, extra))[:3]}")
    return errs, meta


def verify_circuit(doc, circuits_dir):
    """Full fast-path verdict for a submission's circuit block. Returns a
    report dict shaped like qldpc_verify's; report['ok'] is the verdict."""
    report = {"name": doc.get("name"), "checks": [], "ok": True,
              "computed": {}, "earned_d_circ": {}}

    def record(label, ok, detail=""):
        report["checks"].append({"check": label, "ok": bool(ok),
                                 "detail": detail})
        if not ok:
            report["ok"] = False

    cb = doc.get("circuit")
    if not cb:
        record("circuit_block_present", False,
               "submission declares no circuit tier")
        return report

    record("stim_version_pinned", cb["stim_version"] == stim.__version__,
           f"declared {cb['stim_version']}, pinned verifier stack runs "
           f"{stim.__version__}")
    d = doc["distance"]["d"]
    record("rounds_at_least_d", cb["rounds"] >= d,
           f"rounds={cb['rounds']}, code distance d={d} (fewer rounds "
           f"provably overestimate d_circ)")

    n = doc["n"]
    for side in ("X", "Z"):
        claim = cb["d_circ"][side]
        base = os.path.join(circuits_dir, SIDE_FILES[side])
        try:
            for ext in (".stim", ".dem"):
                if os.path.getsize(base + ext) > MAX_CIRCUIT_FILE_BYTES:
                    raise ValueError(f"{base + ext} exceeds "
                                     f"{MAX_CIRCUIT_FILE_BYTES} bytes")
            circuit = stim.Circuit(open(base + ".stim").read())
            committed = stim.DetectorErrorModel(open(base + ".dem").read())
        except Exception as e:
            record(f"{side}_circuit_files", False, f"{type(e).__name__}: {e}")
            continue
        record(f"{side}_circuit_files", True,
               f"{os.path.relpath(base, os.path.dirname(circuits_dir))}"
               f".stim/.dem")

        skel = ct.strip_noise(circuit)
        try:                                    # step 1: validity
            skel.detector_error_model()
            valid = skel.num_detectors > 0
            record(f"{side}_detectors_deterministic", valid,
                   f"{skel.num_detectors} deterministic detectors" if valid
                   else "circuit defines no detectors")
        except Exception as e:
            record(f"{side}_detectors_deterministic", False, str(e))
            continue

        nerrs = ct.noise_recipe_errors(circuit, n)  # step 2: noise recipe
        record(f"{side}_noise_recipe_canonical", not nerrs,
               "; ".join(nerrs) or
               f"canonical placement at reference rate {ct.P_REF}")

        berrs, meta = _binding_errors(skel, side, doc)  # step 3: code binding
        record(f"{side}_code_binding", not berrs, "; ".join(berrs[:4]) or
               f"k observables, checks, and rounds bound to the declared code")

        derived = ct.derive_dem(circuit)        # step 5: witness
        record(f"{side}_dem_within_budget",
               derived.num_errors <= MAX_DEM_MECHANISMS,
               f"{derived.num_errors} mechanisms (cap {MAX_DEM_MECHANISMS}: "
               f"verification-budget rule; the refutation gate must be able "
               f"to search this DEM)")
        if derived.num_errors > MAX_DEM_MECHANISMS:
            continue
        dem_match = ct.dem_matches(derived, committed)
        record(f"{side}_dem_reproduces", dem_match,
               "committed .dem re-derives mechanism-for-mechanism (exact "
               "structure and order; probabilities to float tolerance)"
               if dem_match else
               "committed .dem differs from the pinned re-derivation -- "
               "regenerate it with the pinned stim version")
        if not dem_match:
            continue
        werrs = ct.witness_errors(derived, claim["witness"], claim["value"])
        if claim["value"] > d:
            werrs.append(f"claimed d_circ {claim['value']} exceeds code "
                         f"distance d={d}: the tier is penalty-only, clamp "
                         f"the claim to d")
        record(f"{side}_witness_valid", not werrs, "; ".join(werrs) or
               f"weight-{claim['value']} undetected logical fault set "
               f"confirmed in GF(2)")

        meta.update(mechanisms=derived.num_errors,
                    detectors=derived.num_detectors)
        report["computed"][side] = meta
        side_checks = [c for c in report["checks"]
                       if c["check"].startswith(f"{side}_")]
        if all(c["ok"] for c in side_checks):
            report["earned_d_circ"][side] = {"value": claim["value"],
                                             "tier": "upper_bound"}

    if {"X", "Z"} <= set(report["earned_d_circ"]) and \
            report["checks"][0]["ok"] and report["checks"][1]["ok"]:
        report["earned_d_circ"]["d_circ"] = {
            "value": min(report["earned_d_circ"][s]["value"]
                         for s in ("X", "Z")),
            "tier": "upper_bound"}
    else:
        report["ok"] = False
    return report


def main(argv):
    if not 1 <= len(argv) <= 2:
        print("usage: python circuit_verify.py <submission.json> "
              "[circuits-dir]", file=sys.stderr)
        return 2
    path = argv[0]
    try:
        doc = json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        print(f"could not load {path}: {e}", file=sys.stderr)
        return 2
    slug = os.path.splitext(os.path.basename(path))[0]
    circuits_dir = argv[1] if len(argv) == 2 else os.path.join(
        os.path.dirname(os.path.abspath(path)), "..", "circuits", slug)
    report = verify_circuit(doc, circuits_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

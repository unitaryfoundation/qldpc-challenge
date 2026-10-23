"""Validation gate for changes to verify/: solved cases, broken artifacts, published reproductions (issue #4030).

verify/ is hash-pinned (check_validator_integrity.py), which answers "did it
change" and not "is the changed verifier right". This gate is the second
question, run before a re-pin, in the shape arXiv:2610.31352 gives an
evaluator-validation gate:

1. solved cases: small codes with analytically known properties. The gate
   builds them in code, so nothing on the board can move them: the Steane
   [[7,1,3]] and Shor [[9,1,3]] codes and the [[4,2,2]] code, each of which
   the structural verifier must accept with the right k and the exact
   certifier (verify/certify.py) must prove at the known distance; two Steane
   codes on disjoint qubits, which the connectivity check must refuse as a
   direct sum; and the Shor code with a Hadamard on two qubits filed as a
   stabilizer code, which the local-Clifford check must send back as the CSS
   code it is, naming the CSS image's fingerprint;
2. broken artifacts with expected diagnoses: one deliberately broken document
   per failure class of the preflight taxonomy (research/kit/prescreen.py:
   construction and weight are the code's fault, packaging, typing, witness,
   and layout the document's). The gate asserts the rejection, the check
   that fired, and the class, so a verifier that still rejects but for the
   wrong reason fails here;
3. published reproductions: seeded baselines and the mitten and ZSZ lifted
   product entries ("reconstructions checked against the authors' own
   matrices") re-run through the structural verifier and compared
   byte-for-byte with the committed verdicts under
   verify/fixtures/validation_gate/golden/. A changed entry is reported as
   such, distinct from a changed verdict.

``check_validator_integrity.py --update`` runs this gate first and refuses to
re-pin unless it exits 0. The gate adds, removes, and loosens no check; it
validates that the checks do what they claim. It imports nothing from
research/ (the taxonomy below is a mirror; research/test_prescreen.py asserts
the two agree).

    uv run python verify/validation_gate.py                 # exit 0 iff every part passes
    uv run python verify/validation_gate.py --update-golden # record the current verdicts (reviewable diff)
"""
import argparse
import copy
import hashlib
import itertools
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
import certify  # noqa: E402
import gf2  # noqa: E402
import qldpc_verify as V  # noqa: E402

GOLDEN_DIR = os.path.join(_HERE, "fixtures", "validation_gate", "golden")
CODES = os.path.join(_ROOT, "codes")
# Seeded baselines and the mitten (Bhardwaj et al.) and ZSZ lifted-product
# reconstructions: the entries whose verdicts a changed verifier must reproduce.
REPRODUCTIONS = ("7-1-3", "72-12-6", "144-12-12", "100-20-8", "120-24-8", "150-30-10",
                 "160-32-10", "160-36-6", "170-34-8", "180-36-8", "190-38-8")
# Mirror of research/kit/prescreen.py KINDS: which failed checks say the code
# is inadmissible as opposed to the document being wrong.
KINDS = {
    "construction": ("tanner_connected", "stabilizer_group_connected",
                     "css_commutation", "stabilizer_commutation",
                     "k_at_least_1"),
    "weight": ("check_weight_is_ldpc",),
    "typing": ("stabilizer_code_is_not_css",
               "stabilizer_code_is_not_locally_css"),
    "layout": ("coordinates_cover_all_qubits", "coordinates_uniform_dimension",
               "interaction_radius_within_claim", "site_occupancy_within_layers",
               "site_spacing_at_least_one", "modules_cover_all_qubits"),
    "other": ("verifier_ran",),
}
CODE_KINDS = frozenset({"construction", "weight"})


def kind_of(check, detail=""):
    """Classify a failed check the way research/kit/prescreen.py does."""
    for kind, names in KINDS.items():
        if check in names:
            return kind
    if check == "schema_valid" and any(part.startswith("checks/") and "is too long" in part
                                       for part in detail.split("; ")):
        return "weight"
    if check.startswith(("distance_", "d_matches_")):
        return "witness"
    return "packaging"


# -- solved cases ---------------------------------------------------------------

def _lightest_logical(H_ker, H_row, n):
    """Brute force the lightest vector in ker(H_ker) outside row(H_row); tiny n only."""
    Hk = np.asarray(H_ker, dtype=np.int8)
    rows = np.asarray(H_row, dtype=np.int8)
    rank_rows = gf2.rank(rows) if len(rows) else 0
    for w in range(1, n + 1):
        for supp in itertools.combinations(range(n), w):
            v = np.zeros(n, dtype=np.int8)
            v[list(supp)] = 1
            if ((Hk.astype(np.int64) @ v) % 2).any():
                continue
            if len(rows) and gf2.rank(np.vstack([rows, v])) == rank_rows:
                continue
            return list(supp)
    return None


def css_doc(name, HX, HZ, d, *, construction, family="other", confidence="exact"):
    """Build a complete CSS submission document for a small code, witnesses found by brute force."""
    HX = np.asarray(HX, dtype=np.int8)
    HZ = np.asarray(HZ, dtype=np.int8)
    n = HX.shape[1]
    k = n - gf2.rank(HX) - gf2.rank(HZ)
    wx = _lightest_logical(HZ, HX, n)
    wz = _lightest_logical(HX, HZ, n)
    return {"schema_version": "0.2", "name": name, "code_type": "CSS", "n": n, "k": int(k),
            "checks": {"X": [list(map(int, np.flatnonzero(r))) for r in HX],
                       "Z": [list(map(int, np.flatnonzero(r))) for r in HZ]},
            "distance": {"d": d, "X": {"value": len(wx), "confidence": confidence, "witness": wx},
                         "Z": {"value": len(wz), "confidence": confidence, "witness": wz}},
            "provenance": {"authors": ["validation gate"], "origin": "baseline",
                           "construction": construction, "date": "2026-10-23",
                           "references": ["arXiv:2610.31352"]},
            "family": family}


def steane():
    H = [[3, 4, 5, 6], [1, 2, 5, 6], [0, 2, 4, 6]]
    M = np.zeros((3, 7), dtype=np.int8)
    for i, s in enumerate(H):
        M[i, s] = 1
    return css_doc("[[7,1,3]] Steane code (validation gate)", M, M, 3,
                   construction="Steane code: HX = HZ = the Hamming(7,4) parity-check matrix",
                   family="topological")


def shor():
    HX = np.zeros((2, 9), dtype=np.int8)
    HX[0, 0:6] = 1
    HX[1, 3:9] = 1
    HZ = np.zeros((6, 9), dtype=np.int8)
    for i, (a, b) in enumerate([(0, 1), (1, 2), (3, 4), (4, 5), (6, 7), (7, 8)]):
        HZ[i, [a, b]] = 1
    return css_doc("[[9,1,3]] Shor code (validation gate)", HX, HZ, 3,
                   construction="Shor code: three bit-flip repetition blocks under a phase-flip repetition code")


def four_two_two():
    M = np.ones((1, 4), dtype=np.int8)
    return css_doc("[[4,2,2]] code (validation gate)", M, M, 2,
                   construction="the smallest error-detecting CSS code: one X check and one Z check on four qubits")


SOLVED = (("Steane [[7,1,3]]", steane, 1, 3), ("Shor [[9,1,3]]", shor, 1, 3), ("[[4,2,2]]", four_two_two, 2, 2))


def direct_sum_of_two_steane():
    a = steane()
    n = a["n"]
    doc = copy.deepcopy(a)
    doc["name"] = "two Steane codes on disjoint qubits (validation gate)"
    doc["n"], doc["k"] = 2 * n, 2
    for side in ("X", "Z"):
        doc["checks"][side] = a["checks"][side] + [[q + n for q in s] for s in a["checks"][side]]
    return doc


def shor_with_hadamards(qubits=(0, 4)):
    """File the Shor code as a stabilizer code with a Hadamard on `qubits`: CSS up to a local Clifford."""
    a = shor()
    gens = []
    for side, other in (("X", "Z"), ("Z", "X")):
        for s in a["checks"][side]:
            g = {"X": [], "Z": []}
            for q in s:
                g[other if q in qubits else side].append(q)
            gens.append({k: sorted(v) for k, v in g.items()})
    wit = {"X": [], "Z": []}
    for q in a["distance"]["X"]["witness"]:
        wit["Z" if q in qubits else "X"].append(q)
    return {"schema_version": "0.4", "name": "Shor code under a Hadamard on two qubits (validation gate)",
            "code_type": "stabilizer", "n": a["n"], "k": a["k"], "checks": {"S": gens},
            "distance": {"d": 3, "P": {"value": 3, "confidence": "upper_bound",
                                       "witness": {k: sorted(v) for k, v in wit.items()}}},
            "provenance": a["provenance"], "family": "other"}


def _failed(rep):
    return [(c["check"], c.get("detail", "")) for c in rep["checks"]
            if not c["ok"] and c["check"] != "distance_not_refuted"]


def run_solved(tlim=60.0):
    out = []
    for label, build, k, d in SOLVED:
        doc = build()
        rep = V.verify(doc, refute=False)
        cert = certify.certify(doc, tlim=tlim)
        sides = {s: cert["sides"].get(s, {}).get("exact") for s in ("X", "Z")}
        ok = (rep["ok"] and rep["computed"]["k"] == k and doc["k"] == k and doc["distance"]["X"]["value"] == d
              and doc["distance"]["Z"]["value"] == d and cert["d_exact"] and all(sides.values()))
        out.append({"case": label, "ok": bool(ok), "verifier_ok": rep["ok"], "k": rep["computed"].get("k"),
                    "d_witnessed": min(doc["distance"]["X"]["value"], doc["distance"]["Z"]["value"]),
                    "certified_exact": bool(cert["d_exact"]), "failed": _failed(rep)})
    rep = V.verify(direct_sum_of_two_steane(), refute=False)
    failed = _failed(rep)
    names = {c for c, _ in failed}
    out.append({"case": "direct sum of two Steane codes is refused as disconnected", "failed": failed,
                "ok": (not rep["ok"]) and "tanner_connected" in names
                and all(kind_of(c, dd) == "construction" for c, dd in failed)})
    image = shor_with_hadamards()
    rep = V.verify(image, refute=False)
    failed = _failed(rep)
    base = shor()
    fp = V.css_fingerprint(V._matrix(base["checks"]["X"], 9), V._matrix(base["checks"]["Z"], 9))
    eq = rep.get("css_equivalent") or {}
    out.append({"case": "Shor code under a local Hadamard is sent back as its CSS image", "failed": failed,
                "image_named": fp in (eq.get("fingerprints") or []),
                "ok": (not rep["ok"]) and "stabilizer_code_is_not_locally_css" in {c for c, _ in failed}
                and fp in (eq.get("fingerprints") or [])})
    return out


# -- broken artifacts ------------------------------------------------------------

def _fixture_72():
    with open(os.path.join(_HERE, "fixtures", "72-6-6.json"), encoding="utf-8") as f:
        return json.load(f)


def broken_construction():
    doc = steane()
    doc["checks"]["Z"][0] = [3, 4, 5]            # drops a qubit: the checks no longer commute
    return doc


def broken_weight():
    n = 40
    HX = np.ones((1, n), dtype=np.int8)           # one check on all 40 qubits, over the cap of 32
    HZ = np.zeros((n // 2, n), dtype=np.int8)
    for i in range(n // 2):
        HZ[i, [2 * i, 2 * i + 1]] = 1
    return css_doc("a check over the weight cap (validation gate)", HX, HZ, 2,
                   construction="one weight-40 X check against 20 weight-2 Z checks", confidence="upper_bound")


def broken_packaging():
    doc = steane()
    del doc["provenance"]                         # a required block is missing
    return doc


def broken_typing():
    a = steane()
    gens = [{"X": s, "Z": []} for s in a["checks"]["X"]] + [{"X": [], "Z": s} for s in a["checks"]["Z"]]
    return {"schema_version": "0.4", "name": a["name"], "code_type": "stabilizer", "n": 7, "k": 1,
            "checks": {"S": gens},               # every generator pure: a CSS code typed stabilizer
            "distance": {"d": 3, "P": {"value": 3, "confidence": "upper_bound",
                                       "witness": {"X": a["distance"]["X"]["witness"], "Z": []}}},
            "provenance": a["provenance"], "family": "other"}


def broken_witness():
    doc = steane()
    doc["distance"]["X"]["witness"] = [0, 1]      # not in ker(H_Z): no logical at all
    doc["distance"]["X"]["value"] = 2
    doc["distance"]["d"] = 2
    return doc


def broken_layout():
    doc = _fixture_72()
    coords = doc["locality"]["coordinates"]
    coords[1] = list(coords[0])                   # two qubits on one site, one layer declared
    doc["locality"]["layers"] = 1
    return doc


BROKEN = (("construction", broken_construction, "css_commutation"),
          ("weight", broken_weight, None),
          ("packaging", broken_packaging, "schema_valid"),
          ("typing", broken_typing, "stabilizer_code_is_not_css"),
          ("witness", broken_witness, "distance_X_witness"),
          ("layout", broken_layout, "site_occupancy_within_layers"))


def run_broken():
    out = []
    for kind, build, check in BROKEN:
        rep = V.verify(build(), refute=False)
        failed = _failed(rep)
        kinds = {kind_of(c, d) for c, d in failed}
        names = {c for c, _ in failed}
        ok = (not rep["ok"]) and kind in kinds and (check is None or check in names) \
            and ((kind in CODE_KINDS) == any(k in CODE_KINDS for k in kinds))
        out.append({"kind": kind, "expected_check": check, "ok": bool(ok), "failed": failed,
                    "kinds": sorted(kinds)})
    return out


# -- published reproductions -----------------------------------------------------

def _doc_sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _golden_path(slug):
    return os.path.join(GOLDEN_DIR, slug + ".json")


def run_reproductions(update=False):
    out = []
    for slug in REPRODUCTIONS:
        path = os.path.join(CODES, slug + ".json")
        if not os.path.exists(path):
            out.append({"slug": slug, "status": "entry_missing", "ok": False})
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        rep = V.verify(doc, refute=False)
        text = json.dumps(rep, sort_keys=True, indent=1)
        sha = _doc_sha(path)
        gp = _golden_path(slug)
        if update:
            os.makedirs(GOLDEN_DIR, exist_ok=True)
            with open(gp, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"slug": slug, "doc_sha256": sha, "report": rep}, f, sort_keys=True, indent=1)
                f.write("\n")
            out.append({"slug": slug, "status": "recorded", "ok": True})
            continue
        if not os.path.exists(gp):
            out.append({"slug": slug, "status": "no_golden", "ok": False})
            continue
        with open(gp, encoding="utf-8") as f:
            golden = json.load(f)
        if golden.get("doc_sha256") != sha:
            out.append({"slug": slug, "status": "entry_changed", "ok": False,
                        "detail": "the entry's bytes differ from when the golden verdict was recorded; "
                                  "re-record with --update-golden after checking the entry's change"})
        elif json.dumps(golden["report"], sort_keys=True, indent=1) == text:
            out.append({"slug": slug, "status": "match", "ok": True})
        else:
            diff = [c["check"] for c in rep["checks"]
                    if c not in golden["report"].get("checks", [])]
            out.append({"slug": slug, "status": "drift", "ok": False,
                        "detail": "the verifier's verdict differs from the committed one"
                                  + (f"; changed checks: {', '.join(diff[:6])}" if diff else "")})
    return out


def run(update_golden=False, tlim=60.0):
    return {"solved": run_solved(tlim), "broken": run_broken(),
            "reproductions": run_reproductions(update=update_golden)}


def ok(results):
    return all(r["ok"] for part in results.values() for r in part)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--update-golden", action="store_true",
                    help="record the current verdicts of the reproduction set as the golden files")
    ap.add_argument("--tlim", type=float, default=60.0, help="MILP time limit for the solved cases")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    results = run(update_golden=a.update_golden, tlim=a.tlim)
    if a.json:
        print(json.dumps(results, indent=1, sort_keys=True))
    elif not a.quiet or not ok(results):
        for r in results["solved"]:
            print(f"solved      {'ok  ' if r['ok'] else 'FAIL'} {r['case']}"
                  + (f" (k={r.get('k')}, d<={r.get('d_witnessed')}, exact={r.get('certified_exact')})"
                     if "k" in r else "")
                  + ("" if r["ok"] else f" failed checks: {r['failed']}"))
        for r in results["broken"]:
            print(f"broken      {'ok  ' if r['ok'] else 'FAIL'} {r['kind']}: "
                  + ", ".join(c for c, _ in r["failed"]) + f" -> {r['kinds']}")
        for r in results["reproductions"]:
            print(f"reproduction {'ok  ' if r['ok'] else 'FAIL'} {r['slug']}: {r['status']}"
                  + (f" ({r['detail']})" if r.get("detail") else ""))
    good = ok(results)
    if not a.quiet or not good:
        print("validation gate: " + ("passed" if good else "FAILED"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())

"""
Adversarial tests for the verifier: the trust anchor of the challenge must
ACCEPT a valid submission and REJECT every way a bad one can be wrong.

Run: uv run python verify/test_verifier.py   (or: pytest verify/test_verifier.py)

Each tamper takes the known-good verify/fixtures/72-6-6.json, breaks exactly one
thing, and asserts the verifier flags it (report["ok"] is False, and ideally
the specific check fails). A green run means a hostile or mistaken submission
cannot slip a false claim onto the board.
"""

import copy
import glob
import importlib.util
import json
import os
import sys
import tempfile
import qldpc_verify

verify = qldpc_verify.verify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = json.load(open(os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")))

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def rep(doc):
    return verify(doc)


def failed_checks(r):
    return {c["check"] for c in r["checks"] if not c["ok"]}


def load_site_build():
    spec = importlib.util.spec_from_file_location(
        "site_build", os.path.join(ROOT, "site", "build.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    print("ACCEPT the valid submission:")
    r = rep(GOOD)
    check("valid code passes", r["ok"])
    check("earns a distance tier", "d" in r["earned_distance"])
    check("connected Tanner graph passes",
          "tanner_connected" not in failed_checks(r))
    check("X and Z checks use one combined graph",
          qldpc_verify._tanner_component_count(
              {"X": [[0], [1]], "Z": [[0, 1]]}, 2) == 1)

    disconnected = {
        "schema_version": "0.1",
        "name": "disconnected synthetic code",
        "code_type": "CSS",
        "n": 3,
        "k": 1,
        "checks": {"X": [[0]], "Z": [[1]]},
        "distance": {
            "d": 1,
            "X": {"value": 1, "confidence": "upper_bound", "witness": [2]},
            "Z": {"value": 1, "confidence": "upper_bound", "witness": [2]},
        },
        "provenance": {"authors": ["@test"], "construction": "synthetic"},
    }
    r = rep(disconnected)
    check("disconnected Tanner graph rejected",
          not r["ok"] and "tanner_connected" in failed_checks(r))
    tanner_check = next(c for c in r["checks"]
                        if c["check"] == "tanner_connected")
    check("isolated qubit is counted as a component",
          tanner_check["detail"] == "Tanner graph has 3 connected component(s)")
    check("connected stabilizer group passes",
          "stabilizer_group_connected" not in failed_checks(rep(GOOD)))

    # A direct sum whose Tanner graph is glued together by one linearly
    # dependent check per side (row_A XOR row_B): the raw component count is 1,
    # but the stabilizer group is still two independent blocks. Two copies of
    # the [[4,2,2]] code, n=8; the bridging rows add nothing to the row space.
    bridged = {
        "schema_version": "0.1",
        "name": "bridged direct sum of two [[4,2,2]] codes",
        "code_type": "CSS",
        "n": 8,
        "k": 4,
        "checks": {"X": [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 2, 3, 4, 5, 6, 7]],
                   "Z": [[0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 2, 3, 4, 5, 6, 7]]},
        "distance": {
            "d": 2,
            "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
            "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
        },
        "provenance": {"authors": ["@test"], "construction": "synthetic"},
    }
    r = rep(bridged)
    check("bridged direct sum has a connected Tanner graph",
          "tanner_connected" not in failed_checks(r))
    check("bridged direct sum rejected on the stabilizer group",
          not r["ok"] and "stabilizer_group_connected" in failed_checks(r))
    block_check = next(c for c in r["checks"]
                       if c["check"] == "stabilizer_group_connected")
    check("block sizes reported",
          block_check["detail"].endswith("(sizes 4, 4)"))

    # A qubit frozen by a weight-1 stabilizer hiding in the row space: the two
    # Z checks differ only in qubit 4, so Z_4 is a stabilizer and qubit 4 carries
    # no X check. It is an unused qubit with a connected Tanner graph.
    frozen = {
        "schema_version": "0.1",
        "name": "[[4,2,2]] plus one frozen qubit",
        "code_type": "CSS",
        "n": 5,
        "k": 2,
        "checks": {"X": [[0, 1, 2, 3]],
                   "Z": [[0, 1, 2, 3], [0, 1, 2, 3, 4]]},
        "distance": {
            "d": 2,
            "X": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
            "Z": {"value": 2, "confidence": "upper_bound", "witness": [0, 1]},
        },
        "provenance": {"authors": ["@test"], "construction": "synthetic"},
    }
    r = rep(frozen)
    check("frozen qubit has a connected Tanner graph",
          "tanner_connected" not in failed_checks(r))
    check("frozen qubit rejected on the stabilizer group",
          not r["ok"] and "stabilizer_group_connected" in failed_checks(r))
    check("frozen qubit reported as a size-1 block",
          qldpc_verify._stabilizer_block_count(
              qldpc_verify._matrix(frozen["checks"]["X"], 5),
              qldpc_verify._matrix(frozen["checks"]["Z"], 5), 5) == (2, [4, 1]))

    print("\nREJECT tampered submissions:")

    # 1. fake (too-short) distance witness: claim d=6 but witness has weight 4
    d = copy.deepcopy(GOOD)
    d["distance"]["X"]["witness"] = d["distance"]["X"]["witness"][:4]
    r = rep(d)
    check("short witness rejected (weight != value)",
          not r["ok"] and "distance_X_witness" in failed_checks(r))

    # 2. witness that is a stabilizer (trivial): use an X-check row as the
    #    'logical' witness -- it commutes but is in rowspace(H_X), so trivial
    d = copy.deepcopy(GOOD)
    stab = d["checks"]["X"][0]
    d["distance"]["X"]["witness"] = stab
    d["distance"]["X"]["value"] = len(stab)
    d["distance"]["d"] = min(len(stab), d["distance"]["Z"]["value"])
    r = rep(d)
    check("trivial (stabilizer) witness rejected",
          not r["ok"] and "distance_X_witness" in failed_checks(r))

    # 3. broken CSS commutation: flip one bit into an X-check so H_X H_Z^T != 0
    d = copy.deepcopy(GOOD)
    q = (set(range(d["n"])) - set(d["checks"]["X"][0])).pop()
    d["checks"]["X"][0] = sorted(d["checks"]["X"][0] + [q])
    r = rep(d)
    check("broken CSS commutation rejected",
          not r["ok"] and "css_commutation" in failed_checks(r))

    # 4. inflated k claim
    d = copy.deepcopy(GOOD)
    d["k"] = d["k"] + 2
    r = rep(d)
    check("wrong k rejected",
          not r["ok"] and "k_matches_claim" in failed_checks(r))

    # 5. out-of-range qubit index
    d = copy.deepcopy(GOOD)
    d["checks"]["Z"][0] = sorted(set(d["checks"]["Z"][0] + [d["n"] + 5]))
    r = rep(d)
    check("out-of-range qubit index rejected",
          not r["ok"] and "qubit_indices_in_range" in failed_checks(r))

    # 5b. a claimed model must name a version, not a bare vendor name
    d = copy.deepcopy(GOOD)
    d.setdefault("provenance", {})["model"] = "Claude"
    r = rep(d)
    check("underspecified model (no version) rejected",
          not r["ok"] and "model_version_specified" in failed_checks(r))

    # 6. inflated distance: claim d larger than the witness actually achieves
    d = copy.deepcopy(GOOD)
    d["distance"]["X"]["value"] += 3
    d["distance"]["d"] = min(d["distance"]["X"]["value"],
                             d["distance"]["Z"]["value"])
    r = rep(d)
    check("inflated distance value rejected",
          not r["ok"] and "distance_X_witness" in failed_checks(r))
    check("invalid side prevents global distance",
          "d" not in r["earned_distance"])

    # 6b. a bare distance number with no witnesses must not verify or render.
    d = copy.deepcopy(GOOD)
    d["distance"] = {"d": 99}
    r = rep(d)
    check("distance without witnesses rejected",
          not r["ok"] and "d" not in r["earned_distance"])
    build = load_site_build()
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, "codes"))
        with open(os.path.join(td, "codes", "bad.json"), "w") as f:
            json.dump(d, f)
        build.ROOT = td
        build.CERTS = os.path.join(td, "certs")
        check("site skips entries without an earned distance",
              build.load_entries() == [])

    # 6b. resource limits must reject hostile shapes before dense matrices are built.
    d = copy.deepcopy(GOOD)
    d["n"] = qldpc_verify.MAX_N + 1
    r = rep(d)
    check("oversized n rejected", not r["ok"])

    # 6c. two-tier blocklength cap: above BASE_MAX_N only sparse checks with a
    # reachable distance claim are admitted. Synthetic shapes checked at the
    # resource layer, so no board code is pinned.
    B, W, D = (qldpc_verify.BASE_MAX_N, qldpc_verify.EXT_MAX_CHECK_WEIGHT,
               qldpc_verify.EXT_MAX_D)
    adm = qldpc_verify.admissible
    check("admissible: base tier takes any weight and distance",
          adm(B, qldpc_verify.MAX_CHECK_WEIGHT, 10 * D))
    check("admissible: extended tier at the bounds", adm(B + 1, W, D)
          and adm(qldpc_verify.MAX_N, W, D))
    check("admissible: extended tier refuses weight above the bound",
          not adm(B + 1, W + 1, D))
    check("admissible: extended tier refuses distance above the bound",
          not adm(B + 1, W, D + 1))
    check("admissible: nothing above MAX_N",
          not adm(qldpc_verify.MAX_N + 1, W, D))

    def tiered(n, weight, claimed_d):
        row = list(range(weight))
        return {"n": n, "checks": {"X": [row], "Z": [row]},
                "distance": {"d": claimed_d}}

    def cap_errors(doc):
        return [e for e in qldpc_verify.resource_errors(doc)
                if "cap" in e or "above" in e]

    check("resource layer admits the extended tier", cap_errors(tiered(B + 1, W, D)) == [])
    errs = cap_errors(tiered(B + 1, W + 1, D + 1))
    check("resource layer rejects an over-cap extended-tier claim",
          len(errs) == 1 and "check weight" in errs[0] and "claimed" in errs[0])
    errs = cap_errors(tiered(qldpc_verify.MAX_N + 1, W, D))
    check("resource layer rejects n above MAX_N",
          len(errs) == 1 and "blocklength cap" in errs[0])

    if GOOD.get("locality"):
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[0.0, 0.0]] * (qldpc_verify.MAX_COORDINATES + 1)
        r = rep(d)
        check("oversized coordinate payload rejected", not r["ok"])

    # 7. locality claim too tight (interaction radius understated)
    if "locality" in GOOD:
        d = copy.deepcopy(GOOD)
        d["locality"]["interaction_radius"] = 1.0
        r = rep(d)
        check("understated interaction radius rejected",
              not r["ok"]
              and "interaction_radius_within_claim" in failed_checks(r))

    # 7a. computed locality class: a valid layout earns a 2d-local class, and
    #     the class is derived from the layout, never from a self-declared track.
    if GOOD.get("locality"):
        check("valid layout earns its computed locality class",
              rep(GOOD)["computed"]["locality_class"].startswith("local-2d"))

        # no layout -> unrestricted (membership is computed, not rejected)
        d = copy.deepcopy(GOOD)
        d.pop("locality", None)
        r = rep(d)
        check("no layout computes as unrestricted, still valid",
              r["ok"] and r["computed"]["locality_class"] == "unrestricted")

        # 7a'. a layout must declare its layer count (schema requirement)
        d = copy.deepcopy(GOOD)
        d["locality"].pop("layers", None)
        r = rep(d)
        check("layout without layers rejected",
              not r["ok"] and "schema_valid" in failed_checks(r))

        # 7b. crammed layout: collapse qubits onto a sub-unit-spaced line so the
        #     radius looks tiny -- a dishonest layout must FAIL verification,
        #     not silently demote to unrestricted and merge green
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[0.001 * i, 0.0] for i in range(d["n"])]
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("crammed layout fails verification",
              not r["ok"]
              and "site_spacing_at_least_one" in failed_checks(r)
              and r["computed"]["locality_class"] == "unrestricted")

        # 7b'. over-occupancy: more qubits stacked on one site than declared
        #      layers -- same dishonesty, same hard failure
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[float(i // 3), 0.0]
                                        for i in range(d["n"])]
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("over-occupied sites fail verification",
              not r["ok"]
              and "site_occupancy_within_layers" in failed_checks(r)
              and r["computed"]["locality_class"] == "unrestricted")

        # 7c. honest spacing but long range: a check spans far beyond any cap.
        #     That is a legitimate unrestricted submission, so it stays valid --
        #     but the demotion is surfaced as a named check, never silent.
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[float(i), 0.0] for i in range(d["n"])]
        d["locality"]["layers"] = 1
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("over-radius layout stays valid but is named unrestricted",
              r["ok"]
              and r["computed"]["locality_class"] == "unrestricted"
              and any(c["check"] == "locality_class_computed"
                      and "unrestricted" in c["detail"]
                      for c in r["checks"]))

    # 8. malformed: missing a required field, must not crash
    d = copy.deepcopy(GOOD)
    del d["checks"]
    try:
        r = rep(d)
        check("malformed (missing checks) rejected cleanly",
              not r["ok"] and "schema_valid" in failed_checks(r))
    except Exception as e:
        check(f"malformed rejected cleanly (raised {type(e).__name__})", False)

    # 8b. witness_provenance (schema 0.2, issue #611): refutation credit is
    #     attached to the witness, not to provenance.authors
    d = copy.deepcopy(GOOD)
    d["schema_version"] = "0.2"
    d["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@FarLab"], "date": "2026-08-19",
        "found_at_samples": 50_000_000, "survived_samples": 1_000_000_000,
        "tool": "ris_gpu", "seeds": [88000007]}
    r = rep(d)
    check("witness_provenance accepted (schema 0.2)", r["ok"])

    d = copy.deepcopy(GOOD)
    d["schema_version"] = "0.2"
    d["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@FarLab"], "date": "2026-08-19",
        "found_at_samples": 50_000_000}  # survived_samples is optional
    r = rep(d)
    check("witness_provenance without survived_samples accepted", r["ok"])

    d = copy.deepcopy(GOOD)
    d["schema_version"] = "0.2"
    d["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@FarLab"], "date": "2026-08-19",
        "survived_samples": 10 ** 9}  # no found_at_samples
    r = rep(d)
    check("witness_provenance without found_at_samples rejected",
          not r["ok"] and "schema_valid" in failed_checks(r))

    d = copy.deepcopy(GOOD)  # schema_version stays 0.1
    d["distance"]["X"]["witness_provenance"] = {
        "found_by": ["@FarLab"], "date": "2026-08-19",
        "found_at_samples": 1000}
    r = rep(d)
    check("witness_provenance on a 0.1 document rejected",
          not r["ok"] and "schema_valid" in failed_checks(r))

    d = copy.deepcopy(GOOD)
    d["schema_version"] = "0.2"
    d["distance"]["X"]["witness_provenance"] = {
        "found_by": ["FarLab"], "date": "2026-08-19",
        "found_at_samples": 1000}
    r = rep(d)
    check("witness_provenance handle without @ rejected",
          not r["ok"] and "schema_valid" in failed_checks(r))

    # 9. not even a dict, must not crash
    try:
        r = rep([1, 2, 3])
        check("non-object submission rejected cleanly", not r["ok"])
    except Exception as e:
        check(f"non-object rejected cleanly (raised {type(e).__name__})", False)

    # 10. duplicate detection: a code shares signature AND fingerprint with
    #     itself, and is invariant to row reordering (same stabilizer group).
    r1 = rep(GOOD)
    d = copy.deepcopy(GOOD)
    d["checks"]["X"] = list(reversed(d["checks"]["X"]))  # reorder checks
    r2 = rep(d)
    check("identical codes share WL signature", r1["signature"]["hash"]
          == r2["signature"]["hash"])
    check("row-reordered code has same exact fingerprint",
          r1["fingerprint"] == r2["fingerprint"])

    # 11. a genuinely different code has a different WL signature. Pick any
    #     board code that is not the [[72,6,6]] used above.
    others = [p for p in glob.glob(os.path.join(ROOT, "codes", "*.json"))
              if os.path.basename(p) != "72-6-6.json"]
    other = json.load(open(others[0]))
    check("distinct codes have distinct WL signatures",
          rep(other)["signature"]["hash"] != r1["signature"]["hash"])

    # every shipped example/code still verifies
    print("\nshipped submissions still verify:")
    paths = (sorted(glob.glob(os.path.join(ROOT, "codes", "*.json")))
             + sorted(glob.glob(os.path.join(ROOT, "verify", "fixtures", "*.json"))))
    for p in paths:
        doc = json.load(open(p))
        r = verify(doc)
        check(f"{os.path.basename(p)} verifies", r["ok"])
    if not _fail:
        print("  ok    all shipped submissions verify")

    check("normal file size accepted",
          qldpc_verify.file_size_error(__file__) == "")
    with tempfile.NamedTemporaryFile() as f:
        f.seek(qldpc_verify.MAX_SUBMISSION_BYTES)
        f.write(b"x")
        f.flush()
        check("oversized file size rejected",
              qldpc_verify.file_size_error(f.name) != "")

    print(f"\n{'ALL PASS' if not _fail else 'FAILURES: ' + ', '.join(_fail)}")
    return 1 if _fail else 0


# pytest entry points
def test_adversarial():
    assert main() == 0


def test_main():
    """pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())


def test_board_reports_memoized_per_board_state(tmp_path, monkeypatch):
    """Share one structural pass per board state across callers in the process.

    Any change to the files re-verifies; broken files are recorded, not
    raised, so one bad entry cannot take the whole board down.
    """
    import shutil

    import qldpc_verify as Q

    src = os.path.join(ROOT, "verify", "fixtures", "72-6-6.json")
    d = tmp_path / "codes"
    d.mkdir()
    shutil.copy(src, d / "72-6-6.json")
    calls = []
    real = Q.verify
    monkeypatch.setattr(Q, "verify",
                        lambda doc, *a, **k: (calls.append(1), real(doc, *a, **k))[1])

    r1 = Q.board_reports(str(d))
    r2 = Q.board_reports(str(d))
    assert r1 is r2 and len(calls) == 1
    assert r1[0]["slug"] == "72-6-6" and r1[0]["report"]["ok"]

    shutil.copy(src, d / "99-9-9.json")               # board changed -> fresh pass
    r3 = Q.board_reports(str(d))
    assert r3 is not r1 and len(calls) == 3 and [e["slug"] for e in r3] == ["72-6-6", "99-9-9"]

    (d / "broken.json").write_text("{")
    r4 = Q.board_reports(str(d))
    bad = next(e for e in r4 if e["slug"] == "broken")
    assert bad["doc"] is None and bad["report"] is None and "JSONDecodeError" in bad["load_error"]
    assert sum(e["report"] is not None for e in r4) == 2

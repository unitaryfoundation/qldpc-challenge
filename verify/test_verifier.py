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

    # 7d. heuristic routing cost (issue #1847): the MST lower bound on the
    #     nearest-neighbor SWAPs each check needs on its layout, computed for
    #     every accepted layout and labeled heuristic; never for a code
    #     without one. One lattice step is the layout's minimum site spacing.
    print("\nheuristic routing cost:")
    if GOOD.get("locality"):
        rc = rep(GOOD)["computed"].get("routing_cost")
        check("accepted layout reports a routing cost labeled heuristic",
              rc is not None and rc["heuristic"] == "mst-lower-bound"
              and isinstance(rc["total_swaps"], int)
              and isinstance(rc["max_swaps_per_check"], int)
              and rc["max_swaps_per_check"] <= rc["total_swaps"]
              and rc["lattice_step"] == 1.0)
        d = copy.deepcopy(GOOD)
        d.pop("locality", None)
        check("no layout, no routing cost",
              "routing_cost" not in rep(d)["computed"])
        # a cap-exceeding layout (every qubit on one line) is still priced
        d = copy.deepcopy(GOOD)
        d["locality"]["coordinates"] = [[float(i), 0.0] for i in range(d["n"])]
        d["locality"]["layers"] = 1
        d["locality"].pop("interaction_radius", None)
        r = rep(d)
        check("cap-exceeding layout still gets a routing cost",
              r["computed"]["locality_class"] == "unrestricted"
              and r["computed"]["routing_cost"]["total_swaps"] > 0)
    # a small planar code: 3x3 grid of qubits, one plaquette per unit square,
    # so every support is a nearest-neighbor cluster and costs 0 SWAPs
    grid = [[float(x), float(y)] for y in range(3) for x in range(3)]
    plaquettes = [[3 * y + x, 3 * y + x + 1, 3 * (y + 1) + x, 3 * (y + 1) + x + 1]
                  for y in range(2) for x in range(2)]
    check("planar plaquettes cost 0 SWAPs",
          qldpc_verify.routing_cost(plaquettes, grid, 1.0) == (0, 0))
    # the rotated surface code shipped on the board is the same statement end
    # to end: its weight-4 checks sit on unit squares, its weight-2 boundary
    # checks on unit edges
    planar = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
    rc = rep(planar)["computed"]["routing_cost"]
    check("rotated surface code costs 0 SWAPs end to end",
          (rc["total_swaps"], rc["max_swaps_per_check"]) == (0, 0))
    # a hand-built long-range check on a unit line: qubits at 0, 1, 5, 12.
    # MST edges 1, 4, 7 steps = 12, minus (4 - 1) = 9 SWAPs
    line = [[float(x), 0.0] for x in range(13)]
    check("long-range check costs MST steps minus (|support| - 1)",
          qldpc_verify.check_routing_cost([0, 1, 5, 12], line, 1.0) == 9)
    # the MST, not the diameter: a path 0, 1, 5, 12 plus a chord is priced by
    # the tree, and a two-check code reports the total and the max
    check("routing cost reports total and max over checks",
          qldpc_verify.routing_cost([[0, 1, 5, 12], [2, 3], [7, 9]], line, 1.0)
          == (10, 9))
    # lattice steps follow the layout's minimum spacing: the same check on a
    # layout with spacing 2 costs the same, since 2 units is one step there
    check("nearest neighbor is one minimum-spacing step",
          qldpc_verify.check_routing_cost(
              [0, 1, 5, 12], [[2.0 * x, 0.0] for x in range(13)], 2.0) == 9)
    # a diagonal is longer than one step (sqrt 2 rounds up to 2), and stacked
    # flip-chip qubits count as adjacent rather than free
    check("diagonal neighbors cost one SWAP",
          qldpc_verify.check_routing_cost([0, 1], [[0.0, 0.0], [1.0, 1.0]], 1.0)
          == 1)
    check("stacked qubits are adjacent, never negative",
          qldpc_verify.check_routing_cost([0, 1, 2],
                                          [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
                                          1.0) == 0)
    check("empty and singleton supports cost 0",
          qldpc_verify.check_routing_cost([], line, 1.0) == 0
          and qldpc_verify.check_routing_cost([4], line, 1.0) == 0)

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

    # Same-size edit with the mtime restored (cp -p / rsync -t / touch -r
    # shape): metadata is unchanged, the content is not, and the memo must
    # not serve the old report.
    p = d / "99-9-9.json"
    st = p.stat()
    text = p.read_text()
    assert '"k": 6' in text
    p.write_text(text.replace('"k": 6', '"k": 5', 1))
    os.utime(p, (st.st_atime, st.st_mtime))
    assert p.stat().st_size == st.st_size and p.stat().st_mtime == st.st_mtime
    r3b = Q.board_reports(str(d))
    assert r3b is not r3 and len(calls) == 5
    bad_k = next(e for e in r3b if e["slug"] == "99-9-9")
    assert bad_k["doc"]["k"] == 5 and not bad_k["report"]["ok"]
    assert Q.board_reports(str(d)) is r3b and len(calls) == 5   # and it is a hit again

    (d / "broken.json").write_text("{")
    r4 = Q.board_reports(str(d))
    bad = next(e for e in r4 if e["slug"] == "broken")
    assert bad["doc"] is None and bad["report"] is None and "JSONDecodeError" in bad["load_error"]
    assert sum(e["report"] is not None for e in r4) == 2

    # Two spellings of the same directory are one snapshot, not two passes.
    rel = os.path.relpath(str(d))
    n = len(calls)
    assert Q.board_reports(rel) is r4 and len(calls) == n


def _modular_fixture(split=lambda c: 0 if c[1] < 3 else 1):
    """The fixture with every qubit assigned to a module by its coordinate
    (schema 0.3, since locality.modules is a 0.3 field)."""
    d = copy.deepcopy(GOOD)
    d["schema_version"] = "0.3"
    d["locality"]["modules"] = [split(c) for c in d["locality"]["coordinates"]]
    return d


def test_module_diagnostics():
    """locality.modules (issue #1846): every qubit carries a module id, and the
    verifier reports cross-module checks, ports per module, and qubits per
    module while leaving the locality class and the rest of the verdict alone.
    """
    base = rep(GOOD)
    d = _modular_fixture()
    r = rep(d)
    assert r["ok"]
    assert r["computed"]["flags"]["modular"] is True
    assert r["computed"]["locality_class"] == base["computed"]["locality_class"]
    assert r["computed"]["locality"] == base["computed"]["locality"]
    m = r["computed"]["modules"]
    assert m["count"] == 2
    mods = d["locality"]["modules"]
    assert m["qubits_per_module"] == {"0": mods.count(0), "1": mods.count(1)}
    # recompute the crossing set by hand and compare
    X, Z = d["checks"]["X"], d["checks"]["Z"]
    cross = {s: [i for i, sup in enumerate(H)
                 if len({mods[q] for q in sup}) > 1]
             for s, H in (("X", X), ("Z", Z))}
    assert m["cross_module_check_indices"] == cross
    assert m["cross_module_checks"] == len(cross["X"]) + len(cross["Z"])
    assert 0 < m["cross_module_checks"] < len(X) + len(Z)
    # two modules that share a check each see exactly one neighbor
    assert m["ports_per_module"] == {"0": 1, "1": 1} and m["max_ports"] == 1
    assert any(c["check"] == "modules_computed" and c["ok"] for c in r["checks"])

    # a single module: nothing crosses, no ports
    r1 = rep(_modular_fixture(lambda c: 7))
    m1 = r1["computed"]["modules"]
    assert r1["ok"] and m1["count"] == 1 and m1["cross_module_checks"] == 0
    assert m1["ports_per_module"] == {"7": 0} and m1["max_ports"] == 0

    # one module per qubit: every check crosses, ports = distinct partners
    d2 = _modular_fixture()
    d2["locality"]["modules"] = list(range(GOOD["n"]))
    r2 = rep(d2)
    m2 = r2["computed"]["modules"]
    assert r2["ok"] and m2["count"] == GOOD["n"]
    assert m2["cross_module_checks"] == len(X) + len(Z)

    # no modules field: flag off, no block, verdict as before
    assert base["computed"]["flags"]["modular"] is False
    assert "modules" not in base["computed"]


def test_module_assignment_must_cover_every_qubit():
    """A partial assignment is a rejected layout claim, not a silent demotion;
    a stale schema_version and an oversize list are rejected too."""
    d = _modular_fixture()
    d["locality"]["modules"] = d["locality"]["modules"][:-1]
    r = rep(d)
    assert not r["ok"] and "modules_cover_all_qubits" in failed_checks(r)
    assert r["computed"]["flags"]["modular"] is False
    assert "modules" not in r["computed"]

    d = _modular_fixture()
    d["schema_version"] = "0.1"
    r = rep(d)
    assert not r["ok"] and "schema_valid" in failed_checks(r)

    d = _modular_fixture()
    d["locality"]["modules"] = [0] * (qldpc_verify.MAX_COORDINATES + 1)
    assert not rep(d)["ok"]

    d = _modular_fixture()
    d["locality"]["modules"][0] = -1
    r = rep(d)
    assert not r["ok"] and "schema_valid" in failed_checks(r)


def _lift_to_3d(doc):
    """The bilayer fixture unstacked into a genuine 3D layout: the two qubits
    sharing a planar site go to z = 0 and z = 1, and layers drops to 1."""
    d = copy.deepcopy(doc)
    seen = {}
    coords = []
    for c in d["locality"]["coordinates"]:
        z = seen.get(tuple(c), 0)
        seen[tuple(c)] = z + 1
        coords.append([float(c[0]), float(c[1]), float(z)])
    d["locality"]["coordinates"] = coords
    d["locality"]["layers"] = 1
    d["locality"].pop("interaction_radius", None)
    return d


def test_3d_layout_checks():
    """3D coordinates (issue #1849): the honesty checks and the radius carry
    over, the report says D = 3, and no 2D-local class is earned."""
    import math
    base = rep(GOOD)
    assert base["computed"]["locality"]["dimension"] == 2
    assert "qubits_per_unit_area" in base["computed"]["locality"]

    d = _lift_to_3d(GOOD)
    r = rep(d)
    assert r["ok"], failed_checks(r)
    lay = r["computed"]["locality"]
    assert lay["dimension"] == 3 and len(lay["bbox"]) == 3
    assert lay["max_qubits_per_site"] == 1 and lay["min_site_spacing"] == 1.0
    assert "qubits_per_unit_volume" in lay and "qubits_per_unit_area" not in lay
    coords = d["locality"]["coordinates"]
    radius = max(math.dist(coords[a], coords[b])
                 for sup in d["checks"]["X"] + d["checks"]["Z"]
                 for a in sup for b in sup)
    assert lay["interaction_radius"] == round(radius, 4)
    assert radius >= base["computed"]["locality"]["interaction_radius"]
    assert r["computed"]["locality_class"] == "unrestricted"
    assert any(c["check"] == "locality_class_computed" and "3D" in c["detail"]
               for c in r["checks"])
    assert any(c["check"] == "coordinates_uniform_dimension" and c["ok"]
               for c in r["checks"])

    # a claimed radius is still checked in 3D
    d2 = copy.deepcopy(d)
    d2["locality"]["interaction_radius"] = radius - 0.5
    r2 = rep(d2)
    assert not r2["ok"] and "interaction_radius_within_claim" in failed_checks(r2)

    # cramming along z fails, as it does in the plane
    d3 = copy.deepcopy(d)
    d3["locality"]["coordinates"] = [[c[0], c[1], 0.25 * c[2]] for c in coords]
    r3 = rep(d3)
    assert not r3["ok"] and "site_spacing_at_least_one" in failed_checks(r3)

    # stacking beyond the declared layers fails in 3D too
    d4 = copy.deepcopy(d)
    d4["locality"]["coordinates"] = [[c[0], c[1], 0.0] for c in coords]
    r4 = rep(d4)
    assert not r4["ok"] and "site_occupancy_within_layers" in failed_checks(r4)
    # and passes when the layers are declared, but as a 3D layout it still
    # earns no planar class
    d4["locality"]["layers"] = 2
    r4 = rep(d4)
    assert r4["ok"] and r4["computed"]["locality_class"] == "unrestricted"
    assert (r4["computed"]["locality"]["interaction_radius"]
            == base["computed"]["locality"]["interaction_radius"])


def test_mixed_or_higher_dimensions_rejected():
    d = _lift_to_3d(GOOD)
    d["locality"]["coordinates"][0] = d["locality"]["coordinates"][0][:2]
    r = rep(d)
    assert not r["ok"] and "coordinates_uniform_dimension" in failed_checks(r)
    assert "locality" not in r["computed"]

    d = _lift_to_3d(GOOD)
    d["locality"]["coordinates"] = [c + [0.0] for c in d["locality"]["coordinates"]]
    r = rep(d)
    assert not r["ok"] and "schema_valid" in failed_checks(r)

    # modules stay orthogonal to the dimension
    d = _lift_to_3d(GOOD)
    d["schema_version"] = "0.3"
    d["locality"]["modules"] = [int(c[2]) for c in d["locality"]["coordinates"]]
    r = rep(d)
    assert r["ok"] and r["computed"]["flags"]["modular"]
    assert r["computed"]["modules"]["count"] == 2

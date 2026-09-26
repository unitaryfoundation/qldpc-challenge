"""validate_candidate -- the trusted gate an autoresearch agent must pass to claim a code.

This is the *conscience* of the autoresearch loop. An agent may explore freely and
write its own code, but every distance/quality CLAIM has to survive this gate, which
it must not be able to weaken.

It is deliberately THIN: the actual verification and refutation are the existing
verifier (``qldpc_verify.verify(doc, refute=True)`` already does schema + n/k/CSS +
witnesses AND the random-seed distance refutation in one call). This module adds only
what the agent needs on top: board deduplication, a novelty label, and a single
structured verdict with honest labels the skill can act on.

TRUST MODEL
-----------
1. This file depends ONLY on the trusted verifier stack in ``verify/``. It imports
   NOTHING from ``research/`` -- the agent's playground -- so an agent cannot soften
   the gate by editing its own kit; it would have to edit the trusted stack, whose
   hashes CI pins (see ``check_validator_integrity.py``).
2. Editing THIS file cannot be prevented on a machine the agent controls, so it is
   not the root of trust. The authoritative run is CI, executing this file from the
   protected ``main`` branch. A local run is a fast preview. Every verdict is stamped
   with this file's source hash (``validator.source_sha256``) so a verdict produced
   by a tampered local copy is detectable downstream.

The gate, per candidate (a schema-shaped submission ``doc``):
  verify   -- the real verifier passes (schema + n/k/CSS/weight + witnesses)
  refute   -- the verifier's own random-seed refutation finds nothing lighter than
              the claimed distance (an over-claim is caught here)
  dedup    -- not an exact duplicate of a board entry (WL-equivalent is flagged)
  novelty  -- LABEL only: does it advance its own primary-track cell? (literature
              novelty is out of scope here). A win whose only strict axis is d,
              over a board entry equal in n, k and w, is also reported as
              ``d_only_gain`` together with ``d_only_peers``, the entries it beat.
              The label names those peers whenever the candidate beats one of
              them on d alone -- even if it gained on another axis over a
              different entry -- and tells you to re-measure at matched depth.

``passed`` is True iff the verifier accepts it (structure + witnesses), it is not
refuted, and it is not an exact board duplicate. Novelty is a label, not a pass
condition.
"""
import hashlib
import json
import os
import secrets
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                       # trusted verify/ only
import qldpc_verify

_REPO = os.path.dirname(_HERE)
_CODES = os.path.join(_REPO, "codes")

# nesting order (stricter -> looser); a code competes in its class and every looser one
_WEIGHT_ORDER = {"weight-4": 0, "weight-6": 1, "weight-8": 2, "weight-9plus": 3}
_LOCAL_ORDER = {"local-2d-single": 0, "local-2d-bilayer": 1, "unrestricted": 2}


def source_sha256():
    """SHA-256 of this validator's own source -- the provenance stamp CI checks."""
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _board_entries():
    """Trusted read of the current board via verify/, memoized per board state
    (qldpc_verify.board_reports) so validating many candidates in a session --
    or the site build and the tests in the same process -- rescans once."""
    out = []
    for e in qldpc_verify.board_reports(_CODES):
        doc, rep = e["doc"], e["report"]
        if doc is None or rep is None:
            continue                            # a broken board file never blocks a candidate
        try:
            comp = rep.get("computed", {})
            ceq = rep.get("css_equivalent") or {}
            out.append({
                "name": os.path.basename(e["path"]),
                "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"],
                "code_type": doc.get("code_type", "CSS"),
                "fingerprint": rep.get("fingerprint"),
                "sig": rep.get("signature", {}).get("hash"),
                # a stabilizer entry that is CSS up to local Hadamards also
                # carries the fingerprints and signatures of that CSS code
                "css_fingerprints": list(ceq.get("fingerprints") or []),
                "css_sigs": list(ceq.get("signatures") or []),
                "weight_class": comp.get("weight_class"),
                "w": comp.get("max_check_weight"),
                "locality_class": comp.get("locality_class"),
            })
        except Exception:
            continue
    return out


def _identity_sets(rep):
    """Return the (fingerprints, signatures) under which a verified code is recognized.

    Its own, plus those of the CSS code it maps to under local Hadamards when
    the verifier found one (report["css_equivalent"]).
    """
    ceq = rep.get("css_equivalent") or {}
    fps = {rep.get("fingerprint")} | set(ceq.get("fingerprints") or [])
    sigs = {rep.get("signature", {}).get("hash")} | set(ceq.get("signatures") or [])
    return fps - {None}, sigs - {None}


def validate_candidate(doc, *, seed=None, refute=True):
    """Run the trusted gate on a candidate submission ``doc``.

    ``refute`` defaults to True and preserves the full candidate-gate behavior.
    Trusted callers that already ran the independent distance gate may set it to
    False to obtain the structural, deduplication, and frontier verdict without
    repeating the expensive random search.

    Returns a structured verdict (JSON-serializable). ``passed`` is the honest bottom
    line; ``gates`` is the evidence for each check; ``labels`` are the human-facing
    tags an agent should surface with the candidate.
    """
    if seed is None:
        seed = secrets.randbelow(2**31)         # refutation is non-deterministic by design
    claimed_d = int(doc["distance"]["d"]) if "distance" in doc else None

    verdict = {
        "passed": False,
        "candidate": {"n": doc.get("n"), "k": doc.get("k"), "d": claimed_d,
                      "family": doc.get("family")},
        "gates": {},
        "labels": [],
        "validator": {"source_sha256": source_sha256(), "seed": seed},
    }
    g = verdict["gates"]

    # 1+2. VERIFY + REFUTE -- the normal path does schema/n/k/CSS/weight/witnesses
    #      and the random-seed distance refutation in one call. Receipt generation
    #      can reuse the structural portion after gate_changed.py has already run.
    rep = qldpc_verify.verify(doc, refute=refute, seed=seed)
    checks = rep["checks"]
    nd = next((c for c in checks if c["check"] == "distance_not_refuted"), None)
    refuted = nd is not None and not nd["ok"]
    structural_fail = [c["check"] for c in checks
                       if not c["ok"] and c["check"] != "distance_not_refuted"]
    verify_ok = not structural_fail
    comp = rep.get("computed", {})
    wc, lc = comp.get("weight_class"), comp.get("locality_class")
    verdict["candidate"]["weight_class"] = wc
    verdict["candidate"]["locality_class"] = lc
    verdict["candidate"]["fingerprint"] = rep.get("fingerprint")
    verdict["candidate"]["signature"] = rep.get("signature", {}).get("hash")

    g["verify"] = {"ok": verify_ok, "failed_checks": structural_fail,
                   "weight_class": wc, "locality_class": lc}
    if not verify_ok:
        verdict["labels"].append("invalid: verifier rejected")
        return verdict                          # nothing else is meaningful if it doesn't verify

    g["refute"] = {"refuted": refuted, "seed": seed,
                   "detail": nd["detail"] if nd else "no distance witnesses to refute"}
    if refuted:
        verdict["labels"].append(f"refuted (over-claimed distance): {nd['detail']}")

    # 3. DEDUP -- compare against the board by exact fingerprint and WL signature,
    #    both already computed by the verifier above. A stabilizer candidate
    #    that is a CSS code up to a Hadamard on some qubits is
    #    also compared through that CSS code's fingerprint and signature, in
    #    both directions, so a relabeled copy of a board entry is marked a
    #    duplicate of it rather than admitted as a new code. The CSS and
    #    stabilizer boards are separate, so this is the ONE place the two
    #    types meet, and only to recognize the same code.
    cand_fp = rep.get("fingerprint")
    cand_fps, cand_sigs = _identity_sets(rep)
    board = _board_entries()

    def fps_of(b):
        return {b["fingerprint"]} | set(b.get("css_fingerprints") or [])

    def sigs_of(b):
        return {b["sig"]} | set(b.get("css_sigs") or [])

    exact_dup = next((b["name"] for b in board if cand_fps & fps_of(b)), None)
    wl_equiv = next((b["name"] for b in board
                     if cand_sigs & sigs_of(b) and not (cand_fps & fps_of(b))), None)
    g["dedup"] = {"exact_duplicate_of": exact_dup, "wl_equivalent_of": wl_equiv}
    via_hadamard = exact_dup is not None and not any(
        b["fingerprint"] == cand_fp for b in board if b["name"] == exact_dup)
    if exact_dup and via_hadamard:
        g["dedup"]["local_clifford"] = "hadamard"
        verdict["labels"].append(
            f"duplicate: identical to board entry {exact_dup} up to a Hadamard "
            f"on {len(rep.get('css_equivalent', {}).get('hadamard_qubits', []))} "
            f"qubit(s)")
    elif exact_dup:
        verdict["labels"].append(f"duplicate: identical to board entry {exact_dup}")
    elif wl_equiv:
        verdict["labels"].append(f"possibly equivalent (same WL signature) to {wl_equiv}")

    # 4. NOVELTY (label only) -- non-dominated within the candidate's own track cell?
    #
    # The comparison is over all four axes (n lower, k higher, d higher, w
    # lower), matching TRACKS.md and site/build.py:pareto. Weight enters twice
    # and the two roles are distinct: the weight CLASS selects which cell a
    # code competes in, and the raw max check weight is a ranking axis inside
    # it. Comparing on class alone treated a w = 32 code as dominating a w = 7
    # one whenever n, k and d allowed, which the site's own frontier does not,
    # so a code could be labelled "does not advance its board cell" while
    # starring on the rendered board.
    #
    # The code type is a third cell dimension: a stabilizer
    # code is compared only with stabilizer codes and a CSS code only with
    # CSS codes, so neither board's entries can dominate the other's.
    n, k, d = doc["n"], doc["k"], claimed_d
    w = comp.get("max_check_weight")
    code_type = doc.get("code_type", "CSS")
    dominators = []
    dominated = []                            # (board entry, axes where the candidate is strictly better)
    for b in board:
        # a board code shares the candidate's cell iff it is on the same
        # board and stricter-or-equal on both axes
        if (b.get("code_type", "CSS") == code_type
                and _WEIGHT_ORDER.get(b["weight_class"], 9) <= _WEIGHT_ORDER.get(wc, 9)
                and _LOCAL_ORDER.get(b["locality_class"], 9) <= _LOCAL_ORDER.get(lc, 9)):
            bw = b.get("w")
            if bw is None:                     # pre-fix cache entry; skip the w axis
                bw = w
            if (b["n"] <= n and b["k"] >= k and b["d"] >= d and bw <= w
                    and (b["n"] < n or b["k"] > k or b["d"] > d or bw < w)):
                dominators.append(f"[[{b['n']},{b['k']},{b['d']}]] w={bw} {b['name']}")
                continue
            gains = [ax for ax, better in (("n", b["n"] > n), ("k", b["k"] < k),
                                           ("d", b["d"] < d), ("w", bw > w)) if better]
            if gains and b["n"] >= n and b["k"] <= k and b["d"] <= d and bw >= w:
                dominated.append((b, gains, f"[[{b['n']},{b['k']},{b['d']}]] w={bw} {b['name']}"))
    # Novelty against a board that already contains this exact code is not a
    # well-posed question, so say which condition fired rather than reporting a
    # verdict that was never reached. Validating a file already sitting in
    # codes/ compares it with itself, and the old label ("does not advance its
    # board cell", with an empty dominator list) reads as a rejection on
    # merit -- which cost a real submission that was in fact board-advancing.
    board_advancing = None if exact_dup else not dominators
    # Which axes does the candidate beat the board on? A construction fixes n, k
    # and w, so the only axis left to gain on is d -- and d is a witness-backed
    # upper bound, so it is the axis most likely to be too high. Two questions,
    # deliberately kept apart: does the board yield on nothing but d
    # (d_only_gain, true only when every strict axis is d), and is any single
    # entry beaten on nothing but d (d_only_peers). The second one drives the
    # label, because the win over THAT entry is suspect even when the candidate
    # legitimately gained on another axis over some third entry -- the label is
    # where the instruction to re-measure lives, so it must not go quiet just
    # because the candidate is also good somewhere else.
    advances_by = sorted({ax for _, gains, _ in dominated for ax in gains})
    d_only_peers = [desc for _, gains, desc in dominated if gains == ["d"]]
    d_only_gain = bool(board_advancing) and advances_by == ["d"]
    g["novelty"] = {"cell": [wc, lc], "board": code_type,
                    "board_advancing": board_advancing,
                    "dominated_by": dominators, "advances_by": advances_by,
                    "d_only_gain": d_only_gain,
                    "d_only_peers": d_only_peers,
                    "literature_novelty": "unverified"}
    if exact_dup:
        verdict["labels"].append(
            "novelty not assessed: this code is already on the board "
            f"as {exact_dup}")
    elif board_advancing and d_only_peers:
        peers = ", ".join(d_only_peers)
        if d_only_gain:
            verdict["labels"].append(
                f"advances the {wc} x {lc} board ONLY on d over {peers}: "
                "distance is the suspect axis; re-measure the peer and this "
                "candidate at matched depth "
                "(research/audits/leader_audit.py pair) before packaging")
        else:
            verdict["labels"].append(
                f"advances the {wc} x {lc} board on {', '.join(advances_by)}; "
                f"its gain over {peers} is d-only: distance is the suspect "
                "axis; re-measure the peer and this candidate at matched depth "
                "(research/audits/leader_audit.py pair) before packaging")
    else:
        verdict["labels"].append(
            f"advances the {wc} x {lc} {code_type} board" if board_advancing
            else f"does not advance its {code_type} board cell")
    verdict["labels"].append("literature novelty UNVERIFIED")

    verdict["passed"] = bool(verify_ok and not refuted and not exact_dup)
    return verdict


def main(argv):
    if not argv:
        print("usage: python verify/validate_candidate.py <submission.json>")
        return 2
    doc = json.load(open(argv[0]))
    verdict = validate_candidate(doc)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

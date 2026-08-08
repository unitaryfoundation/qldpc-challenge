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
              novelty is out of scope here)

``passed`` is True iff the verifier accepts it (structure + witnesses), it is not
refuted, and it is not an exact board duplicate. Novelty is a label, not a pass
condition.
"""
import functools
import glob
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


def _board_stamp():
    """A cheap key that changes iff the board files change (name/mtime/size), so the
    scan below can be cached within a session but never goes stale."""
    return tuple((os.path.basename(p), os.path.getmtime(p), os.path.getsize(p))
                 for p in sorted(glob.glob(os.path.join(_CODES, "*.json"))))


@functools.lru_cache(maxsize=4)
def _board_entries_cached(_stamp):
    out = []
    for p in sorted(glob.glob(os.path.join(_CODES, "*.json"))):
        try:
            doc = json.load(open(p))
            rep = qldpc_verify.verify(doc, refute=False)   # structural only; fast
            comp = rep.get("computed", {})
            out.append({
                "name": os.path.basename(p),
                "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"],
                "fingerprint": rep.get("fingerprint"),
                "sig": rep.get("signature", {}).get("hash"),
                "weight_class": comp.get("weight_class"),
                "w": comp.get("max_check_weight"),
                "locality_class": comp.get("locality_class"),
            })
        except Exception:
            continue                            # a broken board file never blocks a candidate
    return out


def _board_entries():
    """Trusted read of the current board via verify/, cached per board state so
    validating many candidates in a session does not rescan every time."""
    return _board_entries_cached(_board_stamp())


def validate_candidate(doc, *, seed=None):
    """Run the full trusted gate on a candidate submission ``doc``.

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

    # 1+2. VERIFY + REFUTE -- one trusted call does schema/n/k/CSS/weight/witnesses
    #      AND the random-seed distance refutation (the "distance_not_refuted" check).
    rep = qldpc_verify.verify(doc, refute=True, seed=seed)
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
    #    both already computed by the verifier above.
    cand_fp = rep.get("fingerprint")
    cand_sig = rep.get("signature", {}).get("hash")
    board = _board_entries()
    exact_dup = next((b["name"] for b in board if b["fingerprint"] == cand_fp), None)
    wl_equiv = next((b["name"] for b in board
                     if b["sig"] == cand_sig and b["fingerprint"] != cand_fp), None)
    g["dedup"] = {"exact_duplicate_of": exact_dup, "wl_equivalent_of": wl_equiv}
    if exact_dup:
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
    n, k, d = doc["n"], doc["k"], claimed_d
    w = comp.get("max_check_weight")
    dominators = []
    for b in board:
        # a board code shares the candidate's cell iff it is stricter-or-equal on both axes
        if (_WEIGHT_ORDER.get(b["weight_class"], 9) <= _WEIGHT_ORDER.get(wc, 9)
                and _LOCAL_ORDER.get(b["locality_class"], 9) <= _LOCAL_ORDER.get(lc, 9)):
            bw = b.get("w")
            if bw is None:                     # pre-fix cache entry; skip the w axis
                bw = w
            if (b["n"] <= n and b["k"] >= k and b["d"] >= d and bw <= w
                    and (b["n"] < n or b["k"] > k or b["d"] > d or bw < w)):
                dominators.append(f"[[{b['n']},{b['k']},{b['d']}]] w={bw} {b['name']}")
    board_advancing = not dominators and not exact_dup
    g["novelty"] = {"cell": [wc, lc], "board_advancing": board_advancing,
                    "dominated_by": dominators, "literature_novelty": "unverified"}
    verdict["labels"].append(
        f"advances the {wc} x {lc} board" if board_advancing
        else "does not advance its board cell")
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

"""Reconstruct the 931-qubit checkerboard reduction and its archived proposals.

Author: @vprusso. Source checkerboard: @mathysrennela; secondary search
source: @npdeep. This script constructs arrays, checks exact fingerprints,
and optionally delegates saved-witness validation to the unchanged kit.
It contains no distance-search or distance-certification algorithm.
"""

import argparse
import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def find_repo():
    for path in HERE.parents:
        if (path / "verify/qldpc_verify.py").is_file() and (path / "codes").is_dir():
            return path
    raise RuntimeError("Use --repo to select a qldpc-challenge checkout")


def payload(state):
    hx, hz, coords, _ = state
    return {
        "n": int(hx.shape[1]),
        "checks": {side: [np.flatnonzero(row).astype(int).tolist() for row in h] for side, h in [("X", hx), ("Z", hz)]},
        "coordinates": np.asarray(coords, dtype=float).tolist(),
        "layers": 1,
    }


def fingerprint(state):
    raw = json.dumps(payload(state), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def from_document(doc):
    hs = []
    for side in ("X", "Z"):
        h = np.zeros((len(doc["checks"][side]), doc["n"]), dtype=np.int8)
        for i, support in enumerate(doc["checks"][side]):
            h[i, support] = 1
        hs.append(h)
    return (*hs, np.asarray(doc["locality"]["coordinates"], dtype=float), list(range(doc["n"])))


def apply_move(state, move, cleanup):
    """Apply one constructor move; original indices are never renumbered in recipes."""
    hx, hz, coords, original = state
    hx, hz = hx.copy(), hz.copy()
    original = original.copy()
    q = original.index(move["original_qubit"])
    h = hx if move["side"] == "X" else hz
    support = move["pivot_support_original"]
    matches = [i for i, row in enumerate(h) if [original[int(j)] for j in np.flatnonzero(row)] == support]
    assert matches, ("Missing recorded pivot", move)
    r = matches[0]
    if "pivot_row" in move:
        assert r == move["pivot_row"], ("Pivot row order differs", move)
    degree = int(h[:, q].sum())
    if move["operation"] == "degree_one_graft":
        assert degree == 1
    elif move["operation"] == "local_contraction":
        assert degree == move["degree"]
        assert degree == 1 or int(h[r].sum()) == 2
        pivot = h[r].copy()
        for rr in np.flatnonzero(h[:, q]):
            if rr != r:
                h[rr] ^= pivot
    else:
        raise ValueError(move["operation"])
    if move["side"] == "X":
        hx = np.delete(hx, r, axis=0)
    else:
        hz = np.delete(hz, r, axis=0)
    hx, hz = np.delete(hx, q, axis=1), np.delete(hz, q, axis=1)
    coords = np.delete(coords, q, axis=0)
    del original[q]
    if move["operation"] == "local_contraction":
        hx, hz, kept = cleanup(hx, hz)
        live = set(map(int, kept))
        removed = [v for i, v in enumerate(original) if i not in live]
        assert removed == move["cleanup_removed_original"]
        coords = coords[kept]
        original = [original[int(i)] for i in kept]
    return hx, hz, coords, original


class Reconstruction:
    def __init__(self, repo, recipe):
        self.repo, self.recipe = repo, recipe
        sys.path.insert(0, str(repo / "research/local2d"))
        from boundary_engine import _cleanup

        self.cleanup = _cleanup
        self.nodes = {n["id"]: n for n in recipe["nodes"]}
        self.sources = {s["id"]: s for s in recipe["sources"]}
        cleanup_file = repo / "research/local2d/boundary_engine.py"
        assert hashlib.sha256(cleanup_file.read_bytes()).hexdigest() == recipe["cleanup_module_sha256"]

    @lru_cache(maxsize=48)
    def build(self, key):
        if key in self.sources:
            source = self.sources[key]
            raw = (self.repo / source["path"]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source["file_sha256"], source["path"]
            state = from_document(json.loads(raw))
            assert fingerprint(state) == source["arrays_sha256"]
            return state
        node = self.nodes[key]
        state = apply_move(self.build(node["parent"]), node["move"], self.cleanup)
        assert fingerprint(state) == node["arrays_sha256"], key
        assert state[0].shape[1] == node["n"], key
        return state


def check_saved_witnesses(reconstruction, evidence):
    """Delegate saved-support checks to the repository validator without searching."""
    sys.path[:0] = [str(reconstruction.repo / "verify"), str(reconstruction.repo / "research/kit")]
    from surrogate import _validate_fast_witness

    count = 0
    for case in evidence["cases"]:
        if case["initial"] is None:
            assert not case["native_returns"]
            continue
        hx, hz, _, _ = reconstruction.build(case["node"])
        proposals = [
            (side, case["initial"]["distance"][side]["value"], case["initial"]["distance"][side]["witness"])
            for side in ("X", "Z")
        ]
        proposals += [(p["side"], p["weight"], p["witness"]) for p in case["native_returns"]]
        for side, weight, support in proposals:
            assert _validate_fast_witness(hx, hz, weight, side, support), (case["node"], side, support)
            count += 1
    for audit in evidence.get("independent_audits", []):
        hx, hz, _, _ = reconstruction.build(audit["node"])
        for p in audit["native_returns"]:
            assert _validate_fast_witness(hx, hz, p["weight"], p["side"], p["witness"])
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument(
        "--all-cases", action="store_true", help="Rebuild all archived proposals and compare exact array fingerprints."
    )
    parser.add_argument(
        "--check-witnesses",
        action="store_true",
        help="Validate saved supports with the unchanged repository witness checker; no search.",
    )
    parser.add_argument(
        "--compare", type=Path, help="Compare final check arrays and coordinates against a candidate document."
    )
    parser.add_argument("--output", type=Path, help="Write final arrays and original indices to an NPZ file.")
    args = parser.parse_args()
    recipe = json.loads((HERE / "recipe.json").read_text())
    reconstruction = Reconstruction(args.repo or find_repo(), recipe)
    final = reconstruction.build(recipe["final_node"])
    assert final[3] == recipe["final_original_indices"]
    if args.compare:
        assert payload(final) == payload(from_document(json.loads(args.compare.read_text())))
    checked = 0
    if args.all_cases:
        for node in recipe["nodes"]:
            reconstruction.build(node["id"])
            checked += 1
    witnesses = None
    if args.check_witnesses:
        witnesses = check_saved_witnesses(reconstruction, json.loads((HERE / "search-evidence.json").read_text()))
    if args.output:
        np.savez_compressed(args.output, HX=final[0], HZ=final[1], coordinates=final[2], original_indices=final[3])
    print(
        json.dumps(
            {
                "n": final[0].shape[1],
                "final_arrays_sha256": fingerprint(final),
                "additional_recipe_nodes_checked": checked,
                "saved_witnesses_validated": witnesses,
                "distance_searches_performed": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

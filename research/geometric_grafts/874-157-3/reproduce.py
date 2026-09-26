"""Reproduce fixed rectangular plaquette/graft artifacts; no distance search.

Affinely punctured checkerboard grammar: @mathysrennela, notes/961-169-3.md.
Rectangular completion and this finite contraction campaign: @vprusso.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "verify/gf2.py").exists())
sys.path[:0] = [str(ROOT / "research/kit"), str(ROOT / "verify"), str(ROOT / "research/local2d")]
from boundary_engine import _cleanup
from gf2 import rank as trusted_rank
from qldpc_verify import _stabilizer_block_count
from surrogate import _validate_fast_witness

try:
    import gf2_fast as F
except ImportError:
    from gf2 import rref

    class F:
        gf2_rref = staticmethod(rref)


def dense(rows, n):
    h = np.zeros((len(rows), n), dtype=np.uint8)
    for i, support in enumerate(rows):
        h[i, list(support)] = 1
    return h


def initial(W, H, px, pz):
    rows, holes = [[], []], [[], []]
    for x in range(W - 1):
        for y in range(H - 1):
            side = (x + y) % 2
            support = (x * H + y, x * H + y + 1, (x + 1) * H + y, (x + 1) * H + y + 1)
            phase = (px, pz)[side]
            (holes if (x + (3 if side == 0 else 2) * y) % 5 == phase else rows)[side].append(support)
    return rows, holes


def construct(W, H, px, pz, order):
    n = W * H
    rows, holes = initial(W, H, px, pz)
    cols = [[0] * n for _ in range(2)]

    def append(side, support):
        bit = 1 << len(rows[side])
        rows[side].append(tuple(support))
        for q in support:
            cols[side][q] ^= bit

    for side in [0, 1]:
        for i, support in enumerate(rows[side]):
            for q in support:
                cols[side][q] ^= 1 << i
    rng = np.random.default_rng(924995100 + order)
    pairs = []
    for x in range(W):
        for y in range(H):
            for dx, dy in [(0, 1), (1, -1), (1, 0), (1, 1)]:
                xx, yy = x + dx, y + dy
                if 0 <= xx < W and 0 <= yy < H:
                    # Every supplied pin in the baseline touches this band.
                    if min(x, y, W - 1 - x, H - 1 - y, xx, yy, W - 1 - xx, H - 1 - yy) <= 1:
                        pairs.append((x * H + y, xx * H + yy))
    candidates = [(side, a, b) for side in [0, 1] for a, b in pairs]
    permutation = rng.permutation(len(candidates))
    priority = {tuple(candidates[i]): rank for rank, i in enumerate(permutation)}
    # Pure algebraic completion: commutation, boundary coverage, and local
    # independent rows. No logical operators are enumerated or classified.
    # Order0/1 favor one Pauli side, order2/3 use a mixed fixed-seed order.
    pin_count = [0, 0]
    for epoch in range(3):
        while True:
            available = []
            for side, a, b in candidates:
                if cols[1 - side][a] != cols[1 - side][b]:
                    continue
                if cols[side][a] == cols[side][b] and cols[side][a] != 0:
                    # This is only a redundant-candidate heuristic; the final
                    # row basis and ranks are computed by trusted native GF2.
                    continue
                zero = (cols[side][a] == 0) + (cols[side][b] == 0)
                favored = int(side == order) if order < 2 else 0
                available.append(((-zero, -favored, priority[(side, a, b)]), side, a, b))
            if not available:
                break
            _, side, a, b = min(available)
            append(side, (a, b))
            pin_count[side] += 1
            candidates.remove((side, a, b))
        missing = [(side, q) for side in [0, 1] for q in range(n) if cols[side][q] == 0]
        if not missing:
            break
        changed = False
        for side, q in missing:
            if cols[side][q]:
                continue
            for support in holes[side]:
                if q not in support:
                    continue
                syndrome = 0
                for a in support:
                    syndrome ^= cols[1 - side][a]
                if syndrome == 0:
                    append(side, support)
                    holes[side].remove(support)
                    changed = True
                    break
        if not changed:
            break
    missing = sum(c == 0 for side in cols for c in side)
    if missing:
        return None, {"uncovered_qubit_sector_pairs": missing}
    matrices = []
    for side in [0, 1]:
        h = dense(rows[side], n)
        _, independent = F.gf2_rref(h.T)
        matrices.append(h[independent])
    # Sparse bit-column construction already maintains commutation; verify it
    # independently here, using integer matrix multiplication only.
    assert not np.any((matrices[0] @ matrices[1].T) % 2)
    k = n - len(matrices[0]) - len(matrices[1])
    return matrices, {
        "k": k,
        "n": n,
        "pin_rows_added": pin_count,
        "remaining_holes": list(map(len, holes)),
        "ranks": list(map(len, matrices)),
        "g_at_hypothetical_d3": 9 * k / n,
    }


def supports(matrix):
    return [list(map(int, np.flatnonzero(row))) for row in matrix]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def matrix(support_rows, n):
    return dense(support_rows, n)


def state_for_base(base):
    p = base["parameters"]
    matrices, record = construct(p["W"], p["H"], p["px"], p["pz"], p["order"])
    assert matrices is not None
    hx, hz = matrices
    checks = {"X": supports(hx), "Z": supports(hz)}
    assert digest(checks) == base["checks_sha256"], "Base completion differs"
    xy = np.array([(x, y) for x in range(p["W"]) for y in range(p["H"])], dtype=float)
    return hx, hz, xy, list(range(p["W"] * p["H"]))


def contract(state, move):
    hx, hz, coords, originals = state
    side = move["side"]
    q = originals.index(move["original_qubit"])
    own = hx if side == "X" else hz
    wanted = move["pivot_original_support"]
    rows = [r for r, row in enumerate(own) if [originals[int(j)] for j in np.flatnonzero(row)] == wanted]
    assert rows, "Recorded pivot is absent"
    r = rows[0]
    a, b = hx.copy(), hz.copy()
    own = a if side == "X" else b
    assert int(own[:, q].sum()) == move["degree"]
    pivot = own[r].copy()
    for rr in np.flatnonzero(own[:, q]):
        if rr != r:
            own[rr] ^= pivot
    if side == "X":
        a = np.delete(a, r, 0)
    else:
        b = np.delete(b, r, 0)
    a, b = np.delete(a, q, 1), np.delete(b, q, 1)
    xy = np.delete(coords, q, 0)
    ix = originals.copy()
    ix.pop(q)
    a, b, kept = _cleanup(a, b)
    keptset = set(map(int, kept))
    assert [value for i, value in enumerate(ix) if i not in keptset] == move["cleanup_removed_original"]
    return a, b, xy[kept], [ix[int(i)] for i in kept]


def validate_saved(state, record):
    """Validate retained supports only; this never searches for a logical."""
    hx, hz, _, _ = state
    count = 0
    initial = record.get("initial_distance")
    if initial:
        for side in ["X", "Z"]:
            entry = initial[side]
            assert _validate_fast_witness(hx, hz, entry["value"], side, entry["witness"])
            count += 1
    for ret in record.get("native_returns", []):
        witness = ret.get("witness", ret.get("support"))
        assert _validate_fast_witness(hx, hz, ret["weight"], ret["side"], witness)
        count += 1
    return count


def project_core(state, projection):
    hx, hz, xy, originals = state
    n = hx.shape[1]
    blocks = projection["blocks"]
    assert sorted(q for b in blocks for q in b["indices_in_source"]) == list(range(n))
    for h, name in [(hx, "X"), (hz, "Z")]:
        ranks = [trusted_rank(h[:, b["indices_in_source"]]) for b in blocks]
        assert ranks == [b["rank_" + name] for b in blocks]
        assert sum(ranks) == trusted_rank(h), "Projection blocks are not a direct sum"
    assert all(b["n"] - b["rank_X"] - b["rank_Z"] == b["k"] for b in blocks)
    assert all(b["k"] == 0 for b in blocks[1:])
    assert _stabilizer_block_count(hx, hz, n)[1] == projection["trusted_block_sizes"]
    kept = projection["kept_source_indices"]
    a, b = hx[:, kept], hz[:, kept]
    a = a[a.any(1)]
    b = b[b.any(1)]
    assert _stabilizer_block_count(a, b, len(kept))[0] == 1
    return a, b, xy[kept], [originals[i] for i in kept]


def main():
    ap = argparse.ArgumentParser(description="Reproduce recorded geometry; no distance searches")
    ap.add_argument("--compare", type=Path, help="Compare against a submission JSON")
    ap.add_argument(
        "--audit-evidence",
        action="store_true",
        help="Replay all constructor proposals and trusted-check every retained witness",
    )
    args = ap.parse_args()
    recipe = json.loads((HERE / "recipe.json").read_text())
    evidence = json.loads((HERE / "search-evidence.json").read_text())
    bases = {b["id"]: b for b in evidence["base_screens"]}
    state = state_for_base(bases[recipe["base_id"]])
    for move in recipe["accepted_moves"]:
        state = contract(state, move)
    state = project_core(state, recipe["core_projection"])
    hx, hz, xy, originals = state
    checks = {"X": supports(hx), "Z": supports(hz)}
    assert digest(checks) == recipe["final"]["checks_sha256"]
    assert digest(xy.tolist()) == recipe["final"]["coordinates_sha256"]
    assert originals == recipe["final"]["original_indices"]
    assert hx.shape[1] == recipe["final"]["n"]
    assert not np.any((hx @ hz.T) % 2)
    k = hx.shape[1] - trusted_rank(hx) - trusted_rank(hz)
    assert k == recipe["final"]["k"]
    if args.compare:
        doc = json.loads(args.compare.read_text())
        assert doc["checks"] == checks
        assert doc["locality"]["coordinates"] == xy.tolist()
        assert doc["n"] == hx.shape[1] and doc["k"] == k
        for side in ["X", "Z"]:
            e = doc["distance"][side]
            assert _validate_fast_witness(hx, hz, e["value"], side, e["witness"])
    witness_checks = 0
    if args.audit_evidence:
        states = {}
        for base in evidence["base_screens"]:
            states[base["id"]] = state_for_base(base)
            witness_checks += validate_saved(states[base["id"]], base)
        for branch in evidence["graft_branches"]:
            prefix = branch["id"]
            states[prefix + ":source"] = states[branch["base_id"]]
            for proposal in branch["proposals"]:
                st = contract(states[prefix + ":" + proposal["parent_accepted_id"]], proposal["move"])
                if proposal.get("checks_sha256"):
                    assert digest({"X": supports(st[0]), "Z": supports(st[1])}) == proposal["checks_sha256"]
                witness_checks += validate_saved(st, proposal)
                if proposal["accepted"]:
                    states[prefix + ":" + proposal["id"]] = st
        cores_by_digest = {}
        for core in evidence["connected_cores"]:
            parent = states[core["parent_branch"] + ":" + core["parent_proposal_id"]]
            st = project_core(parent, core["projection"])
            assert digest({"X": supports(st[0]), "Z": supports(st[1])}) == core["checks_sha256"]
            witness_checks += validate_saved(st, core)
            cores_by_digest[core["checks_sha256"]] = st
        for audit in evidence.get("official_final_audits", {}).values():
            st = cores_by_digest[audit["checks_sha256"]]
            witness_checks += validate_saved(st, audit)
            witness_checks += validate_saved(st, {"initial_distance": audit["selected_distance"]})
    print(
        json.dumps(
            {
                "reproduced": True,
                "n": hx.shape[1],
                "k": k,
                "checks_sha256": digest(checks),
                "coordinates_sha256": digest(xy.tolist()),
                "recorded_moves": len(recipe["accepted_moves"]),
                "retained_witness_checks": witness_checks,
                "distance_searches": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

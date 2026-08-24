"""Parity tests for the optional gf2_fast C++ accelerator against verify/gf2.py.

The accelerator is search-only tooling: the pure-Python gf2.py stays the
reference implementation, so every exported function must agree with it. Skips
(exit 0) when the extension is not built -- CI does not build it; run
`make fast` first to exercise these locally.
"""
import json
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
import gf2

try:
    import gf2_fast
except ImportError:                      # pragma: no cover - depends on `make fast`
    import pytest
    pytest.skip("gf2_fast not built (run `make fast`); the pure-Python "
                "fallback is the reference and needs no test here.",
                allow_module_level=True)

FAILURES = []


def check(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        FAILURES.append(name)


def _matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


# 1. rank / rref / kernel parity on random matrices across shapes.
rng = np.random.default_rng(20260707)
for trial in range(30):
    rows = int(rng.integers(1, 40))
    cols = int(rng.integers(1, 90))
    M = (rng.random((rows, cols)) < 0.3).astype(np.int8)
    rank_py = gf2.rank(M)
    rank_fast = gf2_fast.gf2_rank(M)
    if rank_py != rank_fast:
        check(f"rank parity trial {trial}", False,
              f"py={rank_py} fast={rank_fast}")
        break
    K_py = gf2.kernel_basis(M)
    K_fast = gf2_fast.kernel_basis(M)
    ok = (K_py.shape[0] == K_fast.shape[0]           # same nullity
          and (K_fast.shape[0] == 0
               or (not ((M @ K_fast.T) % 2).any()    # rows lie in the kernel
                   and gf2.rank(K_fast) == K_fast.shape[0])))  # and are independent
    if not ok:
        check(f"kernel parity trial {trial}", False,
              f"py dim {K_py.shape}, fast dim {K_fast.shape}")
        break
else:
    check("rank+kernel parity (30 random matrices)", True)

# 2. compute_k parity on every certified code on the board.
codes_dir = os.path.join(_HERE, "..", "codes")
mismatch = []
for fname in sorted(os.listdir(codes_dir)):
    if not fname.endswith(".json"):
        continue
    doc = json.load(open(os.path.join(codes_dir, fname)))
    n = doc["n"]
    HX = _matrix(doc["checks"]["X"], n)
    HZ = _matrix(doc["checks"]["Z"], n)
    if gf2_fast.compute_k(HX, HZ) != doc["k"]:
        mismatch.append(fname)
check("compute_k parity (all board codes)", not mismatch, str(mismatch))

# 3. distance_rand re-finds the known distance of a small certified code.
doc = json.load(open(os.path.join(codes_dir, "72-6-6.json")))
HX = _matrix(doc["checks"]["X"], doc["n"])
HZ = _matrix(doc["checks"]["Z"], doc["n"])
d = gf2_fast.distance_rand(HX, HZ, trials=2000, seed=3, pair_depth=8)
check("distance_rand finds d on [[72,6,6]]", d == doc["distance"]["d"],
      f"found {d}, known {doc['distance']['d']}")

dp = gf2_fast.distance_rand_parallel(HX, HZ, trials=2000, seed=3,
                                     pair_depth=8, threads=4)
check("distance_rand_parallel agrees", dp == d, f"parallel {dp} vs single {d}")

# 4. distance_rand_witness: the returned support must be a genuine nontrivial
#    logical of the returned weight -- validated with the PYTHON stack, which is
#    exactly the trust pattern callers must follow.
w, side, support = gf2_fast.distance_rand_witness(HX, HZ, trials=2000, seed=3,
                                                  pair_depth=8, threads=4)
v = np.zeros(doc["n"], dtype=np.int8)
v[list(support)] = 1
Hcheck = HZ if side == "X" else HX
La, Lb = (HX, HZ) if side == "X" else (HZ, HX)
L = gf2.logical_basis(La, Lb)
ok = (side in ("X", "Z")
      and int(v.sum()) == w
      and not ((Hcheck @ v) % 2).any()
      and bool(((L @ v) % 2).any())
      and w == d)
check("distance_rand_witness returns a valid logical", ok,
      f"w={w} side={side} |support|={len(support)}")

def test_gf2_fast_matches_reference():
    """pytest entry point: the checks above run at import, this reports them."""
    assert not FAILURES, FAILURES


def test_dem_rand_witness_parity():
    """The circuit-tier trial loop (dem_rand_witness) against the numpy
    reference loop in circuit_tools.ris_dem: same hook-limited bound on the
    greedy [[25,1,5]] Z-memory DEM, valid witness, deterministic given
    (seed, trials, threads), and the guarded fallback path unchanged."""
    import circuit_tools as ct
    from qldpc_verify import _matrix as _m
    ROOT = os.path.dirname(_HERE)
    doc = json.load(open(os.path.join(ROOT, "codes", "25-1-5.json")))
    n = doc["n"]
    HX = _m(doc["checks"]["X"], n)
    HZ = _m(doc["checks"]["Z"], n)
    skel = ct.build_css_memory(HX, HZ, rounds=5, basis="Z")
    dem = ct.derive_dem(ct.apply_noise(skel, n))
    H, L = ct.dem_matrices(dem)

    w, wit = gf2_fast.dem_rand_witness(H, L, trials=200, seed=7)
    assert ct.witness_errors(dem, wit, w) == []
    assert gf2_fast.dem_rand_witness(H, L, trials=200, seed=7) == (w, wit)

    # reference: the numpy loop (force the fallback) finds the same bound
    saved, ct._GF = ct._GF, None
    try:
        w_py, wit_py = ct.ris_dem(H, L, trials=50, seed=7)
    finally:
        ct._GF = saved
    assert ct.witness_errors(dem, wit_py, w_py) == []
    assert w == w_py == 3          # the greedy schedule's hook, both paths

    # the wrapper takes the C++ path and self-agrees
    w2, wit2 = ct.ris_dem(H, L, trials=200, seed=7)
    assert w2 == 3 and ct.witness_errors(dem, wit2, w2) == []


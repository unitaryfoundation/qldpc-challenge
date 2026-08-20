"""Tests for the ris_gpu wrapper (verify/ris_gpu.py).

Everything CPU-side runs everywhere: packing layout, input-file format,
output parsing, and the CPU witness verification that gates what the GPU
reports. The end-to-end GPU check runs only when build/ris_gpu exists and a
CUDA device answers; otherwise it is skipped (this is CI, which has no GPU).
"""

import json
import os
import struct
import subprocess
import sys
import tempfile

import numpy as np
import pytest

import gf2
import ris_gpu

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_pack_rows_layout():
    # column j must land in word j//64, bit j%64 (LSB-first)
    M = np.zeros((2, 130), dtype=np.uint8)
    M[0, 0] = 1
    M[0, 63] = 1
    M[0, 64] = 1
    M[1, 129] = 1
    P = ris_gpu.pack_rows(M)
    assert P.shape == (2, 3), P.shape
    assert P[0, 0] == (1 | (1 << 63)), hex(P[0, 0])
    assert P[0, 1] == 1
    assert P[0, 2] == 0
    assert P[1, 2] == 2, hex(P[1, 2])

    # round-trip through an independent unpack
    rng = np.random.default_rng(7)
    M = rng.integers(0, 2, size=(5, 100)).astype(np.uint8)
    P = ris_gpu.pack_rows(M)
    back = np.zeros_like(M)
    for r in range(M.shape[0]):
        for j in range(M.shape[1]):
            back[r, j] = (int(P[r, j // 64]) >> (j % 64)) & 1
    assert np.array_equal(M, back)


def test_input_file_format():
    W_null = np.eye(3, 70, dtype=np.uint8)
    W_log = np.ones((2, 70), dtype=np.uint8)
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, W_null, W_log, 70)
        with open(path, "rb") as f:
            blob = f.read()
        assert blob[:8] == b"RISGPU01"
        n, k_null, k_logical, nw = struct.unpack_from("<4i", blob, 8)
        assert (n, k_null, k_logical, nw) == (70, 3, 2, 2)
        assert len(blob) == 8 + 16 + (3 + 2) * nw * 8
        words = np.frombuffer(blob, dtype="<u8", offset=24)
        assert words[0] == 1          # W_null row 0 = e_0
        assert words[2 * 2] == 4      # row 2 = e_2
    finally:
        os.unlink(path)


def test_parse_output():
    res = ris_gpu.parse_output(
        "mode=recover\nn=7\ntrials=100000\nbest_weight=3\nsupport=0,1,2\n")
    assert res["best_weight"] == 3
    assert res["trials"] == 100000
    assert res["support"] == [0, 1, 2]
    res = ris_gpu.parse_output("mode=estimate\nbest_weight=-1\n")
    assert res["best_weight"] == -1
    assert "support" not in res


def load_steane():
    with open(os.path.join(ROOT, "codes", "7-1-3.json")) as f:
        doc = json.load(f)
    n = doc["n"]
    HX = ris_gpu.checks_matrix(doc["checks"]["X"], n)
    HZ = ris_gpu.checks_matrix(doc["checks"]["Z"], n)
    return n, HX, HZ


def test_cpu_verify_gate():
    n, HX, HZ = load_steane()
    L_opp = gf2.logical_basis(HX, HZ)  # Z-type logicals, for the X side

    # a stabilizer row commutes with everything: must be rejected
    stab = sorted(int(q) for q in np.flatnonzero(HX[0]))
    assert not ris_gpu.cpu_verify(stab, n, HZ, L_opp)

    # a genuine X logical (weight 3 in the Steane code): kernel_basis(HZ)
    # rows that anticommute with a Z logical
    found = None
    for row in gf2.kernel_basis(HZ):
        sup = sorted(int(q) for q in np.flatnonzero(row))
        if ris_gpu.cpu_verify(sup, n, HZ, L_opp):
            found = sup
            break
    assert found is not None, "no logical found in ker(HZ) basis"

    # a single qubit is outside ker(HZ) in the Steane code: must be rejected
    assert not ris_gpu.cpu_verify([0], n, HZ, L_opp)

    # a verified operator's weight is recounted, never len(support)
    assert ris_gpu.cpu_verify(found, n, HZ, L_opp) == len(found)

    # malformed GPU output must be rejected, not crash or miscount:
    # duplicate indices (would silently collapse in the indicator vector)
    assert ris_gpu.cpu_verify(found + [found[0]], n, HZ, L_opp) is None
    # out-of-range index (would raise IndexError unguarded)
    assert ris_gpu.cpu_verify([0, n + 3], n, HZ, L_opp) is None
    assert ris_gpu.cpu_verify([-1], n, HZ, L_opp) is None
    # empty support
    assert ris_gpu.cpu_verify([], n, HZ, L_opp) is None


def gpu_available(binary):
    if not (os.path.isfile(binary) and os.access(binary, os.X_OK)):
        return False
    r = subprocess.run(["nvidia-smi", "-L"], capture_output=True)
    return r.returncode == 0 and b"GPU" in r.stdout


def test_end_to_end_gpu():
    binary = os.path.join(ROOT, "build", "ris_gpu")
    if not gpu_available(binary):
        pytest.skip("no ris_gpu binary or no GPU")
    n, HX, HZ = load_steane()
    L_opp = gf2.logical_basis(HX, HZ)
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, gf2.kernel_basis(HZ), L_opp, n)
        proc = subprocess.run(
            [binary, path, "--mode", "recover", "--trials", "200000",
             "--seed", "5", "--k-sub", "8"],
            capture_output=True, text=True, check=True)
        res = ris_gpu.parse_output(proc.stdout)
        assert res["best_weight"] == 3, res  # Steane distance is exactly 3
        assert ris_gpu.cpu_verify(res["support"], n, HZ, L_opp)
        assert len(res["support"]) == 3
    finally:
        os.unlink(path)


def test_pair_depth_flag_surface():
    # CPU-side: the wrapper must advertise --pair-depth and accept it; the
    # binary usage text must document it (parsed here from the .cu so the
    # check runs without nvcc).
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "verify", "ris_gpu.py"), "--help"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "--pair-depth" in r.stdout
    with open(os.path.join(ROOT, "verify", "ris_gpu.cu")) as f:
        src = f.read()
    assert "--pair-depth" in src and "deep_pair_kernel" in src


def test_end_to_end_gpu_pair_depth():
    # Deep-mode PLUMBING on the Steane code: full-kernel default (no
    # --k-sub), witness recovery, CPU re-verify. At this size the pair
    # stage itself is not load-bearing (any config saturates); the
    # pair-stage mechanism is exercised by test_gpu_pair_stage_matters.
    binary = os.path.join(ROOT, "build", "ris_gpu")
    if not gpu_available(binary):
        pytest.skip("no ris_gpu binary or no GPU")
    n, HX, HZ = load_steane()
    L_opp = gf2.logical_basis(HX, HZ)
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, gf2.kernel_basis(HZ), L_opp, n)
        proc = subprocess.run(
            [binary, path, "--mode", "recover", "--trials", "50000",
             "--seed", "5", "--pair-depth", "8"],
            capture_output=True, text=True, check=True)
        res = ris_gpu.parse_output(proc.stdout)
        assert res["best_weight"] == 3, res
        assert ris_gpu.cpu_verify(res["support"], n, HZ, L_opp)
        # deep mode defaults k_sub to the full kernel basis
        assert res["k_sub"] == gf2.kernel_basis(HZ).shape[0], res
    finally:
        os.unlink(path)


def test_end_to_end_gpu_pair_depth_hybrid():
    # Explicit small --k-sub together with --pair-depth: the sketch-draw +
    # pair-stage hybrid path. Needs a code whose kernel is genuinely larger
    # than the sketch (the Steane kernel is only 4-dim, where --k-sub 8
    # would be clamped to full basis). Assertions are stochastic-safe: the
    # path must run, honor the sketch size, and anything recovered must
    # CPU-verify -- no exact-weight demand at a weak sketch.
    binary = os.path.join(ROOT, "build", "ris_gpu")
    if not gpu_available(binary):
        pytest.skip("no ris_gpu binary or no GPU")
    with open(os.path.join(ROOT, "codes", "186-10-14.json")) as f:
        doc = json.load(f)
    n = doc["n"]
    HX = ris_gpu.checks_matrix(doc["checks"]["X"], n)
    HZ = ris_gpu.checks_matrix(doc["checks"]["Z"], n)
    L_opp = gf2.logical_basis(HX, HZ)
    K = gf2.kernel_basis(HZ)
    assert K.shape[0] > 8, "test premise: kernel larger than the sketch"
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, K, L_opp, n)
        proc = subprocess.run(
            [binary, path, "--mode", "recover", "--trials", "100000",
             "--seed", "5", "--k-sub", "8", "--pair-depth", "8"],
            capture_output=True, text=True, check=True)
        res = ris_gpu.parse_output(proc.stdout)
        assert res["k_sub"] == 8, res
        if res.get("support"):
            w = ris_gpu.cpu_verify(res["support"], n, HZ, L_opp)
            assert w == res["best_weight"], (w, res)
    finally:
        os.unlink(path)


def test_gpu_pair_depth_midsize():
    # Deep-mode exactness on a mid-size board code ([[186,10,14]]): 100k
    # full-kernel trials reach the known distance, witness re-verifies.
    # Covers full-basis deep mode, not the pair stage per se (at n=186 the
    # exact distance is reached with pairs inert; see
    # test_gpu_pair_stage_matters for the pair-sensitive case).
    binary = os.path.join(ROOT, "build", "ris_gpu")
    if not gpu_available(binary):
        pytest.skip("no ris_gpu binary or no GPU")
    with open(os.path.join(ROOT, "codes", "186-10-14.json")) as f:
        doc = json.load(f)
    n = doc["n"]
    HX = ris_gpu.checks_matrix(doc["checks"]["X"], n)
    HZ = ris_gpu.checks_matrix(doc["checks"]["Z"], n)
    L_opp = gf2.logical_basis(HX, HZ)
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, gf2.kernel_basis(HZ), L_opp, n)
        proc = subprocess.run(
            [binary, path, "--mode", "recover", "--trials", "100000",
             "--seed", "11", "--pair-depth", "24"],
            capture_output=True, text=True, check=True)
        res = ris_gpu.parse_output(proc.stdout)
        assert res["best_weight"] == 14, res
        w = ris_gpu.cpu_verify(res["support"], n, HZ, L_opp)
        assert w == 14, (w, res)
    finally:
        os.unlink(path)


def test_gpu_pair_stage_matters():
    # The pair stage must be load-bearing: at n >= 500 and a small matched
    # trial budget, depth-24 finds strictly lighter operators than depth-1
    # (full-basis RREF, pairs inert). Fixed seed; estimate mode is a pure
    # min over a deterministic trial set, so the comparison is exact and
    # this test FAILS if the pair stage is deleted or disabled.
    binary = os.path.join(ROOT, "build", "ris_gpu")
    if not gpu_available(binary):
        pytest.skip("no ris_gpu binary or no GPU")
    with open(os.path.join(ROOT, "codes", "514-162-29.json")) as f:
        doc = json.load(f)
    n = doc["n"]
    HX = ris_gpu.checks_matrix(doc["checks"]["X"], n)
    HZ = ris_gpu.checks_matrix(doc["checks"]["Z"], n)
    L_opp = gf2.logical_basis(HX, HZ)
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        path = tmp.name
    try:
        ris_gpu.write_input(path, gf2.kernel_basis(HZ), L_opp, n)
        best = {}
        for pd in (1, 24):
            proc = subprocess.run(
                [binary, path, "--mode", "estimate", "--trials", "20000",
                 "--seed", "11", "--pair-depth", str(pd)],
                capture_output=True, text=True, check=True)
            best[pd] = ris_gpu.parse_output(proc.stdout)["best_weight"]
        assert best[24] < best[1], best
    finally:
        os.unlink(path)


if __name__ == "__main__":
    for fn in (test_pack_rows_layout, test_input_file_format,
               test_parse_output, test_cpu_verify_gate,
               test_pair_depth_flag_surface, test_end_to_end_gpu,
               test_end_to_end_gpu_pair_depth,
               test_end_to_end_gpu_pair_depth_hybrid,
               test_gpu_pair_depth_midsize, test_gpu_pair_stage_matters):
        try:
            fn()
        except pytest.skip.Exception as e:
            print(f"SKIP {fn.__name__}: {e}")
    print("ok")

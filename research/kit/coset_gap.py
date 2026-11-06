r"""Coset two-block codes of arXiv:2606.17268 (Aydin, Tamo, Barg), built in GAP.

The paper's construction (``Q_G^H(ahat, bhat)``) generalises the two-block
group-algebra codes to a subgroup ``H`` that need not be normal.  The data
the paper prints for each instance is:

* ``G = SmallGroup(ell, m)``;
* ``H`` is the ``s``-th non-normal subgroup of ``G`` in
  ``Filtered(AllSubgroups(G), H -> not IsNormal(G, H))``;
* ``ahat`` are 1-based indices into the coset-representative list
  ``LeftCosets(G, Core(G,H))`` -- the paper's support of the group-algebra
  element ``ahat`` of ``F[G]``;
* ``bhat`` are 1-based indices into ``LeftCosets(Normalizer(G,H), H)`` -- the
  support of ``bhat`` of ``F[N_G(H)]``.

The code's parity checks are

    H_X = [L(ahat) | R(bhat)],   H_Z = [R(bhat)^T | L(ahat)^T]

where ``L(g)`` is the left action of ``g`` on the left cosets of ``H`` in
``G`` (``xH -> (g x)H``) and ``R(g)`` the right action of the normalizer
(``xH -> (x g)H``), both as ``m x m`` permutation matrices with
``m = [G:H]``.  CSS commutation is automatic because the two actions
commute.

The matrices are assembled inside GAP, so that no convention -- coset
representatives, composition order, which side is transposed -- is left to
the caller.  GAP is asked for the group data; this module only parses what
GAP prints back.

Requires GAP (the ``smallgrp`` package) on ``PATH``.  The result is a CSS
code, so it is directly usable by ``research/kit/submit.py`` and by
``research/kit/rebuild.py`` as ``coset_gap.build``.
"""
import os
import subprocess
import tempfile

import numpy as np

GAP_DIR = os.environ.get("QLDPC_GAP_DIR") or tempfile.mkdtemp(prefix="qldpc-coset-gap-")

_TEMPLATE = r'''
LoadPackage("smallgrp");
SizeScreen([1000000, 1000000]);
G := SmallGroup(%(ell)d, %(m)d);
nons := Filtered(AllSubgroups(G), H -> not IsNormal(G, H));
H := nons[%(s)d];
CoreH := Core(G, H);
Nrm := Normalizer(G, H);
cosA := LeftCosets(G, CoreH);
cosB := LeftCosets(Nrm, H);
cosH := LeftCosets(G, H);
mm := Length(cosH);
cosidx := function(g)
  local i;
  for i in [1..mm] do
    if g in cosH[i] then return i; fi;
  od;
  return 0;
end;
Lmat := function(g)
  local M, i, r, j;
  M := NullMat(mm, mm, 0);
  for i in [1..mm] do
    r := Representative(cosH[i]);
    j := cosidx(g * r);
    M[j][i] := 1;
  od;
  return M;
end;
Rmat := function(g)
  local M, i, r, j;
  M := NullMat(mm, mm, 0);
  for i in [1..mm] do
    r := Representative(cosH[i]);
    j := cosidx(r * g);
    M[j][i] := 1;
  od;
  return M;
end;
a_els := List(%(ahat)s, i -> Representative(cosA[i]));
b_els := List(%(bhat)s, i -> Representative(cosB[i]));
LA := NullMat(mm, mm, 0);
for g in a_els do
  LA := (LA + Lmat(g)) mod 2;
od;
RB := NullMat(mm, mm, 0);
for g in b_els do
  RB := (RB + Rmat(g)) mod 2;
od;
RBT := TransposedMat(RB);
LAT := TransposedMat(LA);
Print("@@HX ", mm, " ", 2*mm, "\n");
for i in [1..mm] do
  Print("@@ROW");
  for j in [1..mm] do Print(" ", LA[i][j]); od;
  for j in [1..mm] do Print(" ", RB[i][j]); od;
  Print("\n");
od;
Print("@@HZ ", mm, " ", 2*mm, "\n");
for i in [1..mm] do
  Print("@@ROW");
  for j in [1..mm] do Print(" ", RBT[i][j]); od;
  for j in [1..mm] do Print(" ", LAT[i][j]); od;
  Print("\n");
od;
QUIT;
'''


def _parse(stdout):
    """Parse the ``@@HX`` / ``@@HZ`` blocks GAP printed."""
    HX = HZ = None
    mat = None
    filled = 0
    for line in stdout.splitlines():
        if line.startswith("@@HX ") or line.startswith("@@HZ "):
            _, cnt, ncol = line.split()
            mat = np.zeros((int(cnt), int(ncol)), dtype=np.int8)
            filled = 0
            if line.startswith("@@HX "):
                HX = mat
            else:
                HZ = mat
        elif line.startswith("@@ROW"):
            vals = [int(x) for x in line.split()[1:]]
            if len(vals) != mat.shape[1]:
                raise RuntimeError(
                    f"row has {len(vals)} entries, expected {mat.shape[1]}")
            mat[filled] = vals
            filled += 1
    if HX is None or HZ is None:
        raise RuntimeError("GAP output is missing a matrix block")
    return HX, HZ


def build(ell, m, s, ahat, bhat, timeout=900):
    """Return ``(HX, HZ)`` for the coset code of arXiv:2606.17268.

    ``ell``, ``m``, ``s`` are the paper's GAP identifiers: ``G =
    SmallGroup(ell, m)`` and ``H`` the ``s``-th non-normal subgroup.  ``ahat``
    and ``bhat`` are the paper's 1-based indices into the two coset
    representative lists.  The result is a CSS code of length ``2 [G:H]``.
    """
    os.makedirs(GAP_DIR, exist_ok=True)
    script = os.path.join(GAP_DIR, f"_gap_coset_{os.getpid()}.g")
    with open(script, "w") as f:
        f.write(_TEMPLATE % {
            "ell": ell, "m": m, "s": s,
            "ahat": "[" + ",".join(str(x) for x in ahat) + "]",
            "bhat": "[" + ",".join(str(x) for x in bhat) + "]",
        })
    try:
        r = subprocess.run(["gap", "-b", script], capture_output=True,
                           text=True, timeout=timeout)
    finally:
        try:
            os.remove(script)
        except OSError:
            pass
    return _parse(r.stdout)


# The instances of the paper's Table group_codes (main table) and Table
# group_codes_additional (Appendix F), as
# (n, k, d, ell, m, s, ahat, bhat).  Every one of these reproduces the
# paper's stated (n, k) exactly.
PAPER_INSTANCES = [
    (48, 8, 6, 384, 512, 53, [1, 34, 48], [1, 6, 12]),
    (96, 8, 10, 384, 512, 27, [1, 9, 87], [1, 21, 23]),
    (224, 12, 16, 224, 53, 1, [1, 81, 186], [1, 16, 47]),
    (84, 16, 8, 252, 21, 6, [1, 14, 71, 89], [1, 6, 8, 19]),
    (112, 16, 10, 224, 53, 9, [1, 11, 59, 81], [1, 15, 23, 25]),
    (128, 16, 12, 128, 10, 1, [1, 47, 75, 88], [1, 8, 12, 19]),
    (168, 16, 15, 168, 33, 1, [1, 72, 106, 109], [1, 11, 18, 26]),
    (36, 4, 6, 162, 3, 24, [1, 15, 36], [1, 4, 8]),
    (48, 4, 8, 216, 12, 14, [1, 26, 69], [1, 8, 9]),
    (54, 8, 6, 216, 47, 23, [1, 13, 27], [1, 4, 5]),
    (56, 6, 8, 56, 9, 1, [1, 5, 56], [1, 2, 9]),
    (60, 16, 4, 150, 8, 6, [1, 11, 31], [1, 10, 12]),
    (72, 4, 10, 72, 30, 1, [1, 12, 50], [1, 4, 17]),
    (72, 8, 8, 216, 47, 17, [1, 6, 31], [1, 7, 10]),
    (84, 6, 10, 252, 21, 6, [1, 24, 34], [1, 10, 20]),
    (90, 8, 10, 360, 99, 35, [1, 39, 41], [1, 4, 14]),
    (96, 4, 12, 288, 489, 93, [1, 19, 52], [1, 14, 24]),
    (108, 8, 10, 216, 47, 12, [1, 13, 67], [1, 8, 18]),
    (112, 6, 12, 336, 188, 59, [1, 76, 107], [1, 13, 14]),
    (112, 12, 8, 336, 188, 59, [1, 44, 106], [1, 12, 27]),
    (120, 8, 12, 360, 99, 18, [1, 162, 211], [1, 7, 11]),
    (126, 10, 10, 126, 8, 1, [1, 10, 81], [1, 5, 19]),
    (144, 4, 16, 216, 12, 1, [1, 26, 179], [1, 22, 33]),
    (150, 16, 8, 150, 8, 1, [1, 4, 55], [1, 7, 15]),
    (168, 16, 10, 168, 33, 1, [1, 92, 118], [1, 14, 30]),
    (180, 8, 16, 360, 99, 14, [1, 84, 128], [1, 5, 22]),
    (186, 10, 14, 186, 3, 1, [1, 74, 183], [1, 21, 29]),
]


if __name__ == "__main__":
    from css import compute_k, verify_css
    for (n_c, k_c, d_c, ell, m, s, ahat, bhat) in PAPER_INSTANCES:
        HX, HZ = build(ell, m, s, ahat, bhat)
        k = compute_k(HX, HZ)
        w = int(max(HX.sum(axis=1).max(), HZ.sum(axis=1).max()))
        print(f"[[{HX.shape[1]},{k},{d_c}]] (paper [[{n_c},{k_c},{d_c}]]) "
              f"w={w} css={verify_css(HX, HZ)}")

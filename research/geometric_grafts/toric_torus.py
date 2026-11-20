"""Rotated toric code on an L x L torus, weight 4, k = 2, d = L.

The construction is the board's own `topological` family: every plaquette of the
periodic L x L lattice is a check, colored by ``(i + j) mod 2`` into the X block
and the Z block. See ``codes/900-2-30.json`` ("rotated toric code (30x30
torus)") for the filed instance of the family, and ``codes/784-2-28.json`` /
``codes/676-2-26.json`` for the rest of the ladder.

Qubits are indexed row-major, ``q(i, j) = i * L + j``, so qubit ``q`` sits at
grid position ``(q // L, q % L)``. Each plaquette is the unit square
``{(i, j), (i+1, j), (i, j+1), (i+1, j+1)}`` with both coordinates taken mod L.

Why k = 2: there are ``L^2`` plaquettes and ``L^2`` qubits, and the stabilizer
group has exactly two independent relations -- one among the X plaquettes and
one among the Z plaquettes -- so ``k = L^2 - (L^2/2 - 1) - (L^2/2 - 1) = 2``.

Why d = L: a full row (or column) of qubits is a logical operator of weight L,
and the code is the standard toric code, whose distance is the shortest
non-contractible cycle length, L. The claim filed here is only the upper bound
``d <= L``, certified by an explicit witness; the matching lower bound is the
standard topological argument of arXiv:quant-ph/9707021.

``planar_coordinates`` lays the code out on the unit grid with unit spacing for
the ``locality`` block. The torus's wrap-around edges put a check's support
diameter at ~2L, far past the radius-4 cap, so the code is ``unrestricted`` --
which is where the existing ladder entries sit.
"""

import numpy as np


def plaquettes(L):
    """The plaquette supports, X block first, as sorted index lists.

    Returned as row lists rather than a matrix so the family can be compared
    against a board entry's ``checks`` block directly -- see the calibration in
    the module docstring of :func:`build_toric_torus`.
    """
    HX, HZ = [], []
    for i in range(L):
        for j in range(L):
            support = sorted(
                (
                    (i % L) * L + (j % L),
                    ((i + 1) % L) * L + (j % L),
                    (i % L) * L + ((j + 1) % L),
                    ((i + 1) % L) * L + ((j + 1) % L),
                )
            )
            (HX if (i + j) % 2 == 0 else HZ).append(support)
    return HX, HZ


def build_toric_torus(L):
    """Return ``(HX, HZ)`` for the L x L rotated toric code.

    The result is the kit's shape convention: two ``int`` arrays of shape
    ``(num_checks, n)`` holding 0/1 entries, not a list of supports.
    """
    if L < 2:
        raise ValueError("L must be >= 2")
    n = L * L
    blocks = []
    for rows in plaquettes(L):
        block = np.zeros((len(rows), n), dtype=np.int64)
        for r, support in enumerate(rows):
            block[r, list(support)] = 1
        blocks.append(block)
    return blocks[0], blocks[1]


def row_logical(L, axis, index, kind):
    """An explicit minimum-weight logical operator, as a sorted index list.

    ``axis=0`` takes a full row of qubits, ``axis=1`` a full column; either
    winds around the torus once, so it commutes with every check (each check
    meets it in 0 or 2 qubits) and is not a product of checks. ``kind="Z"``
    gives the operator acting as Z on those qubits and ``kind="X"`` as X --
    the two are the two independent logicals of the code.
    """
    q = []
    for t in range(L):
        i, j = (index, t) if axis == 0 else (t, index)
        q.append((i % L) * L + (j % L))
    assert len(set(q)) == L, "row/column must be L distinct qubits"
    return sorted(q)


def planar_coordinates(L):
    """One (x, y) per qubit on the unit grid, for the submission's layout."""
    return [[float(q % L), float(q // L)] for q in range(L * L)]

"""Shared CSS / GF(2) helpers for the research starter kit.

A thin layer over the verifier's own audited GF(2) core (``verify/gf2.py``),
so the construction tools and the verifier share a single source of truth for
linear algebra. Everything here operates on CSS parity-check matrices given as
``int`` arrays of shape ``(num_checks, n)``; ``-1`` and ``1`` are identified
(arithmetic is mod 2 throughout).
"""

import os
import sys

import numpy as np

# Reuse the verifier's GF(2) routines rather than re-implementing them: the
# construction side and the checking side then agree by construction.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "verify"))
import gf2  # noqa: E402

# Re-export the primitives the construction/screening tools build on.
rref = gf2.rref
rank = gf2.rank
kernel_basis = gf2.kernel_basis
logical_basis = gf2.logical_basis
commutes = gf2.commutes
in_rowspace = gf2.in_rowspace


def verify_css(HX, HZ):
    """CSS commutation: ``H_X H_Z^T = 0`` over GF(2). Returns ``bool``."""
    HX = np.asarray(HX, dtype=np.int64) % 2
    HZ = np.asarray(HZ, dtype=np.int64) % 2
    return not bool(((HX @ HZ.T) % 2).any())


def compute_k(HX, HZ):
    """Logical qubit count ``k = n - rank(H_X) - rank(H_Z)`` over GF(2).

    This is exactly the quantity the verifier recomputes from a submission, so
    a code whose ``k`` you read here is the ``k`` the board will record.
    """
    HX = np.asarray(HX) % 2
    HZ = np.asarray(HZ) % 2
    n = HX.shape[1]
    return int(n - rank(HX) - rank(HZ))

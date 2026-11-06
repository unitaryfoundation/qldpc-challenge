"""Regression tests for research/kit/tensor_network.py (arXiv:2009.10329).

The module rebuilds the tensor-network codes of the paper from the SWO08
``[[6,1,3]]`` block of Table 1, gluing code tensors by contracting one index
of each (Theorem 1).

What is checked here:

* the 6-qubit block is a valid stabilizer code: its five generators commute,
  they are independent, and it encodes one logical qubit;
* the block is *not* CSS (it contains ``Y``), which is the reason the family
  cannot be submitted to the board's CSS track;
* the glued ``[[11,1,3]]`` code has the paper's block count and dimension;
* the 7-qubit state of the paper is not an abelian stabilizer group as
  literally described (the two logicals anticommute on the extra qubit), so
  the module says so rather than claiming a stabilizer code it does not have.

Run: uv run pytest research/test_tensor_network.py
"""

import itertools
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "kit"))

import numpy as np
import tensor_network as tn
from tensor_network import (eleven_qubit_code, is_abelian, is_css,
                             seven_qubit_state_code, swo08_code)


def _commutes(u, v):
    n = u.size // 2
    return int((u[:n] * v[n:]).sum() + (u[n:] * v[:n]).sum()) % 2 == 0


def test_swo08_block_is_a_valid_stabilizer_code():
    code = swo08_code()
    vecs = [tn.sym_to_xz(g) for g in code["stabilizers"]]
    for u, v in itertools.combinations(vecs, 2):
        assert _commutes(u, v), "the five generators must commute"
    basis = tn._rref(vecs, 2 * code["n"])
    assert basis.shape[0] == 5
    assert code["n"] - basis.shape[0] == 1


def test_swo08_block_is_not_css():
    """The board takes CSS codes only, and this block has Y in it."""
    assert not is_css(swo08_code())


def test_seven_qubit_state_is_not_abelian_as_printed():
    """The paper's seven operators for the 7-qubit state do not commute: the
    two logicals anticommute on the extra qubit 0.  The module reports this
    rather than pretending the family is a stabilizer code."""
    assert not is_abelian(seven_qubit_state_code())


def test_eleven_qubit_glue_has_the_papers_block_count():
    code = eleven_qubit_code()
    assert code["n"] == 11
    vecs = [tn.sym_to_xz(g) for g in code["stabilizers"]]
    basis = tn._rref(vecs, 2 * code["n"])
    assert basis.shape[0] == 10
    assert code["n"] - basis.shape[0] == 1

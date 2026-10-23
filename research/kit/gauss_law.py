r"""Gauss's-law quantum codes -- arXiv:2608.00165 (Rajput, Roggero, Wiebe et al.).

The construction has two halves.

*Classical Gauss's law code* (Definition III.1 / Lemma III.2).  A periodic
hypercubic lattice ``Lambda`` with sites ``S_n`` and links ``L_{n,mu}``.  Every
lattice variable is duplicated ``p_n`` (site) or ``q_{n,mu}`` (link) times.
The code is the set of bit assignments obeying, for every vertex, the
homogeneous constraints

    S^{(1)}_n + sum_mu ( L^{(1)}_{n,mu} + L^{(1)}_{n-mu_hat,mu} ) = 0      (III.17)
    S^{(a)}_n + S^{(a')}_n = 0                                             (III.18)
    L^{(b)}_{n,mu} + L^{(b')}_{n,mu} = 0                                   (III.19)

i.e. one Gauss's-law equation per site on the representative copies, plus
"all copies of a variable are equal" equations.  The number of logical bits
is ``D*N`` (one per link), the distance is the minimum weight of a gauge
invariant flux string (open string: two endpoint sites plus the links on the
path; closed string: the links on the loop).

*Quantum Gauss's law code* (Definition III.4).  Concatenate the classical
code above with a classical inner code ``C_in = [d,1,d]`` (the repetition
code) that handles phase flips.  The inner generators become X-type stabilizers
of weight 2 per block; each outer check of weight ``w`` becomes a Z-type
stabilizer of weight ``w*d`` (Z on every inner qubit of every block it
touches).  The result is a CSS code with

    n = n_out * d,   k = k_out,   d = min(d_out, d_in)                    (III.45)

Optimal 1D choice (Theorem III.5): for distance ``d`` and ``N`` (even) sites,

    p_n = ceil((d-1)/2)   for n even,      ceil(d/2) - 1   for n odd
    q_n = 1

which gives the optimal 1D quantum Gauss's law code [[N d(d+1)/2, N, d]].

Everything here is a plain NumPy construction; the distance claim of the
paper is not reproduced by this module (the trusted gate measures it).
"""
import numpy as np


# ----------------------------------------------------------------------
#  Classical Gauss's law code
# ----------------------------------------------------------------------
def _bit_index_1d(N, p, q):
    """Index the classical bits of the 1D periodic lattice.

    Sites S_n (n = 0..N-1) with p[n] copies, then links L_n (n = 0..N-1,
    L_n joins site n and site n+1) with q[n] copies.  Returns
    ``(site_idx, link_idx, n_bits)`` where ``site_idx[n][a]`` and
    ``link_idx[n][b]`` are bit positions.
    """
    site_idx, link_idx, pos = [], [], 0
    for n in range(N):
        row = list(range(pos, pos + p[n]))
        site_idx.append(row)
        pos += p[n]
    for n in range(N):
        row = list(range(pos, pos + q[n]))
        link_idx.append(row)
        pos += q[n]
    return site_idx, link_idx, pos


def classical_gauss_law_1d(N, p, q):
    """Parity-check matrix of the 1D classical Gauss's law code.

    ``p``, ``q`` are per-site / per-link duplication counts (lists of length
    ``N``).  Returns ``(H, site_idx, link_idx)`` with ``H`` of shape
    (rows, n_bits) over F2.
    """
    site_idx, link_idx, n_bits = _bit_index_1d(N, p, q)
    rows = []
    # (III.17): one Gauss's-law equation per site, on the representative copies.
    for n in range(N):
        r = np.zeros(n_bits, dtype=np.int8)
        r[site_idx[n][0]] ^= 1
        r[link_idx[n][0]] ^= 1
        r[link_idx[(n - 1) % N][0]] ^= 1
        rows.append(r)
    # (III.18): all copies of a site variable are equal.
    for n in range(N):
        for a in range(1, p[n]):
            r = np.zeros(n_bits, dtype=np.int8)
            r[site_idx[n][0]] ^= 1
            r[site_idx[n][a]] ^= 1
            rows.append(r)
    # (III.19): all copies of a link variable are equal.
    for n in range(N):
        for b in range(1, q[n]):
            r = np.zeros(n_bits, dtype=np.int8)
            r[link_idx[n][0]] ^= 1
            r[link_idx[n][b]] ^= 1
            rows.append(r)
    H = np.array(rows, dtype=np.int8) if rows else np.zeros((0, n_bits), dtype=np.int8)
    return H, site_idx, link_idx


def optimal_1d_multiplicities(N, d):
    """Theorem III.5: the duplication counts of the optimal 1D Gauss's law code."""
    if d < 3:
        raise ValueError("d must be >= 3")
    if N < d:
        raise ValueError("need N >= d")
    if N % 2 != 0:
        raise ValueError("N must be even (Theorem III.5 assumes it)")
    p = []
    for n in range(N):
        if n % 2 == 0:                       # n congruent 0 mod 2
            p.append(int(np.ceil((d - 1) / 2)))
        else:
            p.append(int(np.ceil(d / 2)) - 1)
    q = [1] * N
    return p, q


# ----------------------------------------------------------------------
#  Quantum Gauss's law code
# ----------------------------------------------------------------------
def quantum_gauss_law_1d(N, d, p=None, q=None):
    """The 1D quantum Gauss's law code of Definition III.4.

    Concatenates the classical Gauss's law code with ``C_in = [d,1,d]``.
    With ``p=None`` the optimal multiplicities of Theorem III.5 are used.

    Returns ``(HX, HZ)``: int8 CSS check matrices, ``n = n_out * d``.
    """
    if p is None or q is None:
        p, q = optimal_1d_multiplicities(N, d)
    HC, site_idx, link_idx = classical_gauss_law_1d(N, p, q)
    n_out = HC.shape[1]

    # Inner code C_in = [d,1,d]: the classical repetition code, whose
    # generators become X-type stabilizers of weight 2 per block.
    inner_rows = []
    for i in range(d - 1):
        r = np.zeros(d, dtype=np.int8)
        r[i] = 1
        r[i + 1] = 1
        inner_rows.append(r)

    # HX: one X-type stabilizer per (block, inner generator).
    hx_rows = []
    for v in range(n_out):
        for ir in inner_rows:
            r = np.zeros(n_out * d, dtype=np.int8)
            for j in range(d):
                if ir[j]:
                    r[v * d + j] = 1
            hx_rows.append(r)

    # HZ: each outer check of weight w becomes Z on all d inner qubits of
    # every block it touches.
    hz_rows = []
    for c in HC:
        blocks = np.nonzero(c)[0]
        r = np.zeros(n_out * d, dtype=np.int8)
        for b in blocks:
            r[b * d:(b + 1) * d] = 1
        hz_rows.append(r)

    HX = np.array(hx_rows, dtype=np.int8)
    HZ = np.array(hz_rows, dtype=np.int8)
    return HX, HZ


def quantum_gauss_law_1d_coordinates(N, d, p=None, q=None):
    """Physical-qubit coordinates for :func:`quantum_gauss_law_1d`.

    A 1D chain of ``N`` sites with the link ``L_n`` halfway between site
    ``n`` and site ``n+1``; the ``d`` inner qubits of a block sit at the same
    ``x`` and spread over ``y = 0..d-1``.  Returned as ``[[x, y], ...]``.
    """
    if p is None or q is None:
        p, q = optimal_1d_multiplicities(N, d)
    site_idx, link_idx, n_out = _bit_index_1d(N, p, q)
    # block order: sites first, then links (same as the bit indexing)
    block_x = []
    for n in range(N):
        block_x += [2 * n] * p[n]
    for n in range(N):
        block_x += [2 * n + 1] * q[n]
    coords = []
    for v in range(n_out):
        for j in range(d):
            coords.append([block_x[v], j])
    return coords


if __name__ == "__main__":
    from css import verify_css, compute_k
    for (N, d) in [(6, 3), (8, 4), (10, 5), (12, 6), (20, 8)]:
        HX, HZ = quantum_gauss_law_1d(N, d)
        p, q = optimal_1d_multiplicities(N, d)
        n_out = sum(p) + sum(q)
        print(f"N={N} d={d}: n={HX.shape[1]} (expect {N*d*(d+1)//2}) "
              f"k={compute_k(HX, HZ)} (expect {N}) "
              f"wX={int(HX.sum(1).max())} wZ={int(HZ.sum(1).max())} "
              f"css={verify_css(HX, HZ)}")

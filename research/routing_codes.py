"""Construct routing codes from arXiv:2606.25330v1 and prepare for submission.

Routing codes are CSS codes on a torus Z_l x Z_m built by qubit routing with
iSWAP gates. The construction uses:
  - Data qubits D = {(i,j) | i+j is even}
  - X-syndrome qubits X = {(i,j) | i is odd, j is even}
  - Z-syndrome qubits Z = {(i,j) | i is even, j is odd}
  - Routing vector sequences {v_t} and {w_t} that define stabilizer operators
"""
import numpy as np
import sys
import os

# Add paths for imports
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "kit"))
sys.path.insert(0, os.path.join(_HERE, "..", "verify"))

from css import compute_k, verify_css
from surrogate import distance_rand, lightest_logical
from submit import make_submission, save_submission, validate


def _mod_add(a, b, l, m):
    """Add vectors mod (l, m)."""
    return ((a[0] + b[0]) % l, (a[1] + b[1]) % m)


def _mod_sub(a, b, l, m):
    """Subtract vectors mod (l, m)."""
    return ((a[0] - b[0]) % l, (a[1] - b[1]) % m)


def _site_type(i, j):
    """Return site type: 'D' (data), 'X' (X-syndrome), 'Z' (Z-syndrome)."""
    s = (i + j) % 2
    if s == 0:
        return 'D'
    elif i % 2 == 1:  # i odd, j even (since i+j is odd)
        return 'X'
    else:  # i even, j odd
        return 'Z'


def _site_index(i, j, l, m, site_type):
    """Return the index of site (i,j) in the list of its type."""
    if site_type == 'D':
        # Data qubits: i+j even, indexed by position
        count = 0
        for ii in range(l):
            for jj in range(m):
                if (ii + jj) % 2 == 0:
                    if (ii, jj) == (i, j):
                        return count
                    count += 1
    elif site_type == 'X':
        # X-syndrome: i odd, j even
        count = 0
        for ii in range(l):
            for jj in range(m):
                if ii % 2 == 1 and jj % 2 == 0:
                    if (ii, jj) == (i, j):
                        return count
                    count += 1
    elif site_type == 'Z':
        # Z-syndrome: i even, j odd
        count = 0
        for ii in range(l):
            for jj in range(m):
                if ii % 2 == 0 and jj % 2 == 1:
                    if (ii, jj) == (i, j):
                        return count
                    count += 1
    return -1


def _compute_permutation(positions, v_t, l, m):
    """Apply one routing step: sigma_t to all positions.
    
    sigma_t(u) = u + v_t if u in X
                 u + w_t if u in Z
                 u - v_t if u in D and u - v_t in X
                 u - w_t if u in D and u - w_t in Z
    """
    new_positions = {}
    v = tuple(v_t)
    
    for pos, stype in positions.items():
        if stype == 'X':
            new_pos = _mod_add(pos, v, l, m)
            new_positions[new_pos] = stype
        elif stype == 'Z':
            new_pos = _mod_add(pos, v, l, m)
            new_positions[new_pos] = stype
        elif stype == 'D':
            # Check if pos - v is in X
            prev_x = _mod_sub(pos, v, l, m)
            prev_z = _mod_sub(pos, v, l, m)
            if _site_type(*prev_x) == 'X':
                new_positions[pos] = stype
            elif _site_type(*prev_z) == 'Z':
                new_positions[pos] = stype
            else:
                new_positions[pos] = stype
    
    return new_positions


def build_routing_code(l, m, routing_vectors):
    """Build a routing code on torus Z_l x Z_m.
    
    Parameters
    ----------
    l, m : int
        Torus dimensions (both must be even)
    routing_vectors : list of (vx, vy)
        Sequence of routing vectors. For time-reversal symmetric construction,
        the Z routing is the reverse of this sequence.
    
    Returns
    -------
    HX, HZ : ndarray
        Parity check matrices
    """
    T = len(routing_vectors)
    
    # Create initial positions
    positions = {}
    for i in range(l):
        for j in range(m):
            stype = _site_type(i, j)
            if stype in ('X', 'Z', 'D'):
                positions[(i, j)] = stype
    
    # Count qubits
    n_data = sum(1 for p, s in positions.items() if s == 'D')
    n_x = sum(1 for p, s in positions.items() if s == 'X')
    n_z = sum(1 for p, s in positions.items() if s == 'Z')
    n = n_data + n_x + n_z
    
    print(f"Torus {l}x{m}: n={n} (data={n_data}, X-syn={n_x}, Z-syn={n_z})")
    
    # Build index maps
    data_indices = {}
    x_indices = {}
    z_indices = {}
    
    d_count = x_count = z_count = 0
    for i in range(l):
        for j in range(m):
            stype = _site_type(i, j)
            if stype == 'D':
                data_indices[(i, j)] = d_count
                d_count += 1
            elif stype == 'X':
                x_indices[(i, j)] = x_count
                x_count += 1
            elif stype == 'Z':
                z_indices[(i, j)] = z_count
                z_count += 1
    
    # Build stabilizer polynomials by applying routing
    # For X-syndrome: start at position x, apply sigma_1, sigma_2, ..., sigma_T
    # The visited data qubits form the X-check
    
    # X-checks (for Z-stabilizers)
    HX_rows = []
    # Z-checks (for X-stabilizers)  
    HZ_rows = []
    
    # For each X-syndrome qubit position
    for x_pos in x_indices:
        # Simulate routing: X-syndrome qubit at x_pos follows routing_vectors
        current = x_pos
        visited_data = set()
        
        for t, v in enumerate(routing_vectors):
            # At step t, syndrome qubit moves to current + v
            next_pos = _mod_add(current, v, l, m)
            # The data qubit at next_pos gets swapped
            if _site_type(*next_pos) == 'D':
                visited_data.add(next_pos)
            current = next_pos
        
        # Build the check: syndrome qubit at x_pos checks all visited data qubits
        # After all translations by even-even vectors, this generates HX
        for di in range(0, l, 2):
            for dj in range(0, m, 2):
                row = np.zeros(n, dtype=np.int8)
                # The syndrome qubit position (translated)
                synd_pos = ((x_pos[0] + di) % l, (x_pos[1] + dj) % m)
                synd_idx = x_indices.get(synd_pos, -1)
                if synd_idx >= 0:
                    row[n_data + synd_idx] = 1
                
                # Visited data qubits (translated)
                for d_pos in visited_data:
                    trans_d = ((d_pos[0] + di) % l, (d_pos[1] + dj) % m)
                    d_idx = data_indices.get(trans_d, -1)
                    if d_idx >= 0:
                        row[d_idx] = 1
                
                HX_rows.append(row)
    
    # For Z-syndrome qubits (time-reversed routing)
    for z_pos in z_indices:
        current = z_pos
        visited_data = set()
        
        for t, v in enumerate(reversed(routing_vectors)):
            next_pos = _mod_add(current, v, l, m)
            if _site_type(*next_pos) == 'D':
                visited_data.add(next_pos)
            current = next_pos
        
        for di in range(0, l, 2):
            for dj in range(0, m, 2):
                row = np.zeros(n, dtype=np.int8)
                synd_pos = ((z_pos[0] + di) % l, (z_pos[1] + dj) % m)
                synd_idx = z_indices.get(synd_pos, -1)
                if synd_idx >= 0:
                    row[n_data + n_x + synd_idx] = 1
                
                for d_pos in visited_data:
                    trans_d = ((d_pos[0] + di) % l, (d_pos[1] + dj) % m)
                    d_idx = data_indices.get(trans_d, -1)
                    if d_idx >= 0:
                        row[d_idx] = 1
                
                HZ_rows.append(row)
    
    HX = np.array(HX_rows, dtype=np.int8) if HX_rows else np.zeros((0, n), dtype=np.int8)
    HZ = np.array(HZ_rows, dtype=np.int8) if HZ_rows else np.zeros((0, n), dtype=np.int8)
    
    return HX, HZ


def _apply_sigma(pos, v, l, m):
    """Apply one routing step sigma_t to a lattice position.
    
    sigma_t(r) = r + v_t if r is X-syndrome position
                  r + v_t if r is Z-syndrome position
                  r - v_t if r is D position and r - v_t is X or Z
                  r otherwise (stays in place)
    """
    stype = _site_type(pos[0], pos[1])
    if stype in ('X', 'Z'):
        return _mod_add(pos, v, l, m)
    elif stype == 'D':
        prev = _mod_sub(pos, v, l, m)
        if _site_type(prev[0], prev[1]) in ('X', 'Z'):
            return prev
    return pos


def _compute_stabilizer_positions(x, v_sequence, l, m):
    """Compute the stabilizer data-qubit positions for a syndrome at position x.
    
    Uses the palindromic composition from equation (3) of the paper:
    q_{x,t} = (sigma_1 o ... o sigma_t o ... o sigma_1)(x)
    """
    T = len(v_sequence)
    # Compute the syndrome path: x(t) = sigma_t(x(t-1))
    x_path = [x]
    current = x
    for t in range(T):
        current = _apply_sigma(current, v_sequence[t], l, m)
        x_path.append(current)
    
    # For each t, q_{x,t} = (sigma_1 o sigma_2 o ... o sigma_{t-1} o sigma_t o
    #                         sigma_{t-1} o ... o sigma_1)(x)   [paper eq. (3)]
    # After the forward leg reaches x(t) = x_path[t], the backward leg must
    # apply sigma_{t-1}, sigma_{t-2}, ..., sigma_1 in DESCENDING index order
    # (each sigma_i is its own inverse). The previous ascending-order loop
    # here was the bug that produced CSS=False / k=0 / weight=5 results.
    positions = []
    for t in range(1, T + 1):
        pos = x_path[t]
        for i in range(t - 2, -1, -1):
            pos = _apply_sigma(pos, v_sequence[i], l, m)
        positions.append(pos)
    
    return positions


def build_routing_code_v2(l, m, v_sequence, w_sequence):
    """Build routing code with explicit X and Z routing sequences.
    
    This implements the construction from Proposition 2 in the paper:
    - X-syndrome qubits follow v_sequence
    - Z-syndrome qubits follow w_sequence
    - Commutativity is guaranteed if v_sequence = w_sequence (time-reversed)
    
    Physical qubits are only the data qubits (n = lm/2).
    Syndrome qubits are ancillas used for measurement, not counted in n.
    """
    T = len(v_sequence)
    
    # Build index maps for data qubits only (physical qubits)
    data_indices = {}
    d_count = 0
    
    for i in range(l):
        for j in range(m):
            stype = _site_type(i, j)
            if stype == 'D':
                data_indices[(i, j)] = d_count
                d_count += 1
    
    n = d_count  # number of data qubits = physical qubits
    
    # Build X-syndrome positions (for generating checks)
    x_positions = []
    for i in range(l):
        for j in range(m):
            if _site_type(i, j) == 'X':
                x_positions.append((i, j))
    
    # Build Z-syndrome positions
    z_positions = []
    for i in range(l):
        for j in range(m):
            if _site_type(i, j) == 'Z':
                z_positions.append((i, j))
    
    print(f"Torus {l}x{m}: n={n} data qubits, {len(x_positions)} X-checks, {len(z_positions)} Z-checks")
    
    # Build X-checks: ONE representative X-syndrome qubit and its translations
    x_rep = x_positions[0]
    v_stab = _compute_stabilizer_positions(x_rep, v_sequence, l, m)
    
    HX_list = []
    for di in range(0, l, 2):
        for dj in range(0, m, 2):
            row = np.zeros(n, dtype=np.int8)
            for pos in v_stab:
                d_pos = ((pos[0] + di) % l, (pos[1] + dj) % m)
                if d_pos in data_indices:
                    row[data_indices[d_pos]] = 1
            HX_list.append(row)
    
    # Build Z-checks: ONE representative Z-syndrome qubit and its translations
    z_rep = z_positions[0]
    w_stab = _compute_stabilizer_positions(z_rep, w_sequence, l, m)
    
    HZ_list = []
    for di in range(0, l, 2):
        for dj in range(0, m, 2):
            row = np.zeros(n, dtype=np.int8)
            for pos in w_stab:
                d_pos = ((pos[0] + di) % l, (pos[1] + dj) % m)
                if d_pos in data_indices:
                    row[data_indices[d_pos]] = 1
            HZ_list.append(row)
    
    HX = np.array(HX_list, dtype=np.int8) if HX_list else np.zeros((0, n), dtype=np.int8)
    HZ = np.array(HZ_list, dtype=np.int8) if HZ_list else np.zeros((0, n), dtype=np.int8)
    
    return HX, HZ


# Routing codes from Table 1 of arXiv:2606.25330v1
ROUTING_CODES_TABLE1 = [
    {
        "name": "[[54,8,6]]",
        "l": 18, "m": 6,
        "v": [(0,1), (1,0), (3,0), (0,1), (3,0), (1,0), (0,1)],
        "claimed_d": 6,
        "connectivity": 4,
    },
    {
        "name": "[[70,8,7]]",
        "l": 14, "m": 10,
        "v": [(1,0), (0,1), (0,1), (2,1), (0,1), (0,1), (1,0)],
        "claimed_d": 7,
        "connectivity": 4,
    },
    {
        "name": "[[80,8,8]]",
        "l": 16, "m": 10,
        "v": [(0,1), (1,0), (4,1), (0,1), (4,1), (1,0), (0,1)],
        "claimed_d": 8,
        "connectivity": 5,
    },
    {
        "name": "[[90,8,9]]",
        "l": 18, "m": 10,
        "v": [(0,1), (1,0), (4,1), (0,1), (4,1), (1,0), (0,1)],
        "claimed_d": 9,
        "connectivity": 5,
    },
    {
        "name": "[[100,8,10]]",
        "l": 20, "m": 10,
        "v": [(0,1), (1,0), (2,1), (0,1), (2,1), (1,0), (0,1)],
        "claimed_d": 10,
        "connectivity": 4,
    },
    {
        "name": "[[110,8,11]]",
        "l": 22, "m": 10,
        "v": [(0,1), (1,0), (6,1), (0,1), (6,1), (1,0), (0,1)],
        "claimed_d": 11,
        "connectivity": 5,
    },
    {
        "name": "[[140,8,12]]",
        "l": 28, "m": 10,
        "v": [(0,1), (1,0), (2,1), (0,1), (2,1), (1,0), (0,1)],
        "claimed_d": 12,
        "connectivity": 4,
    },
]


# Strong candidates from Supplemental (d > 12, high score)
ROUTING_CODES_SUPP_STRONG = [
    {
        "name": "[[160,8,14]]",
        "l": 32, "m": 10,
        "v": [(0,1), (1,0), (2,1), (0,1), (2,1), (1,0), (0,1)],
        "claimed_d": 14,
        "connectivity": 4,
    },
    {
        "name": "[[180,8,16]]",
        "l": 36, "m": 10,
        "v": [(0,1), (1,0), (4,1), (0,1), (4,1), (1,0), (0,1)],
        "claimed_d": 16,
        "connectivity": 5,
    },
    {
        "name": "[[200,8,18]]",
        "l": 40, "m": 10,
        "v": [(0,1), (1,0), (2,1), (0,1), (2,1), (1,0), (0,1)],
        "claimed_d": 18,
        "connectivity": 4,
    },
    {
        "name": "[[280,8,24]]",
        "l": 56, "m": 10,
        "v": [(0,1), (1,0), (2,1), (0,1), (2,1), (1,0), (0,1)],
        "claimed_d": 24,
        "connectivity": 4,
    },
    {
        "name": "[[240,16,16]]",
        "l": 48, "m": 10,
        "v": [(0,1), (1,0), (4,1), (0,1), (4,1), (1,0), (0,1)],
        "claimed_d": 16,
        "connectivity": 5,
    },
    {
        "name": "[[288,24,18]]",
        "l": 48, "m": 12,
        "v": [(0,1), (1,0), (4,1), (0,1), (4,1), (1,0), (0,1)],
        "claimed_d": 18,
        "connectivity": 5,
    },
]


def try_build_and_validate(code_spec, author="@mathysrennela"):
    """Try to build and validate a routing code."""
    l, m = code_spec["l"], code_spec["m"]
    v = code_spec["v"]
    name = code_spec["name"]
    
    print(f"\n{'='*60}")
    print(f"Building {name} (torus {l}x{m}, T={len(v)})")
    print(f"{'='*60}")
    
    try:
        # Build with time-reversal symmetric routing (w = reversed v)
        w = list(reversed(v))
        HX, HZ = build_routing_code_v2(l, m, v, w)
        
        n = HX.shape[1]
        k = compute_k(HX, HZ)
        
        print(f"  n={n}, k={k}, claimed d={code_spec['claimed_d']}")
        
        # Check CSS commutation
        if not verify_css(HX, HZ):
            print(f"  FAIL: CSS commutation failed")
            return None
        
        print(f"  CSS commutation: OK")
        print(f"  HX shape: {HX.shape}, HZ shape: {HZ.shape}")
        print(f"  Max check weight X: {np.max(np.sum(HX, axis=1))}")
        print(f"  Max check weight Z: {np.max(np.sum(HZ, axis=1))}")
        
        return HX, HZ
        
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    """Build and validate routing codes, save strong candidates."""
    author = "@mathysrennela"
    
    # Try all codes
    all_codes = ROUTING_CODES_TABLE1 + ROUTING_CODES_SUPP_STRONG
    
    results = []
    
    for code_spec in all_codes:
        result = try_build_and_validate(code_spec, author)
        if result is not None:
            HX, HZ = result
            results.append((code_spec, HX, HZ))
    
    print(f"\n{'='*60}")
    print(f"Successfully built {len(results)}/{len(all_codes)} codes")
    print(f"{'='*60}")
    
    return results


if __name__ == "__main__":
    results = main()

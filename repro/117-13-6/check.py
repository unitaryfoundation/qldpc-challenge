#!/usr/bin/env python3
"""Independent, standard-library-only finite certificate for the CSS117 code.

Rebuilds the polynomial lift and checks the supplied JSON without importing
repository validators, received scripts, NPZ data, or cached certificates.
This is a reproducibility proof, not a replacement for the official gate.
"""
import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
from math import comb
from pathlib import Path
import time


N, L = 117, 9
A = ((0, 0, 0), (0, 1, 3))  # Exponents: exponent 0 means polynomial 1.
B = ((0, 0, 0), (0, 1, 4))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def support(word):
    return [q for q in range(N) if word >> q & 1]


def basis(rows):
    """Echelon rows with exact coefficients in the supplied generating set."""
    pivots = {}
    for i, word in enumerate(rows):
        coefficient = 1 << i
        while word:
            p = word.bit_length() - 1
            if p in pivots:
                v, c = pivots[p]
                word ^= v
                coefficient ^= c
            else:
                pivots[p] = (word, coefficient)
                break
    return pivots


def reduce_word(word, pivots):
    coefficient = 0
    while word:
        p = word.bit_length() - 1
        if p not in pivots:
            break
        v, c = pivots[p]
        word ^= v
        coefficient ^= c
    return word, coefficient


def canonical_rows(rows):
    pivots = {p: v for p, (v, _) in basis(rows).items()}
    for p in sorted(pivots):
        for q in pivots:
            if q != p and pivots[q] >> p & 1:
                pivots[q] ^= pivots[p]
    return [pivots[p] for p in sorted(pivots)]


def lift():
    """HX=[A tensor I3 | I2 tensor B^T], HZ=[I3 tensor B | A^T tensor I2].

    A monomial x^s in X expands to P_s[t,u]=[u=t+s mod9].
    Z uses P_-s, implementing the reciprocal transpose over F2[x]/(x^9-1).
    """
    hx, hz = [], []
    for ar in range(2):
        for j in range(3):
            blocks = [(ac*3+j, A[ar][ac]) for ac in range(3)]
            blocks += [(9+ar*2+br, B[br][j]) for br in range(2)]
            for t in range(L):
                hx.append(sum(1 << (c*L+(t+s) % L) for c, s in blocks))
    for ac in range(3):
        for br in range(2):
            blocks = [(ac*3+j, B[br][j]) for j in range(3)]
            blocks += [(9+ar*2+br, A[ar][ac]) for ar in range(2)]
            for t in range(L):
                hz.append(sum(1 << (c*L+(t-s) % L) for c, s in blocks))
    return hx, hz


def parse_rows(supports, name):
    require(isinstance(supports, list), name+' must be a list')
    result = []
    for row in supports:
        require(isinstance(row, list), name+' row must be a list')
        require(all(type(q) is int and 0 <= q < N for q in row), name+' index outside 0..116')
        require(len(row) == len(set(row)), name+' duplicate qubit')
        result.append(sum(1 << q for q in row))
    return result


def component_sizes(rows):
    parent = list(range(N))

    def root(q):
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q

    for word in rows:
        s = support(word)
        for q in s[1:]:
            parent[root(q)] = root(s[0])
    return sorted(Counter(root(q) for q in range(N)).values(), reverse=True)


def resource(hx, hz):
    weights = [w.bit_count() for w in hx+hz]
    loads = [sum(w >> q & 1 for w in hx+hz) for q in range(N)]
    return {'n': N, 'rankX': len(basis(hx)), 'rankZ': len(basis(hz)),
            'k': N-len(basis(hx))-len(basis(hz)), 'max_weight': max(weights),
            'max_degree': max(loads), 'checks': len(hx)+len(hz),
            'incidences': sum(weights), 'degree_histogram': dict(sorted(Counter(loads).items()))}


def prove_side(side, opposite, own, full_own, witness_support):
    columns = [sum(((r >> q) & 1) << i for i, r in enumerate(opposite)) for q in range(N)]
    table = {0: 0}
    entries = [(columns[q], 1 << q) for q in range(N)]
    entries += [(columns[i] ^ columns[j], (1 << i) | (1 << j))
                for i, j in combinations(range(N), 2)]
    for syndrome, word in entries:
        require(syndrome not in table, side+': syndrome collision at weight <=2')
        table[syndrome] = word
    require(len(table) == 6904, side+': incomplete small-support table')
    # Any kernel word of weight <=4 would split into two supports of size <=2.
    # Every weight5 kernel word has a disjoint 3+2 split, found below.
    words = Counter()
    for i, j, k in combinations(range(N), 3):
        syndrome = columns[i] ^ columns[j] ^ columns[k]
        if syndrome in table:
            word = (1 << i) ^ (1 << j) ^ (1 << k) ^ table[syndrome]
            require(word.bit_count() == 5, side+': unexpected lower-weight kernel word')
            words[word] += 1
    require(len(words) == 54 and set(words) == set(full_own), side+': weight5 set differs from reconstructed checks')
    require(set(words.values()) == {10}, side+': missing a 3+2 split')
    pivots = basis(own)
    boundaries = []
    for word in sorted(words):
        remainder, coefficient = reduce_word(word, pivots)
        require(remainder == 0, side+': weight5 logical counterexample')
        indices = [i for i in range(len(own)) if coefficient >> i & 1]
        rebuilt = 0
        for i in indices:
            rebuilt ^= own[i]
        require(rebuilt == word, side+': invalid boundary coefficients')
        boundaries.append({'support': support(word), 'check_indices': indices})
    witness = parse_rows([witness_support], side+' witness')[0]
    require(witness.bit_count() == 6, side+': expected weight6 witness')
    require(all((witness & row).bit_count() % 2 == 0 for row in opposite), side+': nonzero witness syndrome')
    require(reduce_word(witness, pivots)[0] != 0, side+': trivial witness')
    require(len(basis(own+[witness])) == 53, side+': wrong witness augmented rank')
    return {'small_support_count': len(table), 'small_syndromes_distinct': True,
            'triples_exhausted': comb(N, 3), 'triple_pair_hits': sum(words.values()),
            'kernel_words_weight1_to4': 0, 'kernel_words_weight5': len(words),
            'weight5_boundaries': boundaries, 'witness_support': witness_support,
            'witness_weight': 6, 'witness_augmented_rank': 53,
            'proved_pure_distance': 6}


def check(path):
    started = time.process_time()
    raw = path.read_bytes()
    doc = json.loads(raw)
    require(doc.get('code_type') == 'CSS' and doc.get('n') == N and doc.get('k') == 13,
            'expected CSS n117 k13')
    fullx, fullz = lift()
    hx, hz = [parse_rows(doc['checks'][side], side) for side in ('X', 'Z')]
    for side, full, given in [('X', fullx, hx), ('Z', fullz, hz)]:
        require(len(basis(full)) == len(basis(given)) == len(basis(full+given)) == 52,
                side+': supplied group differs from polynomial reconstruction')
    require(all((x & z).bit_count() % 2 == 0 for x in hx for z in hz), 'checks do not commute')
    resources = resource(hx, hz)
    require((resources['max_weight'], resources['max_degree'], resources['checks'], resources['incidences'])
            == (5, 6, 104, 520), 'unexpected supplied generator resources')
    tanner = component_sizes(hx+hz)
    group = component_sizes(canonical_rows(hx)+canonical_rows(hz))
    require(tanner == group == [N], 'disconnected Tanner graph or stabilizer group')
    require(doc['distance']['d'] == 6, 'JSON distance declaration is not6')
    finite = {}
    for side, opposite, own, full in [('X', hz, hx, fullx), ('Z', hx, hz, fullz)]:
        require(doc['distance'][side]['value'] == 6, side+': JSON side value is not6')
        require(doc['distance'][side]['confidence'] == 'upper_bound', side+': expected unchanged upper_bound schema label')
        finite[side] = prove_side(side, opposite, own, full, doc['distance'][side]['witness'])
    preferred_x = [w for i, w in enumerate(fullx) if i not in (44, 53)]
    preferred_z = [w for i, w in enumerate(fullz) if i not in (35, 53)]
    return {'status': 'passed', 'checker': 'independent standard-library finite proof v1',
            'input_name': path.name, 'input_sha256': sha256(raw).hexdigest(),
            'recipe': {'ring': 'F2[x]/(x^9-1)', 'A_exponents': A, 'B_exponents': B,
                       'X_shift_sign': 1, 'Z_shift_sign': -1},
            'same_reconstructed_stabilizer_group': True,
            'matches_prescribed_row_deletions_entrywise': hx == preferred_x and hz == preferred_z,
            'commutes': True, 'resources': resources,
            'tanner_qubit_component_sizes': tanner, 'rowspace_qubit_component_sizes': group,
            'finite_certificate': finite, 'local_proved_distance': 6,
            'schema_distance_confidence_unchanged': 'upper_bound',
            'official_gate_run_by_this_checker': False, 'randomized_logical_trials': 0,
            'cpu_seconds': time.process_time()-started}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[2]/'codes/117-13-6.json')
    parser.add_argument('--output', type=Path, help='Optional JSON proof receipt; input is never modified')
    args = parser.parse_args()
    receipt = check(args.candidate)
    encoded = json.dumps(receipt, indent=2)+'\n'
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end='')


if __name__ == '__main__':
    main()

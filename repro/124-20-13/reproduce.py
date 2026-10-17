#!/usr/bin/env python3
"""Portable standard-library GF4 binding; --full additionally runs exact MITM.

Does not import repository or received-package Python, change candidate metadata,
run a submission gate, or execute unrelated experiments.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
ORIGINAL_SHA = '748df148634412298876764cf231e70619c751148ac9225fe5872f135f0413ee'
SORTED_SHA = '87c3d881051f044ba8c5c15287aca06b58dbfdf58d20a0a0e524d8795b357510'
COLUMN_SHA = {'X': '6c8a38e4e59e6d5edaddd9d8122f7f21306529af833096e9ff4e933065bbfa21',
              'Z': 'c1a3e9e558b6fcb24803c903b6c5987d5b11304c4c4550b154c8bbf75b7b7359'}
F = {0: 3, 1: 2, 3: 1, 8: 2, 11: 3}
G = {0: 3, 1: 1, 4: 1, 12: 2, 13: 3}
COUNTS = [math.comb(124, w)//31 for w in range(1, 7)]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n')

def multiply(a, b):
    value = 0
    for j in range(2):
        if (b >> j) & 1:
            value ^= a << j
    return value ^ 7 if value & 4 else value

def columns(first, second, transpose=False):
    result = []
    for poly in (first, second):
        for j in range(31):
            for bit in range(2):
                result.append(sum(multiply(poly.get(((j-i) if transpose else (i-j)) % 31, 0), 1 << bit) << (2*i)
                                  for i in range(31)))
    return result

def rows(cs):
    return [sum(((c >> i) & 1) << j for j, c in enumerate(cs)) for i in range(62)]

def basis(words):
    result = {}
    for word in words:
        while word:
            pivot = word.bit_length()-1
            if pivot not in result:
                result[pivot] = word
                break
            word ^= result[pivot]
    return result

def word(support):
    require(isinstance(support, list) and all(type(q) is int and 0 <= q < 124 for q in support), 'Invalid support coordinates')
    require(len(set(support)) == len(support), 'Duplicate support coordinates')
    return sum(1 << q for q in support)

def permute_row(row, permutation):
    return sum(((row >> old) & 1) << new for new, old in enumerate(permutation))

def bind(candidate, output):
    doc = json.loads(candidate.read_text())
    require(doc['n'] == 124 and doc['k'] == 20, 'Expected n=124,k=20')
    cs = {'X': columns(F, G), 'Z': columns(G, F, True)}
    raw = {s: rows(cs[s]) for s in ('X', 'Z')}
    require(all((x & z).bit_count() % 2 == 0 for x in raw['X'] for z in raw['Z']), 'Raw matrices do not commute')
    actual = {s: [word(v) for v in doc['checks'][s]] for s in ('X', 'Z')}
    report = {'candidate_file': candidate.name, 'candidate_sha256': sha(candidate),
              'original_optimized_reference_sha256': ORIGINAL_SHA, 'n': 124, 'k': 20,
              'recipe': {'field_modulus': 'omega^2+omega+1', 'm': 31, 'f_nonzero': F, 'g_nonzero': G,
                         'physical_coordinate': 'block*62 + 2*j + bit; block=0,1; j=0..30; bit=0,1'},
              'same_group': {}, 'witnesses': {}, 'column_files': {},
              'candidate_distance_metadata_unchanged': True, 'full_exhaustive_run': False}
    for s in ('X', 'Z'):
        ranks = [len(basis(actual[s])), len(basis(raw[s])), len(basis(actual[s]+raw[s]))]
        require(ranks == [52, 52, 52], f'{s} input is not the reconstructed stabilizer space')
        report['same_group'][s] = {'actual_raw_stacked_ranks': ranks}
        ws = doc['distance'][s]
        v = word(ws['witness'])
        require(ws['value'] == v.bit_count() == 13, f'{s} needs a weight13 upper witness')
        opposite = 'Z' if s == 'X' else 'X'
        require(all((v & check).bit_count() % 2 == 0 for check in raw[opposite]), f'{s} witness has syndrome')
        require(len(basis(actual[s]+[v])) == 53, f'{s} witness is a stabilizer')
        report['witnesses'][s] = {'support': ws['witness'], 'weight': 13, 'zero_syndrome': True, 'augmented_rank': 53}
    rev = [2*((-j) % 31)+b for j in range(31) for b in range(2)]
    permutation = [62+r for r in rev]+rev
    for s, other in [('X', 'Z'), ('Z', 'X')]:
        require([permute_row(row, permutation) for row in raw[s]] == [raw[other][r] for r in rev], 'Exact duality identity failed')
    report['duality_entrywise'] = True
    mapping = [62*(t//2)+2*j+t % 2 for t in range(4) for j in range(31)]
    mask = (1 << 62)-1
    for s in ('X', 'Z'):
        tm = [cs[s][j] for j in mapping]
        require(all(tm[31*t+(j+1) % 31] == ((tm[31*t+j] << 2) & mask) | (tm[31*t+j] >> 60)
                    for t in range(4) for j in range(31)), f'{s} cyclic syndrome alignment failed')
        path = output/f'{s}-columns.txt'
        path.write_text(''.join(str(c)+'\n' for c in tm))
        require(sha(path) == COLUMN_SHA[s], f'{s} independently generated columns changed')
        report['column_files'][s] = {'file': path.name, 'sha256': sha(path), 'j_plus_1_syndrome_action': 'left rotate by2 among62 bits'}
    all_rows = actual['X']+actual['Z']
    degrees = [sum((r >> q) & 1 for r in all_rows) for q in range(124)]
    report['resources'] = {'w': max(r.bit_count() for r in all_rows), 'degree': max(degrees),
                           'M': len(all_rows), 'I': sum(degrees)}
    report['expected_nonempty_orbits_per_weight'] = COUNTS
    report['expected_nonempty_orbits'] = sum(COUNTS)
    dump(output/'binding.json', report)
    return report

def child_cpu():
    r = resource.getrusage(resource.RUSAGE_CHILDREN)
    return r.ru_utime+r.ru_stime

def run_logged(argv, output, label, timeout):
    before, start = child_cpu(), time.monotonic()
    proc = subprocess.run(list(map(str, argv)), text=True, capture_output=True, timeout=timeout, check=False)
    (output/f'{label}.stdout').write_text(proc.stdout)
    (output/f'{label}.stderr').write_text(proc.stderr)
    receipt = {'returncode': proc.returncode, 'wall_seconds': time.monotonic()-start, 'child_cpu_seconds': child_cpu()-before}
    dump(output/f'{label}.receipt.json', receipt)
    require(proc.returncode == 0, f'{label} failed; inspect its saved stdout/stderr')
    return proc.stdout, receipt

def full(output, report, cxx, timeout):
    require(sys.byteorder == 'little', 'Full replay currently requires a little-endian host for the raw key-file SHA')
    source_names = ['orbit_mitm.cpp', 'independent_orbit_check.cpp', 'check_sorted_keys.cpp']
    with tempfile.TemporaryDirectory(prefix='gf4-full-', dir=output) as tmp:
        work = Path(tmp)
        for name in source_names:
            run_logged([cxx, '-O3', '-std=c++17', '-Wall', '-Wextra', HERE/name, '-o', work/Path(name).stem], output, 'compile-'+Path(name).stem, timeout)
        primary, ptime = run_logged([work/'orbit_mitm', output/'X-columns.txt', work/'orbit6', '6'], output, 'primary-full', timeout)
        # Never use the primary exit status alone: it returns0 even on collisions.
        for suffix in ('duplicates.txt', 'exceptions.jsonl'):
            shutil.copyfile(work/f'orbit6_{suffix}', output/f'primary-{suffix}')
        a = [json.loads(line) for line in primary.splitlines()]
        require([r['representatives'] for r in a if r.get('stage') == 'enumerate'] == COUNTS, 'Primary coverage count mismatch')
        final = a[-1]
        require(final.get('stage') == 'complete' and final['keys'] == sum(COUNTS), 'Incomplete primary run')
        require(final['duplicate_groups'] == final['duplicate_pairs'] == final['exceptional_fixed_syndromes'] == 0, 'Primary found a collision or fixed syndrome')
        independent, itime = run_logged([work/'independent_orbit_check', output/'Z-columns.txt', '6'], output, 'independent-full', timeout)
        b = [json.loads(line) for line in independent.splitlines()]
        require([r['actual'] for r in b if 'weight' in r] == COUNTS, 'Independent coverage count mismatch')
        require(b[-1].get('completed') and b[-1]['entries'] == sum(COUNTS) and b[-1]['distinct_orbit_syndrome_collisions'] == b[-1]['fixed_syndromes'] == 0, 'Independent certificate failed')
        keyfile = work/'orbit6_sorted_keys.bin'
        require(keyfile.stat().st_size == 8*sum(COUNTS), 'Wrong sorted-key byte length')
        keys_sha = sha(keyfile)
        require(keys_sha == SORTED_SHA, 'Sorted exact-key SHA mismatch')
        checked, _ = run_logged([work/'check_sorted_keys', keyfile], output, 'sorted-key-check', timeout)
        key_check = json.loads(checked)
        result = {'complete': True, 'candidate_sha256': report['candidate_sha256'],
                  'source_sha256': {name: sha(HERE/name) for name in source_names},
                  'nonempty_half_support_orbits': sum(COUNTS), 'primary_terminal': final, 'independent_terminal': b[-1],
                  'sorted_key_stream_check': key_check, 'sorted_key_sha256': keys_sha,
                  'sorted_key_bytes': keyfile.stat().st_size, 'large_key_file_retained': False,
                  'primary_timing': ptime, 'independent_timing': itime,
                  'local_mathematical_distance': {'dX': 13, 'dZ': 13, 'd': 13},
                  'scope': 'This bound physical stabilizer group and equivalent generator presentations. Local exhaustive result, not an official server exact badge or a novelty claim. Candidate JSON metadata is unchanged.'}
        dump(output/'full-result.json', result)
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('candidate', type=Path, help='e.g. codes/124-20-13.json')
    ap.add_argument('--output', type=Path, default=HERE/'results')
    ap.add_argument('--full', action='store_true', help='Compile and run both full151623375-orbit enumerations, sequentially; approximately1.2GB RAM and1.3GB temporary disk')
    ap.add_argument('--cxx', default='g++')
    ap.add_argument('--timeout', type=int, default=600, help='Seconds allowed per compile/executable')
    args = ap.parse_args();candidate=args.candidate.resolve();output=args.output.resolve();output.mkdir(parents=True, exist_ok=True)
    original = candidate.read_bytes()
    report = bind(candidate, output)
    result = full(output, report, args.cxx, args.timeout) if args.full else report
    require(candidate.read_bytes() == original, 'Candidate changed during reproduction')
    print(json.dumps({'binding_passed': True, 'full_complete': bool(args.full), 'candidate_sha256': report['candidate_sha256'],
                      'resources': report['resources'], 'result_file': 'full-result.json' if args.full else 'binding.json'}, indent=2))

if __name__ == '__main__':
    main()

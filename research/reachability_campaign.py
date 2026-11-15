"""Reachability campaign: discover, stage, and track Pareto-optimal qLDPC codes.

Unified replacement for the two-step ``analyze4.py`` + ``route_a_recover.py``
workflow.  In a single pass over the CSS parents in ``codes/``:

  1. Run the code-calculus planner to derive child codes.
  2. Save each new (n, k, d) child as a full submission (matrices + parentage).
  3. Track reachable/results sets and an incremental Pareto frontier.
  4. Checkpoint after each chunk for crash recovery.

The script parallelises across parents (multiprocessing) and deduplicates by
(n, k, d_ub).  It requires the ``code-calculus`` repository (see the
CALCULUS env var) and the ``research`` extras (``uv run --extra research``).

Environment variables (all optional, sensible defaults):
  CH            repository root (default: parent of this script)
  CALCULUS      code-calculus repo (default: sibling ../code-calculus-dev)
  CKPT          checkpoint path (default: research/out/reachability_ckpt.json)
  OUT_REACH     reachable-n output (default: research/out/reachable_n.txt)
  OUT_BA        board-advancing output (default: research/out/board_advancing_n.txt)
  OUT_PARETO    Pareto frontier JSON (default: research/out/pareto_frontier.json)
  N_MAX         only process parents with n <= N_MAX (default: 1000)
  WORKERS       multiprocessing workers (default: 4)
  CHUNK_SIZE    parents per checkpoint (default: 25)
  TRIALS        witness-search trials per side (default: 1000)
  SKIP_DOMINATED  skip parents dominated by the board (default: 0)

Usage:
  uv run --extra research python -u research/reachability_campaign.py
  uv run --extra research python -u research/reachability_campaign.py --resume

Replaces analyze4.py + route_a_recover.py. In one pass over CSS parents:
  1. Run planner.plan to derive children.
  2. Save each new (n,k,d) child as a full submission (matrices + parentage).
  3. Track reachable/results sets and an incremental Pareto frontier.
  4. Checkpoint after each chunk for crash recovery.

Parallelizes across parents (multiprocessing). Dedups by (n,k,d_ub).

Usage:
    uv run --extra research python -u analyze_and_stage.py
    uv run --extra research python -u analyze_and_stage.py --resume
    N_MAX=400 WORKERS=4 uv run --extra research python -u analyze_and_stage.py
"""
import sys, json, glob, os, argparse, time
import multiprocessing as mp

# --- paths ---
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CH = os.environ.get('CH', REPO_ROOT)
CALCULUS = os.environ.get('CALCULUS', os.path.join(os.path.dirname(REPO_ROOT), 'code-calculus-dev'))
OUT_DIR = os.path.join(REPO_ROOT, 'research', 'out')
os.makedirs(OUT_DIR, exist_ok=True)
CKPT = os.environ.get('CKPT', os.path.join(OUT_DIR, 'reachability_ckpt.json'))
OUT_REACH = os.environ.get('OUT_REACH', os.path.join(OUT_DIR, 'reachable_n.txt'))
OUT_BA = os.environ.get('OUT_BA', os.path.join(OUT_DIR, 'board_advancing_n.txt'))
OUT_PARETO = os.environ.get('OUT_PARETO', os.path.join(OUT_DIR, 'pareto_frontier.json'))
N_MAX = int(os.environ.get('N_MAX', '1000'))
WORKERS = int(os.environ.get('WORKERS', '4'))
CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', '25'))
TRIALS = int(os.environ.get('TRIALS', '1000'))
SKIP_DOMINATED = os.environ.get('SKIP_DOMINATED', '0') == '1'

sys.path.insert(0, CALCULUS)
sys.path.insert(0, CH + '/research/kit')

# --- worker (runs in subprocess) ---
def _worker_init():
    sys.path.insert(0, CALCULUS)
    sys.path.insert(0, CH + '/research/kit')

def process_parent(args):
    """Process one parent. Returns (idx, parent_n, children_list, error)."""
    ppath, pdoc, missing_frozen, seen_frozen = args
    children = []
    error = None
    try:
        from machine.priced_calculus import CodeState, DistanceLedger
        from machine import planner
        st = CodeState.from_challenge(pdoc)
        led = DistanceLedger.from_challenge(st, pdoc, lower_bounds={})
        cands = planner.plan(st, led, target=1, reduce_by_domination=False,
                             structural=True, include_disconnected=False, reduce_display=True)
    except Exception as e:
        return {'ppath': ppath, 'parent_n': pdoc['n'], 'children': [], 'error': str(e)}
    missing = set(missing_frozen)
    seen = set(tuple(x) for x in seen_frozen)
    for c in cands:
        cs = c['state']; cl = c['ledger']
        n = cs.n(); k = cs.k()
        if n not in missing:
            continue
        ux = cl.sector['X'].upper if hasattr(cl.sector['X'], 'upper') else None
        uz = cl.sector['Z'].upper if hasattr(cl.sector['Z'], 'upper') else None
        d_ub = min(x for x in (ux, uz) if x is not None) if any(x is not None for x in (ux, uz)) else pdoc['distance']['d']
        if d_ub is None:
            d_ub = pdoc['distance']['d']
        if (n, k, d_ub) in seen:
            continue
        # compute w, lc, wc
        allw = [len(r.support) for r in cs.rows]
        w = max(allw) if allw else 0
        wc = 'weight-4' if w <= 4 else 'weight-6' if w <= 6 else 'weight-8' if w <= 8 else 'weight-9plus'
        pl = pdoc.get('locality')
        lc = pl['locality_class'] if (pl and pl.get('locality_class')) else 'unrestricted'
        if not lc: lc = 'unrestricted'
        # checks (relabel Q to 0..n-1)
        relabel = {q: i for i, q in enumerate(sorted(cs.Q))}
        checks = cs.to_challenge_checks(relabel=relabel)
        children.append({
            'n': n, 'k': k, 'd_ub': d_ub, 'w': w, 'lc': lc, 'wc': wc,
            'checks': checks,
            'parent_n': pdoc['n'], 'parent_file': ppath,
            'parent_d': pdoc['distance']['d'],
        })
        seen.add((n, k, d_ub))
    return {'ppath': ppath, 'parent_n': pdoc['n'], 'children': children, 'error': None}


# --- helpers ---
def weight_members(wc):
    start = {'weight-4':0,'weight-6':1,'weight-8':2}.get(wc, 3)
    return ['weight-4','weight-6','weight-8','weight-any'][start:]
def locality_members(lc):
    order = ['local-2d-single','local-2d-bilayer','unrestricted']
    i = order.index(lc) if lc in order else len(order)-1
    return order[i:]
def locidx(lc):
    order = ['local-2d-single','local-2d-bilayer','unrestricted']
    return order.index(lc) if lc in order else len(order)-1
def wstart(wc):
    return {'weight-4':0,'weight-6':1,'weight-8':2}.get(wc, 3)
wc_list = ['weight-4','weight-6','weight-8','weight-any']
def in_cell(e, L, W):
    if locidx(e['lc']) > locidx(L): return False
    if wstart(e['wc']) > wc_list.index(W): return False
    return True
def dominated(r, universe):
    for L in locality_members(r['lc']):
        for W in weight_members(r['wc']):
            for e in universe:
                if e is r: continue
                if not in_cell(e, L, W): continue
                if e['n'] <= r['n'] and e['k'] >= r['k'] and e['d'] >= r['d'] and e['w'] <= r['w']:
                    return True
    return False
def update_pareto(frontier, new_entry):
    """Add new_entry to frontier if not dominated; remove dominated entries."""
    to_remove = [e for e in frontier if dominated(e, [new_entry])]
    for e in to_remove:
        frontier.remove(e)
    if not dominated(new_entry, frontier):
        frontier.append(new_entry)
        return True
    return False

def checks_to_matrices(checks, n):
    import numpy as np
    HX = np.zeros((len(checks['X']), n), dtype=np.int8)
    for i, sup in enumerate(checks['X']):
        for q in sup:
            HX[i, q] = 1
    HZ = np.zeros((len(checks['Z']), n), dtype=np.int8)
    for i, sup in enumerate(checks['Z']):
        for q in sup:
            HZ[i, q] = 1
    return HX, HZ

def save_ckpt(idx, reachable, results, seen, pareto, css_total):
    ck = {
        'idx': idx,
        'reachable': {str(n): [list(v) for v in vals] for n, vals in reachable.items()},
        'results': {str(n): [list(v) for v in vals] for n, vals in results.items()},
        'seen_targets': [list(t) for t in seen],
        'pareto_frontier': pareto,
        'css_total': css_total,
    }
    tmp = CKPT + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(ck, f)
    os.replace(tmp, CKPT)

def write_outputs(reachable, results, pareto_frontier):
    out_all = []
    for n in sorted(reachable):
        for (k, d, w, lc, wc) in sorted(reachable[n]):
            out_all.append(f"{n} {k} {d} {w} {lc} {wc}")
    with open(OUT_REACH, 'w') as f:
        f.write('\n'.join(out_all) + '\n')
    out_nd = []
    for n in sorted(results):
        for (k, d, w, lc, wc) in sorted(results[n]):
            out_nd.append(f"{n} {k} {d} {w} {lc} {wc}")
    with open(OUT_BA, 'w') as f:
        f.write('\n'.join(out_nd) + '\n')
    with open(OUT_PARETO, 'w') as f:
        json.dump(pareto_frontier, f, indent=1)

# --- main ---
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()

    # load docs
    docs = []
    for p in glob.glob(CH + '/codes/*.json'):
        try:
            d = json.load(open(p))
            docs.append((p, d))
        except Exception:
            pass
    print('loaded', len(docs), 'docs', flush=True)

    # missing set
    ns = set(d['n'] for _, d in docs if d.get('code_type') == 'CSS')
    missing = set(n for n in range(1, 1001) if n not in ns)
    print('missing n:', len(missing), flush=True)

    # css parents filtered by N_MAX
    css_parents = [(p, d) for p, d in docs if d.get('code_type') == 'CSS' and d['n'] <= N_MAX]
    css_parents_sorted = sorted(css_parents, key=lambda x: x[1]['n'])
    print('css parents (n<=%d): %d' % (N_MAX, len(css_parents_sorted)), flush=True)

    # load checkpoint
    reachable = {}  # n -> set of tuples
    results = {}
    seen_targets = set()  # (n,k,d) tuples
    pareto_frontier = []  # list of entry dicts
    start_idx = 0

    if os.path.exists(CKPT):
        try:
            ck = json.load(open(CKPT))
            start_idx = ck.get('idx', 0)
            for n, vals in ck.get('reachable', {}).items():
                reachable[int(n)] = set(tuple(v) for v in vals)
            for n, vals in ck.get('results', {}).items():
                results[int(n)] = set(tuple(v) for v in vals)
            for t in ck.get('seen_targets', []):
                seen_targets.add(tuple(t))
            pareto_frontier = ck.get('pareto_frontier', [])
            print('resumed: idx=%d, %d reachable n, %d results n, %d seen, %d pareto' %
                  (start_idx, len(reachable), len(results), len(seen_targets), len(pareto_frontier)), flush=True)
        except Exception as e:
            print('checkpoint load failed:', e, flush=True)
            start_idx = 0

    # fallback: load seen_targets from checklist if empty
    if not seen_targets:
        try:
            cl = json.load(open(os.path.join(OUT_DIR, 'pareto_checklist.json')))
            for e in cl.get('entries', []):
                if e.get('found') and e.get('found_file'):
                    seen_targets.add((e['n'], e['k'], e['d']))
            print('loaded %d seen targets from checklist' % len(seen_targets), flush=True)
        except Exception as e:
            print('checklist load failed:', e, flush=True)

    # fallback: load pareto frontier from file if empty
    if not pareto_frontier and os.path.exists(OUT_PARETO):
        try:
            pareto_frontier = json.load(open(OUT_PARETO))
            print('loaded %d pareto entries from file' % len(pareto_frontier), flush=True)
        except Exception as e:
            print('pareto file load failed:', e, flush=True)

    # load existing board entries for domination check
    board_entries = []
    for _, d in docs:
        if d.get('code_type') != 'CSS': continue
        checks = d['checks']
        allc = []
        if 'X' in checks: allc += checks['X']
        if 'Z' in checks: allc += checks['Z']
        w = max(len(c) for c in allc) if allc else 0
        wc = 'weight-4' if w<=4 else 'weight-6' if w<=6 else 'weight-8' if w<=8 else 'weight-9plus'
        lc = d.get('locality', {}).get('locality_class', 'unreachable') if d.get('locality') else 'unrestricted'
        if not lc: lc = 'unrestricted'
        board_entries.append({'n': d['n'], 'k': d['k'], 'd': d['distance']['d'], 'w': w, 'lc': lc, 'wc': wc})

    # checklist tracking (optional, self-contained)
    checklist_path = os.path.join(OUT_DIR, 'pareto_checklist.json')
    def mark_found(n, k, d, found_by, found_file):
        try:
            if not os.path.exists(checklist_path):
                return False
            with open(checklist_path) as f:
                data = json.load(f)
            changed = False
            for e in data.get('entries', []):
                if e.get('n') == n and e.get('k') == k and e.get('d') == d and not e.get('found'):
                    e['found'] = True
                    e['found_by'] = found_by
                    e['found_file'] = found_file
                    changed = True
            if changed:
                data['found_count'] = sum(1 for e in data['entries'] if e.get('found'))
                tmp = checklist_path + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(data, f, indent=1)
                os.replace(tmp, checklist_path)
            return changed
        except Exception:
            return False
    has_checklist = os.path.exists(checklist_path)

    # staging dir
    try:
        from coordination import staging_dir, unique_path
        stg = staging_dir()
    except Exception:
        stg = '/home/mathys/scratchpad/staged'
        os.makedirs(stg, exist_ok=True)
    print('staging dir:', stg, flush=True)

    from submit import make_submission, save_submission
    import numpy as np

    total = len(css_parents_sorted)
    idx = start_idx
    t0 = time.time()

    # process in chunks
    while idx < total:
        chunk_end = min(idx + CHUNK_SIZE, total)
        chunk = css_parents_sorted[idx:chunk_end]

        # snapshot seen for workers
        seen_snapshot = [list(t) for t in seen_targets]

        # skip dominated parents (heuristic) if enabled
        filtered_chunk = []
        for ppath, pdoc in chunk:
            if SKIP_DOMINATED:
                # build parent entry
                checks = pdoc['checks']
                allc = []
                if 'X' in checks: allc += checks['X']
                if 'Z' in checks: allc += checks['Z']
                w = max(len(c) for c in allc) if allc else 0
                wc = 'weight-4' if w<=4 else 'weight-6' if w<=6 else 'weight-8' if w<=8 else 'weight-9plus'
                lc = pdoc.get('locality', {}).get('locality_class', 'unrestricted') if pdoc.get('locality') else 'unrestricted'
                if not lc: lc = 'unrestricted'
                parent_entry = {'n': pdoc['n'], 'k': pdoc['k'], 'd': pdoc['distance']['d'], 'w': w, 'lc': lc, 'wc': wc}
                if dominated(parent_entry, board_entries):
                    continue
            filtered_chunk.append((ppath, pdoc))
        # prepare args
        args_list = [(ppath, pdoc, frozenset(missing), seen_snapshot) for ppath, pdoc in filtered_chunk]

        # parallel process
        with mp.Pool(processes=WORKERS, initializer=_worker_init) as pool:
            results_list = pool.map(process_parent, args_list)

        # aggregate in main process
        for res in results_list:
            idx += 1
            if res.get('error'):
                continue
            for child in res['children']:
                n = child['n']; k = child['k']; d_ub = child['d_ub']
                w = child['w']; lc = child['lc']; wc = child['wc']
                key = (n, k, d_ub)
                if key in seen_targets:
                    continue
                # save matrix
                try:
                    HX, HZ = checks_to_matrices(child['checks'], n)
                    doc = make_submission(HX, HZ,
                                         name='[[%d,%d,%d]] unified' % (n, k, d_ub),
                                         construction='Unified analyze+stage from parent n=%d.' % child['parent_n'],
                                         authors=['mathysrennela'], family='code-calculus',
                                         confidence='upper_bound', trials=TRIALS)
                    path = unique_path('%s/%d-%d-%d.json' % (stg, n, k, d_ub), doc)
                    save_submission(doc, path, spec={
                        'constructor': 'planner.plan',
                        'params': {'parent_n': child['parent_n'],
                                   'parent_file': child['parent_file'],
                                   'parent_d': child['parent_d']},
                    })
                    print('SAVED: %d-%d-%d (parent n=%d) -> %s' % (n, k, d_ub, child['parent_n'], path), flush=True)
                    seen_targets.add(key)
                    missing.discard(n)
                    if has_checklist:
                        try:
                            mark_found(n, k, d_ub, 'unified', path)
                        except Exception:
                            pass
                except Exception as e:
                    print('SAVE FAILED %d-%d-%d: %s' % (n, k, d_ub, e), flush=True)
                    continue

                # update reachable/results
                tup = (k, d_ub, w, lc, wc)
                reachable.setdefault(n, set()).add(tup)
                # check domination against board
                entry = {'n': n, 'k': k, 'd': d_ub, 'w': w, 'lc': lc, 'wc': wc}
                if not dominated(entry, board_entries):
                    results.setdefault(n, set()).add(tup)
                    # update pareto frontier
                    update_pareto(pareto_frontier, entry)

        # checkpoint after chunk
        save_ckpt(idx, reachable, results, seen_targets, pareto_frontier, len(css_parents_sorted))
        write_outputs(reachable, results, pareto_frontier)
        elapsed = time.time() - t0
        rate = idx / elapsed if elapsed > 0 else 0
        eta = (total - idx) / rate if rate > 0 else 0
        print('processed %d/%d parents | seen=%d | pareto=%d | reachable=%d n | %.1f parents/min | ETA %.0f min' %
              (idx, total, len(seen_targets), len(pareto_frontier), len(reachable), rate*60, eta/60), flush=True)

    # final
    save_ckpt(total, reachable, results, seen_targets, pareto_frontier, total)
    write_outputs(reachable, results, pareto_frontier)
    print('=== DONE ===')
    print('parents processed:', total)
    print('seen targets:', len(seen_targets))
    print('reachable n:', len(reachable))
    print('results n:', len(results))
    print('pareto frontier:', len(pareto_frontier))


if __name__ == '__main__':
    main()
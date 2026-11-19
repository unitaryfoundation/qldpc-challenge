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
  TRIALS        base witness-search trials per side (default: 2000; screen depth)
  TRIALS_PER_D  additional trials per unit of claimed d (default: 2000)
  DEEP_RUNG_MIN_D  claimed d at which the mandatory deep rung applies (default: 20)
  DEEP_RUNG_BASE   deep-rung base trials (default: 200000)
  DEEP_RUNG_PER_D   deep-rung trials per unit d (default: 20000)
  DEEP_RUNG_CAP    deep-rung budget cap (default: 2000000)
  GF2_TRIALS    gf2_fast pre-filter trials per child (default: 2000)
  SKIP_DOMINATED  skip parents dominated by the board (default: 1)
  DEDUP_ORACLE  run research/kit/dedup_oracle.py before staging (default: 1)
  DEDUP_OPEN_PRS  index the codes/ files of open PRs as well as the board (default: 1)
  DEDUP_REFRESH  re-fetch the open-PR index at campaign start instead of
                reading the on-disk cache, which never expires on its own (default: 1)
  DEDUP_PR_LIMIT  how many open PRs to index (default: 200)
  OUT_DEDUP     dedup log, one JSON line per skipped or flagged child
                (default: research/out/dedup_oracle.jsonl)

Dedup oracle (issue #6814). Before a child is staged, and before its witness
search is paid for, its fingerprint and WL signature are checked against the
anti-collision index of ``research/kit/dedup_oracle.py``: the board as the gate
sees it (own identity plus local-Hadamard images) and, with DEDUP_OPEN_PRS, the
``codes/`` files of every open PR. An exact match (shared fingerprint) is the
same code, which the gate would refuse as a duplicate or which another PR is
already filing, so the child is skipped and logged. A WL-only match is a probable
permutation; the gate admits those with a label, so the child is staged with a
note naming the match. The oracle is a filter, never a verdict: a child that
clears it still has to pass ``coordination.gate``.

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
TARGET = os.environ.get('TARGET', 'n').lower()
if TARGET not in ('n', 'k'):
    raise SystemExit('TARGET must be n or k, got %r' % TARGET)
_suffix = '' if TARGET == 'n' else '_k'
CKPT = os.environ.get('CKPT', os.path.join(OUT_DIR, 'reachability_ckpt%s.json' % _suffix))
OUT_REACH = os.environ.get('OUT_REACH', os.path.join(OUT_DIR, 'reachable_n%s.txt' % _suffix))
OUT_BA = os.environ.get('OUT_BA', os.path.join(OUT_DIR, 'board_advancing_n%s.txt' % _suffix))
OUT_PARETO = os.environ.get('OUT_PARETO', os.path.join(OUT_DIR, 'pareto_frontier%s.json' % _suffix))
N_MAX = int(os.environ.get('N_MAX', '1000'))
WORKERS = int(os.environ.get('WORKERS', '4'))
CHUNK_SIZE = int(os.environ.get('CHUNK_SIZE', '25'))
TRIALS = int(os.environ.get('TRIALS', '2000'))  # screening depth; deep-confirm survivors at 20000+
GF2_TRIALS = int(os.environ.get('GF2_TRIALS', '2000'))  # gf2_fast pre-filter trials per child
SKIP_DOMINATED = os.environ.get('SKIP_DOMINATED', '1') == '1'

# --- dedup oracle (issue #6814) ---------------------------------------------
DEDUP_ORACLE = os.environ.get('DEDUP_ORACLE', '1') == '1'
DEDUP_OPEN_PRS = os.environ.get('DEDUP_OPEN_PRS', '1') == '1'
DEDUP_REFRESH = os.environ.get('DEDUP_REFRESH', '1') == '1'
DEDUP_PR_LIMIT = int(os.environ.get('DEDUP_PR_LIMIT', '200'))
OUT_DEDUP = os.environ.get('OUT_DEDUP', os.path.join(OUT_DIR, 'dedup_oracle%s.jsonl' % _suffix))

# --- screening budget: depth-proportional, not flat -------------------------
TRIALS_PER_D = int(os.environ.get('TRIALS_PER_D', '2000'))
DEEP_RUNG_MIN_D = int(os.environ.get('DEEP_RUNG_MIN_D', '20'))
DEEP_RUNG_BASE = int(os.environ.get('DEEP_RUNG_BASE', '200000'))
DEEP_RUNG_PER_D = int(os.environ.get('DEEP_RUNG_PER_D', '20000'))
DEEP_RUNG_CAP = int(os.environ.get('DEEP_RUNG_CAP', '2000000'))


def screening_trials(d_claim):
    d = max(int(d_claim) if d_claim else 0, 1)
    t = TRIALS + TRIALS_PER_D * d
    if d >= DEEP_RUNG_MIN_D:
        t = max(t, DEEP_RUNG_BASE + DEEP_RUNG_PER_D * d)
    return min(t, DEEP_RUNG_CAP)


sys.path.insert(0, CALCULUS)
sys.path.insert(0, CH + '/research/kit')

# --- worker (runs in subprocess) ---
def _worker_init():
    sys.path.insert(0, CALCULUS)
    sys.path.insert(0, CH + '/research/kit')
    sys.path.insert(0, CH + '/verify')

def process_parent(args):
    """Process one parent. Returns (idx, parent_n, children_list, error)."""
    ppath, pdoc, target_spec, seen_frozen = args
    mode = target_spec[0]
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
    if mode == 'n':
        missing = set(target_spec[1])
    else:
        maxk = target_spec[1]
    seen = set(tuple(x) for x in seen_frozen)
    for c in cands:
        cs = c['state']; cl = c['ledger']
        n = cs.n(); k = cs.k()
        if mode == 'n':
            if n not in missing:
                continue
        else:
            if n not in maxk or not (k > maxk[n]):
                continue
        ux = cl.sector['X'].upper if hasattr(cl.sector['X'], 'upper') else None
        uz = cl.sector['Z'].upper if hasattr(cl.sector['Z'], 'upper') else None
        d_ub = min(x for x in (ux, uz) if x is not None) if any(x is not None for x in (ux, uz)) else pdoc['distance']['d']
        if d_ub is None:
            d_ub = pdoc['distance']['d']
        # compute w, lc, wc before dedup so the key includes them
        allw = [len(r.support) for r in cs.rows]
        w = max(allw) if allw else 0
        wc = 'weight-4' if w <= 4 else 'weight-6' if w <= 6 else 'weight-8' if w <= 8 else 'weight-9plus'
        pl = pdoc.get('locality')
        lc = pl['locality_class'] if (pl and pl.get('locality_class')) else 'unrestricted'
        if not lc: lc = 'unrestricted'
        if (n, k, d_ub, w, lc, wc) in seen:
            continue
        # checks (relabel Q to 0..n-1)
        relabel = {q: i for i, q in enumerate(sorted(cs.Q))}
        checks = cs.to_challenge_checks(relabel=relabel)
        children.append({
            'n': n, 'k': k, 'd_ub': d_ub, 'w': w, 'lc': lc, 'wc': wc,
            'checks': checks,
            'parent_n': pdoc['n'], 'parent_file': ppath,
            'parent_d': pdoc['distance']['d'],
            'screen_trials': screening_trials(max(
                ux if ux is not None else d_ub,
                uz if uz is not None else d_ub,
                d_ub)),
        })
        seen.add((n, k, d_ub, w, lc, wc))
    return {'ppath': ppath, 'parent_n': pdoc['n'], 'children': children, 'error': None}



# --- dedup oracle (issue #6814) ---
_DEDUP = {'index': None}   # set in the main process by build_dedup_index, in save workers by _save_init


def build_dedup_index():
    """Build the anti-collision index the save workers check children against.

    Returns None when the oracle is disabled or cannot be imported, so the
    campaign runs as before and says so. Otherwise returns
    ``dedup_oracle.combined_index`` over the board and, with DEDUP_OPEN_PRS,
    the open PRs; the open-PR fetch degrades to nothing when ``gh`` is
    unavailable, so an empty open-PR part is reported rather than passed over.
    """
    if not DEDUP_ORACLE:
        print('dedup oracle: off (DEDUP_ORACLE=0)', flush=True)
        _DEDUP['index'] = None
        return None
    try:
        import dedup_oracle
    except Exception as e:
        print('dedup oracle: unavailable (%s); staging without it' % e, flush=True)
        _DEDUP['index'] = None
        return None
    index = dedup_oracle.combined_index(include_board=True,
                                        include_open_prs=DEDUP_OPEN_PRS,
                                        open_pr_limit=DEDUP_PR_LIMIT,
                                        refresh=DEDUP_REFRESH)
    n_board = sum(1 for e in index if e.get('source') == 'board')
    n_pr = sum(1 for e in index if e.get('source') == 'pr')
    print('dedup oracle: %d board entries, %d open-PR codes indexed' % (n_board, n_pr), flush=True)
    if DEDUP_OPEN_PRS and n_pr == 0:
        print('dedup oracle: WARNING the open-PR index is empty (gh unavailable, or no open PR '
              'carries a codes/ file); cross-PR duplicates will not be caught this run', flush=True)
    _DEDUP['index'] = index
    return index


def _save_init(index):
    _worker_init()
    _DEDUP['index'] = index


def _dedup_matches(entries):
    """Index entries as the log records them and as a line names them."""
    records = [{'source': e.get('source'), 'pr': e.get('pr'), 'name': e.get('name'),
                'n': e.get('n'), 'k': e.get('k'), 'd': e.get('d')} for e in entries]
    names = ['pr#%s:%s' % (r['pr'], r['name']) if r['source'] == 'pr' else '%s:%s' % (r['source'], r['name'])
             for r in records]
    return records, names


def _dedup_check(HX, HZ):
    """Return the oracle's verdict for (HX, HZ) against the index in _DEDUP, or None when it is off.

    ``{'kind': 'exact' | 'wl', 'matches': [...], 'names': [...]}``. The identity
    is the fingerprint and WL signature of the code itself
    (``dedup_oracle.identity_matrices``), compared against index entries that
    carry their own identity and their local-Hadamard images; cheap enough to
    run before the witness search.
    """
    index = _DEDUP['index']
    if not index:
        return None
    import dedup_oracle
    res = dedup_oracle.check(dedup_oracle.identity_matrices(HX, HZ), index)
    for kind in ('exact', 'wl'):
        if res[kind]:
            records, names = _dedup_matches(res[kind])
            return {'kind': kind, 'matches': records, 'names': names}
    return None


def log_dedup(record):
    """Append one dedup event to OUT_DEDUP (JSON lines); never raises."""
    try:
        with open(OUT_DEDUP, 'a') as f:
            f.write(json.dumps(record) + '\n')
    except Exception:
        pass


# --- save worker (runs in subprocess) ---
def _save_one(args):
    """Save one child. Returns dict with ok, child, bkey, path, error, and dedup when the oracle spoke."""
    bkey, child, stg, trials = args
    sys.path.insert(0, CALCULUS)
    sys.path.insert(0, CH + '/research/kit')
    n = child['n']; k = child['k']; d_ub = child['d_ub']
    try:
        import numpy as np
        from submit import make_submission, save_submission
        from coordination import unique_path
        HX, HZ = checks_to_matrices(child['checks'], n)
        dedup = _dedup_check(HX, HZ)
        if dedup is not None and dedup['kind'] == 'exact':
            return {'ok': False, 'child': child, 'bkey': bkey, 'path': None, 'dedup': dedup,
                    'error': 'exact duplicate of ' + ', '.join(dedup['names'])}
        notes = None
        if dedup is not None:
            notes = ('Dedup oracle (research/kit/dedup_oracle.py): shares the WL signature of %s, '
                     'a probable permutation of that code; the gate admits it with a '
                     'possibly-equivalent label.' % ', '.join(dedup['names']))
        doc = make_submission(HX, HZ,
                             name='[[%d,%d,%d]] unified' % (n, k, d_ub),
                             construction='Unified analyze+stage from parent n=%d.' % child['parent_n'],
                             authors=['mathysrennela'], family='code-calculus',
                             confidence='upper_bound', trials=trials, notes=notes)
        path = unique_path('%s/%d-%d-%d.json' % (stg, n, k, d_ub), doc)
        save_submission(doc, path, preflight=False, spec={
            'constructor': 'planner.plan',
            'params': {'parent_n': child['parent_n'],
                       'parent_file': child['parent_file'],
                       'parent_d': child['parent_d']},
        })
        out = {'ok': True, 'child': child, 'bkey': bkey, 'path': path, 'error': None}
        if dedup is not None:
            out['dedup'] = dedup
        return out
    except Exception as e:
        return {'ok': False, 'child': child, 'bkey': bkey, 'path': None, 'error': str(e)}

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
_LOCAL_ORDER = ['local-2d-single', 'local-2d-bilayer', 'unrestricted']
_WEIGHT_ORDER = ['weight-4', 'weight-6', 'weight-8', 'weight-any']

def _lidx(x):
    return _LOCAL_ORDER.index(x) if x in _LOCAL_ORDER else len(_LOCAL_ORDER) - 1

def _widx(x):
    return _WEIGHT_ORDER.index(x) if x in _WEIGHT_ORDER else len(_WEIGHT_ORDER) - 1

def dominated(r, universe):
    """Canonical cell-aware domination (matches research/kit/frontier.py and the gate).

    e dominates r only if e is no looser than r on both locality and weight
    (stricter-or-equal cell membership), no worse on all four axes, and strictly
    better on at least one. A tie on all four is not dominance.
    """
    for e in universe:
        if e is r:
            continue
        if e.get('code_type', 'CSS') != r.get('code_type', 'CSS'):
            continue
        if not (_widx(e.get('wc', e.get('weight_class'))) <= _widx(r['wc'])
                and _lidx(e.get('lc', e.get('locality_class'))) <= _lidx(r['lc'])):
            continue
        ew = e.get('w')
        rw = r.get('w')
        if ew is None or rw is None:
            continue
        if (e['n'] <= r['n'] and e['k'] >= r['k'] and e['d'] >= r['d'] and ew <= rw
                and (e['n'] < r['n'] or e['k'] > r['k'] or e['d'] > r['d'] or ew < rw)):
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

def better_variant(w, lc, wc, pw, plc, pwc):
    """Return True if (w,lc,wc) is a strictly better variant than (pw,plc,pwc)."""
    if w != pw:
        return w < pw
    li, pli = _lidx(lc), _lidx(plc)
    if li != pli:
        return li < pli
    wi, pwi = _widx(wc), _widx(pwc)
    if wi != pwi:
        return wi < pwi
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

def save_ckpt(idx, reachable, results, seen, pareto, css_total, best_variants=None):
    ck = {
        'idx': idx,
        'reachable': {str(n): [list(v) for v in vals] for n, vals in reachable.items()},
        'results': {str(n): [list(v) for v in vals] for n, vals in results.items()},
        'seen_targets': [list(t) for t in seen],
        'pareto_frontier': pareto,
        'css_total': css_total,
        'best_variants': [[list(bk), bv[0], bv[1], bv[2], bv[3]] for bk, bv in (best_variants or {}).items()],
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

    # missing set (n mode) / k-targetable set (k mode, filled in after board load)
    if TARGET == 'n':
        ns = set(d['n'] for _, d in docs if d.get('code_type') == 'CSS')
        missing = set(n for n in range(1, 1001) if n not in ns)
        print('missing n:', len(missing), flush=True)
    else:
        missing = set()
        print('TARGET=k: k-gap mode (parents with n on board, k above current max)', flush=True)

    # css parents filtered by N_MAX
    css_parents = [(p, d) for p, d in docs if d.get('code_type') == 'CSS' and d['n'] <= N_MAX]
    css_parents_sorted = sorted(css_parents, key=lambda x: x[1]['n'])
    print('css parents (n<=%d): %d' % (N_MAX, len(css_parents_sorted)), flush=True)

    # load checkpoint
    reachable = {}  # n -> set of tuples
    results = {}
    seen_targets = set()  # (n,k,d,...) tuples
    best_variants = {}    # (n,k,d_ub) -> (w, lc, wc, path) best staged variant
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
                seen_targets.add(tuple(t))  # old 3-tuples simply never match new keys
            pareto_frontier = ck.get('pareto_frontier', [])
            for bv in ck.get('best_variants', []):
                try:
                    bk = tuple(bv[0])
                    best_variants[bk] = (bv[1], bv[2], bv[3], bv[4])
                except Exception:
                    pass
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

    # load existing board entries for domination check (via verifier computed fields)
    sys.path.insert(0, CH + '/verify')
    try:
        import qldpc_verify as _V
        board_entries = []
        for e in _V.board_reports(os.path.join(CH, 'codes')):
            doc, rep = e['doc'], e['report']
            if doc is None or rep is None or doc.get('code_type') != 'CSS':
                continue
            comp = rep.get('computed', {})
            checks = doc['checks']
            allc = []
            if 'X' in checks: allc += checks['X']
            if 'Z' in checks: allc += checks['Z']
            w = comp.get('max_check_weight')
            if w is None:
                w = max((len(c) for c in allc), default=0)
            wc = comp.get('weight_class')
            if not wc:
                wc = 'weight-4' if w <= 4 else 'weight-6' if w <= 6 else 'weight-8' if w <= 8 else 'weight-9plus'
            lc = comp.get('locality_class') or 'unrestricted'
            if not lc:
                lc = 'unrestricted'
            board_entries.append({'n': doc['n'], 'k': doc['k'], 'd': doc['distance']['d'],
                                 'w': w, 'lc': lc, 'wc': wc, 'code_type': 'CSS'})
    except Exception:
        board_entries = []
        for _, d in docs:
            if d.get('code_type') != 'CSS': continue
            checks = d['checks']
            allc = []
            if 'X' in checks: allc += checks['X']
            if 'Z' in checks: allc += checks['Z']
            w = max(len(c) for c in allc) if allc else 0
            wc = 'weight-4' if w<=4 else 'weight-6' if w<=6 else 'weight-8' if w<=8 else 'weight-9plus'
            lc = 'unrestricted'
            board_entries.append({'n': d['n'], 'k': d['k'], 'd': d['distance']['d'], 'w': w, 'lc': lc, 'wc': wc, 'code_type': 'CSS'})

    # k-targetable set for missing-k mode: current max k per n on the board
    maxk_by_n = {}
    for e in board_entries:
        if e['n'] not in maxk_by_n or e['k'] > maxk_by_n[e['n']]:
            maxk_by_n[e['n']] = e['k']
    if TARGET == 'k':
        print('k-targetable n on board:', len(maxk_by_n), flush=True)

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

    # anti-collision index: the board plus open PRs, built once per run (issue #6814)
    dedup_index = build_dedup_index()
    dedup_skipped = 0
    dedup_flagged = 0

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
        if TARGET == 'n':
            target_spec = ('n', frozenset(missing))
        else:
            target_spec = ('k', maxk_by_n)
        args_list = [(ppath, pdoc, target_spec, seen_snapshot) for ppath, pdoc in filtered_chunk]

        # parallel process
        with mp.Pool(processes=WORKERS, initializer=_worker_init) as pool:
            results_list = pool.map(process_parent, args_list)

        # aggregate in main process: collect all children
        all_children = []
        for res in results_list:
            if res.get('error'):
                continue
            all_children.extend(res['children'])

        # dedup across chunk: keep best variant per (n,k,d_ub)
        best_in_chunk = {}
        for child in all_children:
            n = child['n']; k = child['k']; d_ub = child['d_ub']
            w = child['w']; lc = child['lc']; wc = child['wc']
            key = (n, k, d_ub, w, lc, wc)
            if key in seen_targets:
                continue
            bkey = (n, k, d_ub)
            prev = best_variants.get(bkey)
            if prev is not None and not better_variant(w, lc, wc, prev[0], prev[1], prev[2]):
                continue
            prev_local = best_in_chunk.get(bkey)
            if prev_local is not None and not better_variant(w, lc, wc, prev_local['w'], prev_local['lc'], prev_local['wc']):
                continue
            best_in_chunk[bkey] = child

        # save in parallel
        save_args = [(bkey, child, stg, child.get('screen_trials', TRIALS)) for bkey, child in best_in_chunk.items()]
        if save_args:
            with mp.Pool(processes=WORKERS, initializer=_save_init, initargs=(dedup_index,)) as save_pool:
                save_results = save_pool.map(_save_one, save_args)
        else:
            save_results = []

        for sr in save_results:
            child = sr['child']
            bkey = sr['bkey']
            n = child['n']; k = child['k']; d_ub = child['d_ub']
            w = child['w']; lc = child['lc']; wc = child['wc']
            key = (n, k, d_ub, w, lc, wc)
            if not sr['ok']:
                if sr.get('dedup'):
                    dedup_skipped += 1
                    print('DEDUP SKIP %d-%d-%d (parent n=%d): %s' % (n, k, d_ub, child['parent_n'], sr['error']),
                          flush=True)
                    log_dedup({'event': 'skipped', 'kind': 'exact', 'n': n, 'k': k, 'd': d_ub, 'w': w,
                               'parent_n': child['parent_n'], 'parent_file': child['parent_file'],
                               'matches': sr['dedup']['matches']})
                else:
                    print('SAVE FAILED %d-%d-%d: %s' % (n, k, d_ub, sr['error']), flush=True)
                continue
            path = sr['path']
            print('SAVED: %d-%d-%d (parent n=%d) -> %s' % (n, k, d_ub, child['parent_n'], path), flush=True)
            if sr.get('dedup'):
                dedup_flagged += 1
                print('  WL-EQUIVALENT: shares the WL signature of %s (staged with a note)'
                      % ', '.join(sr['dedup']['names']), flush=True)
                log_dedup({'event': 'flagged', 'kind': 'wl', 'n': n, 'k': k, 'd': d_ub, 'w': w,
                           'parent_n': child['parent_n'], 'parent_file': child['parent_file'],
                           'path': path, 'matches': sr['dedup']['matches']})
            seen_targets.add(key)
            if TARGET == 'n':
                missing.discard(n)
            else:
                if n not in maxk_by_n or k > maxk_by_n[n]:
                    maxk_by_n[n] = k
            prev = best_variants.get(bkey)
            if prev is not None and prev[3] and os.path.exists(prev[3]) and prev[3] != path:
                try: os.remove(prev[3])
                except Exception: pass
            best_variants[bkey] = (w, lc, wc, path)
            if has_checklist:
                try:
                    mark_found(n, k, d_ub, 'unified', path)
                except Exception:
                    pass

            # update reachable/results
            tup = (k, d_ub, w, lc, wc)
            reachable.setdefault(n, set()).add(tup)
            entry = {'n': n, 'k': k, 'd': d_ub, 'w': w, 'lc': lc, 'wc': wc}
            if not dominated(entry, board_entries):
                results.setdefault(n, set()).add(tup)
                update_pareto(pareto_frontier, entry)

        idx = chunk_end

        # checkpoint after chunk
        save_ckpt(idx, reachable, results, seen_targets, pareto_frontier, len(css_parents_sorted), best_variants)
        write_outputs(reachable, results, pareto_frontier)
        elapsed = time.time() - t0
        rate = idx / elapsed if elapsed > 0 else 0
        eta = (total - idx) / rate if rate > 0 else 0
        print('processed %d/%d parents | seen=%d | pareto=%d | reachable=%d n | dedup skipped=%d flagged=%d | '
              '%.1f parents/min | ETA %.0f min' %
              (idx, total, len(seen_targets), len(pareto_frontier), len(reachable), dedup_skipped, dedup_flagged,
               rate*60, eta/60), flush=True)

    # final
    save_ckpt(total, reachable, results, seen_targets, pareto_frontier, total, best_variants)
    write_outputs(reachable, results, pareto_frontier)
    print('=== DONE ===')
    print('parents processed:', total)
    print('seen targets:', len(seen_targets))
    print('reachable n:', len(reachable))
    print('results n:', len(results))
    print('pareto frontier:', len(pareto_frontier))
    print('dedup oracle: skipped %d exact duplicates, flagged %d WL equivalents (%s)'
          % (dedup_skipped, dedup_flagged, OUT_DEDUP))


if __name__ == '__main__':
    main()
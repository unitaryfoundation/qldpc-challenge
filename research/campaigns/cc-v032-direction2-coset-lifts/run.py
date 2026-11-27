#!/usr/bin/env python3
"""code-calculus v0.3.2, direction 2 of issue #7377: coset lifted products.

The question. ``lift_{G;H}(A, B)`` (v0.3.2, L-LIFTED with a subgroup) indexes
its blocks by the left cosets G/H instead of G, so a group of order |G| and a
subgroup of index l give a code of the size a lift over a group of order l
gives. When H is normal the two actions factor through G/H and the coset lift
is the regular lift over the quotient group, so the only cases that can say
anything new are non-normal H. Do those produce codes the regular lifts over
groups of order l (abelian, and the nonabelian ones at l = 6 and 8) do not?

Phase A (exact, no search). For every permutation group in GROUPS and every
subgroup H of index 2..8, build every coset lift of the 1x2 shape (A = [a1 a2]
over F_2[G], B = [b1 b2] over F_2[N_G(H)], entries single elements or sums of
two, a1 and b1 normalized to contain the identity, which is a relabeling), or
a sample of them past SAMPLE pairs, and of the 1x3 shape by sampling. Record
(n, k, w), Tanner connectivity, the exact fingerprint and the
Weisfeiler-Leman signature of ``verify/qldpc_verify.py``, both computed on
the full generated row set (see ``full_lift_rows``: the library's retained
display drops dependent rows in an order that differs between a coset lift
and the lift over the quotient, which makes the same code hash differently). Build the same
sets for the regular lifts over every abelian group of order 2..8 and over
S3, D4, Q8 (the nonabelian groups of order 6 and 8). A coset-lift WL class
that no regular lift of the same block count and shape reaches is new.

Phase B (gate). For each new connected class with k >= 1, one representative
is packaged with research/kit/submit.make_submission (witness-backed upper
bound), staged under research/candidates/ with its recipe, and judged by the
trusted gate through research/kit/coordination.gate_and_record. Nothing is
submitted; survivors are reported for human review.

Run:  CODE_CALCULUS_PATH=<clone of code-calculus at v0.3.2> \
      uv run --extra research python research/campaigns/cc-v032-direction2-coset-lifts/run.py \
          --out research/candidates/<run>/ [--sample 2000] [--gate-max 60]
"""

import argparse
import collections
import itertools
import json
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
CC = os.environ.get("CODE_CALCULUS_PATH", os.path.join(os.path.dirname(ROOT), "code-calculus"))
for _p in (CC, ROOT, os.path.join(ROOT, "verify"), os.path.join(ROOT, "research", "kit")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


import qldpc_verify as QV  # noqa: E402
from machine import constructors as C  # noqa: E402
from machine.connectivity import is_tanner_connected  # noqa: E402
from machine.constructors import lifted_product  # noqa: E402
from machine.priced_calculus import Malformed, NoDerivation  # noqa: E402

# ---------------------------------------------------------------- groups


def compose(p, q):
    """P after q, as permutation tuples."""
    return tuple(p[q[i]] for i in range(len(q)))


def inverse(p):
    inv = [0] * len(p)
    for i, x in enumerate(p):
        inv[x] = i
    return tuple(inv)


def closure(gens, degree):
    e = tuple(range(degree))
    members = {e}
    frontier = [e]
    while frontier:
        nxt = []
        for h in frontier:
            for g in gens:
                x = compose(h, g)
                if x not in members:
                    members.add(x)
                    nxt.append(x)
        frontier = nxt
    return frozenset(members)


def cyc(degree, *cycles):
    p = list(range(degree))
    for c in cycles:
        for a, b in zip(c, c[1:] + c[:1]):
            p[a] = b
    return tuple(p)


def dihedral(m):
    """D_m on m points: rotation and a reflection."""
    r = tuple((i + 1) % m for i in range(m))
    s = tuple((-i) % m for i in range(m))
    return [r, s], m


GROUPS = {
    "S3": ([cyc(3, (0, 1, 2)), cyc(3, (0, 1))], 3),
    "D4": dihedral(4),
    "Q8": (
        [
            # Q8 as a permutation group on 8 points (its regular representation)
            (1, 2, 3, 0, 5, 6, 7, 4),  # i
            (4, 7, 6, 5, 2, 1, 0, 3),  # j
        ],
        8,
    ),
    "D5": dihedral(5),
    "A4": ([cyc(4, (0, 1, 2)), cyc(4, (0, 1), (2, 3))], 4),
    "D6": dihedral(6),
    "Dic3": (
        [
            # dicyclic group of order 12 (Z3 : Z4) on 12 points, regular representation
            None,
            None,
        ],
        12,
    ),
    "S4": ([cyc(4, (0, 1, 2, 3)), cyc(4, (0, 1))], 4),
    "D7": dihedral(7),
    "D8": dihedral(8),
}
# Dic3: build from its presentation a^6 = 1, b^2 = a^3, b a b^-1 = a^-1 as a
# regular permutation representation on its own 12 elements.
_dic_elems = [(i, j) for j in range(2) for i in range(6)]  # a^i b^j


def _dic_mul(x, y):
    (i, j), (k, m) = x, y
    if j == 0:
        return ((i + k) % 6, m)
    # b a^k = a^-k b ; b b = a^3
    i2 = (i - k) % 6
    if m == 0:
        return (i2, 1)
    return ((i2 + 3) % 6, 0)


_dic_index = {x: t for t, x in enumerate(_dic_elems)}
_dic_a = tuple(_dic_index[_dic_mul((1, 0), x)] for x in _dic_elems)
_dic_b = tuple(_dic_index[_dic_mul((0, 1), x)] for x in _dic_elems)
GROUPS["Dic3"] = ([_dic_a, _dic_b], 12)

ABELIAN = {  # comparator groups by cyclic orders, order 2..8
    "Z2": (2,),
    "Z3": (3,),
    "Z4": (4,),
    "Z2xZ2": (2, 2),
    "Z5": (5,),
    "Z6": (6,),
    "Z7": (7,),
    "Z8": (8,),
    "Z4xZ2": (4, 2),
    "Z2xZ2xZ2": (2, 2, 2),
}
NONABELIAN_REGULAR = ("S3", "D4", "Q8")  # the nonabelian groups of order 6 and 8
SHAPES = [(1, 2), (1, 3)]  # (m, n) of both A and B; main() replaces the list contents from --shapes


def subgroups(members, degree):
    """Every subgroup generated by one or two elements (all of these groups are small)."""
    elems = sorted(members)
    seen = {}
    for a in elems:
        for b in elems:
            if b < a:
                continue
            H = closure([a, b], degree)
            seen.setdefault(H, (a, b))
    return seen


def conjugacy_representatives(members, subs):
    """One subgroup per conjugacy class: conjugate subgroups give the same codes up to relabeling."""
    out = {}
    seen = set()
    for H in sorted(subs, key=lambda h: (-len(h), sorted(h))):
        if H in seen:
            continue
        orbit = {frozenset(compose(compose(g, h), inverse(g)) for h in H) for g in members}
        seen |= orbit
        out[H] = subs[H]
    return out


def normalizer(members, H):
    out = []
    for g in members:
        gi = inverse(g)
        if all(compose(compose(g, h), gi) in H for h in H):
            out.append(g)
    return frozenset(out)


def is_normal(members, H):
    return len(normalizer(members, H)) == len(members)


# ---------------------------------------------------------------- codes


def entries(elements, identity, *, normalized):
    """Algebra entries: single elements and sums of two. ``normalized``: entries containing the identity."""
    singles = [[g] for g in elements]
    pairs = [[g, h] for g, h in itertools.combinations(elements, 2)]
    if normalized:
        return [[identity]] + [[identity, g] for g in elements if g != identity]
    return singles + pairs


def state_doc(state):
    """Return a minimal CSS document for the verifier's identity keys (the WL hash reads the checks only)."""
    checks = state.to_challenge_checks()
    return {"n": state.n(), "k": state.k(), "code_type": "CSS", "checks": checks, "distance": {"d": 0}}


def keys_of(doc):
    n = doc["n"]
    HX = QV._matrix(doc["checks"]["X"], n)
    HZ = QV._matrix(doc["checks"]["Z"], n)
    return QV.css_fingerprint(HX, HZ), QV.signature(doc)["hash"]


def full_lift_rows(group_spec, A, B, subgroup):
    """Return the lifted product's generated rows before the library drops dependent ones.

    ``lifted_product`` returns a retained display: dependent rows are dropped
    in enumeration order, so the same code built over G/H (S3 element order)
    and over G with H normal (coset-representative order) keeps different
    rows and gets a different Weisfeiler-Leman hash although the row spaces
    agree. The full row set is canonical for the construction, so classes are
    keyed on it. This mirrors ``lifted_product`` line for line minus the
    retention step.
    """
    info = C._group_spec(group_spec)
    A_ = C._algebra_matrix(A, info, "A")
    B_ = C._algebra_matrix(B, info, "B")
    if subgroup is not None:
        members, gens, reps, coset_of = C._coset_spec(info, subgroup)
        mul, inv = info["mul"], info["inv"]
        for b_row in B_:
            for entry in b_row:
                for g in entry:
                    if any(mul(mul(g, s_), inv(g)) not in members for s_ in gens):
                        raise Malformed("B term outside the normalizer")
        ell = len(reps)

        def left(x):
            return C._left_coset_rows(x, info, reps, coset_of)

        def right(y):
            return C._right_coset_rows(y, info, reps, coset_of)
    else:
        ell = len(info["elements"])

        def left(x):
            return C._left_lift_rows(x, info)

        def right(y):
            return C._right_lift_rows(y, info)

    m_a, n_a = len(A_), len(A_[0])
    m_b, n_b = len(B_), len(B_[0])
    left_n = n_a * n_b * ell
    n = left_n + m_a * m_b * ell
    X, Z = [], []
    for a in range(m_a):
        for j in range(n_b):
            for h in range(ell):
                mask = 0
                for i in range(n_a):
                    mask |= left(A_[a][i])[h] << ((i * n_b + j) * ell)
                for b in range(m_b):
                    mask |= right(C._involution(B_[b][j], info))[h] << (left_n + (a * m_b + b) * ell)
                X.append(mask)
    for i in range(n_a):
        for b in range(m_b):
            for h in range(ell):
                mask = 0
                for j in range(n_b):
                    mask |= right(B_[b][j])[h] << ((i * n_b + j) * ell)
                for a in range(m_a):
                    mask |= left(C._involution(A_[a][i], info))[h] << (left_n + (a * m_b + b) * ell)
                Z.append(mask)
    return n, X, Z


def keys_of_full(group_spec, A, B, subgroup):
    """(fingerprint, class key) of the full generated display of a lift.

    The class key is nauty's canonical certificate of the typed Tanner graph
    (qubits, X rows, Z rows as three colors): equal exactly when the two
    generated displays are the same graph up to relabeling, which for a
    lifted product means the same code. The verifier's Weisfeiler-Leman hash
    is too coarse here: a lift's Tanner graph is nearly vertex-transitive and
    color refinement lumps thousands of codes with different k into a
    handful of hashes, while the retained display over-separates (see
    ``full_lift_rows``). The exact fingerprint (RREF) is kept as before.
    """
    import hashlib

    import pynauty

    n, X, Z = full_lift_rows(group_spec, A, B, subgroup)
    supports = [[q for q in range(n) if (m >> q) & 1] for m in X + Z]
    adjacency = {}
    for r, sup in enumerate(supports):
        adjacency[n + r] = list(sup)
    g = pynauty.Graph(
        n + len(supports),
        directed=False,
        adjacency_dict=adjacency,
        vertex_coloring=[set(range(n)), set(range(n, n + len(X))), set(range(n + len(X), n + len(supports)))],
    )
    cert = hashlib.sha256(pynauty.certificate(g)).hexdigest()[:16]
    HX = QV._matrix([[q for q in range(n) if (m >> q) & 1] for m in X], n)
    HZ = QV._matrix([[q for q in range(n) if (m >> q) & 1] for m in Z], n)
    return QV.css_fingerprint(HX, HZ), cert


def build(group_spec, A, B, subgroup):
    try:
        state, _dropped = lifted_product(group_spec, A, B, subgroup=subgroup)
    except (Malformed, NoDerivation) as exc:
        return None, str(exc)[:80]
    return state, None


def _matrix(shape, first, rest):
    """Lay ``first`` and the ``rest`` entries out as an m x n matrix, row-major."""
    m, n = shape
    flat = [first, *rest]
    return [flat[r * n : (r + 1) * n] for r in range(m)]


def sweep(label, group_spec, a_elems, b_elems, identity, shape, subgroup, rng, sample, log):
    """Enumerate or sample (A, B) pairs, both of ``shape`` (m, n), and return the class table."""
    ma, na = shape
    cells = ma * na - 1  # entries besides the normalized first one
    a_first = entries(a_elems, identity, normalized=True)
    a_rest = entries(a_elems, identity, normalized=False)
    b_first = entries(b_elems, identity, normalized=True)
    b_rest = entries(b_elems, identity, normalized=False)
    total = len(a_first) * len(a_rest) ** cells * len(b_first) * len(b_rest) ** cells
    classes = {}
    tried = derived = 0
    refused = collections.Counter()

    def one(A, B):
        nonlocal tried, derived
        tried += 1
        state, why = build(group_spec, A, B, subgroup)
        if state is None:
            refused[why] += 1
            return
        derived += 1
        k = state.k()
        if k < 1:
            refused["k = 0"] += 1
            return
        doc = state_doc(state)
        fp, sig = keys_of_full(group_spec, A, B, subgroup)
        if sig in classes:
            classes[sig]["count"] += 1
            classes[sig]["fingerprints"].add(fp)
            return
        classes[sig] = {
            "n": doc["n"],
            "k": k,
            "w": state.w(),
            "connected": bool(is_tanner_connected(state)),
            "count": 1,
            "fingerprints": {fp},
            "A": A,
            "B": B,
        }

    if total <= sample:
        for a1 in a_first:
            for rest_a in itertools.product(a_rest, repeat=cells):
                A = _matrix(shape, a1, rest_a)
                for b1 in b_first:
                    for rest_b in itertools.product(b_rest, repeat=cells):
                        one(A, _matrix(shape, b1, rest_b))
        mode = "exhaustive"
    else:
        for _ in range(sample):
            A = _matrix(shape, rng.choice(a_first), [rng.choice(a_rest) for _ in range(cells)])
            B = _matrix(shape, rng.choice(b_first), [rng.choice(b_rest) for _ in range(cells)])
            one(A, B)
        mode = f"sampled {sample} of {total}"
    log(
        f"  {label} shape {ma}x{na}: {mode}; tried {tried}, derived {derived}, "
        f"{len(classes)} WL classes ({sum(1 for c in classes.values() if c['connected'])} connected)"
    )
    return {
        "mode": mode,
        "total": total,
        "tried": tried,
        "derived": derived,
        "refused": dict(refused),
        "classes": classes,
    }


def perm_group_spec(gens, degree):
    return {"generators": [list(g) for g in gens], "degree": degree}


# ---------------------------------------------------------------- main


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="durable output directory (under research/candidates/)")
    ap.add_argument(
        "--sample",
        type=int,
        default=100000,
        help="1x2 pairs per (group, subgroup) past which to sample (the default makes most 1x2 sweeps exhaustive)",
    )
    ap.add_argument("--sample-3", type=int, default=3000, help="1x3 pairs per (group, subgroup); always a sample")
    ap.add_argument("--gate-max", type=int, default=60, help="new classes to package and gate, largest kd^2/n first")
    ap.add_argument("--trials", type=int, default=20000, help="RIS trials per side for the witness search")
    ap.add_argument("--seed", type=int, default=7377)
    ap.add_argument(
        "--shapes",
        default="1x2,1x3",
        help="base shapes m x n for A and B, comma separated; 1x2 is exhaustive where it fits, the rest sampled",
    )
    ap.add_argument("--skip-gate", action="store_true")
    ap.add_argument(
        "--gate-from", default=None, metavar="PATH", help="skip phase A; gate the classes of this new_classes.json"
    )
    ap.add_argument(
        "--per-tuple",
        type=int,
        default=0,
        help="with --gate-from: at most this many classes per (n, k, w), lowest k/n first",
    )
    ap.add_argument("--already", default=None, metavar="PATH", help="a phase_b.json whose classes are not gated again")
    ap.add_argument("--phase-b-name", default="phase_b.json")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    log_path = os.path.join(args.out, "run.log")

    def log(msg):
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    t0 = time.time()
    SHAPES[:] = [tuple(int(x) for x in sh.split("x")) for sh in args.shapes.split(",")]
    if args.gate_from:
        with open(args.gate_from, encoding="utf-8") as f:
            new_classes = json.load(f)
        done = set()
        if args.already:
            with open(args.already, encoding="utf-8") as f:
                done = {g["sig"] for g in json.load(f)}
        new_classes = {sig: rec for sig, rec in new_classes.items() if sig not in done}
        if args.per_tuple:
            by_tuple = {}
            for sig, rec in sorted(new_classes.items(), key=lambda kv: (kv[1]["k"] / kv[1]["n"], kv[1]["n"], kv[0])):
                by_tuple.setdefault((rec["n"], rec["k"], rec["w"]), []).append((sig, rec))
            new_classes = {sig: rec for rows in by_tuple.values() for sig, rec in rows[: args.per_tuple]}
        log(f"gating {len(new_classes)} classes from {args.gate_from} ({len(done)} already gated)")
        return gate_classes(new_classes, args, log, t0)
    # Phase A1: comparator classes per (block count l, shape)
    comparator = {}  # (l, shape) -> {sig: {"source": ..., ...}}
    comp_stats = []
    for name, orders in ABELIAN.items():
        order = 1
        for o in orders:
            order *= o
        elems = list(itertools.product(*[range(o) for o in orders]))
        identity = tuple(0 for _ in orders)
        for shape in SHAPES:
            res = sweep(
                f"abelian {name}",
                list(orders),
                elems,
                elems,
                identity,
                shape,
                None,
                rng,
                args.sample if shape == (1, 2) else args.sample_3,
                log,
            )
            table = comparator.setdefault((order, shape), {})
            for sig, c in res["classes"].items():
                table.setdefault(
                    sig, {"source": [], **{k: v for k, v in c.items() if k in ("n", "k", "w", "connected")}}
                )
                table[sig]["source"].append(name)
            comp_stats.append(
                {
                    "group": name,
                    "kind": "abelian",
                    "order": order,
                    "shape": list(shape),
                    **{k: res[k] for k in ("mode", "total", "tried", "derived", "refused")},
                    "classes": len(res["classes"]),
                    "connected_classes": sum(1 for c in res["classes"].values() if c["connected"]),
                }
            )
    for name in NONABELIAN_REGULAR:
        gens, degree = GROUPS[name]
        members = closure(gens, degree)
        elems = sorted(members)
        identity = tuple(range(degree))
        spec = perm_group_spec(gens, degree)
        for shape in SHAPES:
            res = sweep(
                f"regular {name}",
                spec,
                elems,
                elems,
                identity,
                shape,
                None,
                rng,
                args.sample if shape == (1, 2) else args.sample_3,
                log,
            )
            table = comparator.setdefault((len(members), shape), {})
            for sig, c in res["classes"].items():
                table.setdefault(
                    sig, {"source": [], **{k: v for k, v in c.items() if k in ("n", "k", "w", "connected")}}
                )
                table[sig]["source"].append(name)
            comp_stats.append(
                {
                    "group": name,
                    "kind": "nonabelian regular",
                    "order": len(members),
                    "shape": list(shape),
                    **{k: res[k] for k in ("mode", "total", "tried", "derived", "refused")},
                    "classes": len(res["classes"]),
                    "connected_classes": sum(1 for c in res["classes"].values() if c["connected"]),
                }
            )
    log(f"comparators built in {time.time() - t0:.0f} s")

    # Phase A2: coset lifts
    rows = []
    new_classes = {}  # sig -> record
    for name, (gens, degree) in GROUPS.items():
        members = closure(gens, degree)
        order = len(members)
        identity = tuple(range(degree))
        spec = perm_group_spec(gens, degree)
        subs = conjugacy_representatives(members, subgroups(members, degree))
        for H, (ga, gb) in sorted(subs.items(), key=lambda kv: (-len(kv[0]), sorted(kv[0]))):
            index = order // len(H)
            if index < 2 or index > 8 or len(H) == 1:
                continue
            normal = is_normal(members, H)
            N = sorted(normalizer(members, H))
            sub_gens = [list(ga)] if closure([ga], degree) == H else [list(ga), list(gb)]
            for shape in SHAPES:
                res = sweep(
                    f"coset {name}/H(order {len(H)}, index {index}, "
                    f"{'normal' if normal else 'non-normal'}, |N|={len(N)})",
                    spec,
                    sorted(members),
                    N,
                    identity,
                    shape,
                    sub_gens,
                    rng,
                    args.sample if shape == (1, 2) else args.sample_3,
                    log,
                )
                table = comparator.get((index, shape), {})
                comp_exhaustive = all(
                    c["mode"] == "exhaustive" for c in comp_stats if c["order"] == index and tuple(c["shape"]) == shape
                )
                in_comp = {sig for sig in res["classes"] if sig in table}
                new = {sig: c for sig, c in res["classes"].items() if sig not in table}
                new_connected = {sig: c for sig, c in new.items() if c["connected"]}
                row = {
                    "group": name,
                    "order": order,
                    "subgroup_order": len(H),
                    "index": index,
                    "normal": normal,
                    "normalizer_order": len(N),
                    "shape": list(shape),
                    **{k: res[k] for k in ("mode", "total", "tried", "derived", "refused")},
                    "classes": len(res["classes"]),
                    "connected_classes": sum(1 for c in res["classes"].values() if c["connected"]),
                    "comparator_exhaustive": comp_exhaustive,
                    "classes_in_regular_lifts": len(in_comp),
                    "classes_new": len(new),
                    "classes_new_connected": len(new_connected),
                    "new_params": sorted({(c["n"], c["k"], c["w"]) for c in new_connected.values()}),
                }
                rows.append(row)
                log(
                    f"    -> {len(in_comp)} classes among the regular lifts of {index} blocks "
                    f"({'exhaustive' if comp_exhaustive else 'sampled'} comparator), {len(new)} new "
                    f"({len(new_connected)} connected): params {row['new_params'][:8]}"
                )
                if normal and comp_exhaustive and res["mode"] == "exhaustive" and new_connected:
                    log(
                        "    !! a normal subgroup's coset lift is the regular lift over G/H, so an exhaustive "
                        "comparison must find every connected class: this is a bug in the sweep or the library "
                        "(disconnected ones come from entries whose terms cancel in G/H, which the comparator "
                        "never builds)"
                    )
                for sig, c in new_connected.items():
                    rec = new_classes.setdefault(
                        sig,
                        {
                            "group": name,
                            "subgroup_order": len(H),
                            "index": index,
                            "normal": normal,
                            "shape": list(shape),
                            "n": c["n"],
                            "k": c["k"],
                            "w": c["w"],
                            "A": c["A"],
                            "B": c["B"],
                            "subgroup": sub_gens,
                            "degree": degree,
                            "generators": [list(g) for g in gens],
                            "fingerprints": sorted(c["fingerprints"]),
                        },
                    )
    log(f"phase A done in {time.time() - t0:.0f} s: {len(new_classes)} new connected WL classes across all coset lifts")

    def dump(payload, name):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o))

    dump({"comparators": comp_stats, "coset_rows": rows}, "phase_a.json")
    dump({sig: rec for sig, rec in new_classes.items()}, "new_classes.json")

    if args.skip_gate or not new_classes:
        return 0
    return gate_classes(new_classes, args, log, t0)


def gate_classes(new_classes, args, log, t0):
    """Phase B: package and gate the classes, lowest k/n first (d is unknown before the search)."""
    import coordination  # noqa: E402
    import submit as S  # noqa: E402

    def dump(payload, name):
        with open(os.path.join(args.out, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, default=lambda o: sorted(o) if isinstance(o, (set, frozenset)) else str(o))

    order = sorted(new_classes.items(), key=lambda kv: (kv[1]["k"] / kv[1]["n"], kv[1]["n"]))[: args.gate_max]
    staging = coordination.staging_dir()
    gated = []
    for sig, rec in order:
        spec = perm_group_spec([tuple(g) for g in rec["generators"]], rec["degree"])
        state, _ = build(spec, rec["A"], rec["B"], rec["subgroup"])
        doc0 = state_doc(state)
        n = doc0["n"]
        HX = QV._matrix(doc0["checks"]["X"], n)
        HZ = QV._matrix(doc0["checks"]["Z"], n)
        group_order = (
            rec["group_order"]
            if "group_order" in rec
            else len(closure([tuple(g) for g in rec["generators"]], rec["degree"]))
        )
        construction = (
            f"code-calculus v0.3.2 L-LIFTED coset lift lift_{{G;H}}(A, B): G = {rec['group']} "
            f"(order {group_order}), "
            f"H of order {rec['subgroup_order']} and index {rec['index']} "
            f"({'normal' if rec['normal'] else 'non-normal'}), "
            f"A = {rec['A']}, B = {rec['B']} over F_2[G] with permutation generators "
            f"{rec['generators']} on {rec['degree']} points"
        )
        t1 = time.time()
        try:
            doc = S.make_submission(
                HX,
                HZ,
                name=f"[[{n},{rec['k']},?]] coset lifted product {rec['group']}/{rec['index']}",
                construction=construction,
                authors=["@vprusso"],
                family="lifted-product",
                trials=args.trials,
                seed=args.seed,
            )
        except Exception as exc:  # noqa: BLE001 -- a packaging failure is reported, never hidden
            gated.append(
                {
                    "sig": sig,
                    **{k: rec[k] for k in ("group", "index", "n", "k", "w")},
                    "error": f"make_submission: {exc}"[:200],
                }
            )
            log(f"  package failed for {rec['group']}/{rec['index']} n={n}: {exc}")
            continue
        d = doc["distance"]["d"]
        doc["name"] = f"[[{n},{rec['k']},{d}]] coset lifted product {rec['group']}/{rec['index']}"
        recipe = {
            "constructor": "machine.constructors.lifted_product",
            "params": {"group": spec, "A": rec["A"], "B": rec["B"], "subgroup": rec["subgroup"]},
            "library": "code-calculus v0.3.2",
        }
        path = coordination.unique_path(os.path.join(staging, f"{n}-{rec['k']}-{d}.json"), doc)
        try:
            S.save_submission(doc, path, spec=recipe)
            verdict, vpath = coordination.gate_and_record(path)
        except Exception as exc:  # noqa: BLE001
            gated.append(
                {
                    "sig": sig,
                    **{k: rec[k] for k in ("group", "index", "n", "k", "w")},
                    "d": d,
                    "error": f"stage/gate: {exc}"[:200],
                }
            )
            log(f"  stage/gate failed for {path}: {exc}")
            continue
        nov = verdict["gates"].get("novelty", {})
        row = {
            "sig": sig,
            **{k: rec[k] for k in ("group", "subgroup_order", "index", "normal", "shape", "n", "k", "w")},
            "d": d,
            "dX": doc["distance"]["X"]["value"],
            "dZ": doc["distance"]["Z"]["value"],
            "kd2_over_n": round(rec["k"] * d * d / n, 3),
            "passed": verdict["passed"],
            "refuted": verdict["gates"]["refute"].get("refuted"),
            "exact_duplicate_of": verdict["gates"]["dedup"].get("exact_duplicate_of"),
            "wl_equivalent_of": verdict["gates"]["dedup"].get("wl_equivalent_of"),
            "board_advancing": nov.get("board_advancing"),
            "dominated_by": nov.get("dominated_by"),
            "cell": nov.get("cell"),
            "staged": os.path.relpath(path, ROOT),
            "seconds": round(time.time() - t1, 1),
        }
        gated.append(row)
        log(
            f"  gated [[{n},{rec['k']},{d}]] w={rec['w']} {rec['group']}/{rec['index']}: passed={row['passed']} "
            f"advancing={row['board_advancing']} dominated_by={len(row['dominated_by'] or [])} "
            f"dup={row['exact_duplicate_of']} "
            f"wl={row['wl_equivalent_of']} [{row['seconds']}s]"
        )
        dump(gated, args.phase_b_name)
    log(
        f"phase B done in {time.time() - t0:.0f} s: {sum(1 for g in gated if g.get('passed'))} passed, "
        f"{sum(1 for g in gated if g.get('board_advancing'))} board-advancing of {len(gated)} gated"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

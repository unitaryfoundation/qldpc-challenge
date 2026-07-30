"""GAP ↔ Python bridge for systematic group enumeration.

Calls GAP as a subprocess (writes a GAP script to a temp file, invokes
``gap -q``, parses JSON output). No Python bindings required.

Key functions:
  all_groups_of_order(n)           — every group of order n up to isomorphism
  gap_coset_candidates(G, ...)     — subgroups H with large |N_G(H)/H|
  conjugacy_class_supports(mul, w) — supports that are unions of conj. classes

Caching: group catalogs for each order are memoized to disk (JSON) so
repeated sweeps don't re-enumerate.

Graceful fallback: if GAP is not installed, returns an empty list with a
warning — callers fall back to existing random samplers.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
#  Cache directory
# ---------------------------------------------------------------------------
_CACHE_DIR = Path(__file__).resolve().parent.parent / "candidates" / "_gap_cache"


def _cache_path(order):
    return _CACHE_DIR / f"groups_order_{order}.json"


def _save_cache(order, data):
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_cache_path(order), "w") as f:
        json.dump(data, f)


_CANONICAL_KEYS = {
    'order', 'index', 'description', 'abelian', 'solvable',
    'center_size', 'derived_length', 'nilpotency_class', 'cayley_table',
}
_KEY_FIXES = {
    'abelia': 'abelian', 'ceter_size': 'center_size',
    'derived_lenght': 'derived_length', 'nilpotcy_class': 'nilpotency_class',
}


def _load_cache(order):
    p = _cache_path(order)
    if p.exists():
        with open(p) as f:
            data = json.load(f)
        # Validate and fix any corrupt keys
        for g in data:
            for k in list(g.keys()):
                # Strip embedded newlines
                clean = k.strip().replace('\n', '').replace('\r', '')
                if clean != k:
                    g[clean] = g.pop(k)
                    k = clean
            # Apply known key fixes
            for bad, good in _KEY_FIXES.items():
                if bad in g and good not in g:
                    g[good] = g.pop(bad)
        return data
    return None


# ---------------------------------------------------------------------------
#  GAP availability
# ---------------------------------------------------------------------------
_GAP_BINARY = None


def _find_gap():
    global _GAP_BINARY
    if _GAP_BINARY is not None:
        return _GAP_BINARY
    # Try PATH first, then common install locations
    for candidate in ["gap", "/usr/local/bin/gap", "/opt/homebrew/bin/gap",
                       shutil.which("gap") or ""]:
        if candidate and shutil.which(candidate):
            _GAP_BINARY = candidate
            return _GAP_BINARY
    _GAP_BINARY = ""
    return _GAP_BINARY


def gap_available():
    """True if GAP is installed and callable."""
    return bool(_find_gap())


def _run_gap(script_body):
    """Run a GAP script and return its stdout. Raises RuntimeError on failure."""
    gap = _find_gap()
    if not gap:
        raise RuntimeError("GAP not found. Install via: brew install gap / conda install -c conda-forge gap")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".g", delete=False) as f:
        f.write(script_body)
        f.flush()
        tmp = f.name
    try:
        # TERM=dumb prevents GAP from opening an alternate terminal buffer
        # which causes subprocess to hang waiting for terminal input.
        # stdin=DEVNULL prevents GAP from reading stdin instead of the file.
        env = {**os.environ, "TERM": "dumb"}
        result = subprocess.run(
            [gap, "-q", tmp],
            capture_output=True, text=True, timeout=600, env=env,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            raise RuntimeError(f"GAP error (rc={result.returncode}):\n{result.stderr[:2000]}")
        return result.stdout
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
#  GAP script: enumerate all groups of order n
# ---------------------------------------------------------------------------
_GAP_ENUMERATE_TEMPLATE = r"""
orders := {orders_list};
for n in orders do
    grps := AllSmallGroups(n);
    for i in [1..Length(grps)] do
        G := grps[i];
        iso := StructureDescription(G);
        abelian := IsAbelian(G);
        sz := Size(G);
        center_sz := Size(Centre(G));
        deriv := DerivedLength(G);
        if IsNilpotentGroup(G) then
            nilp := NilpotencyClassOfGroup(G);
        else
            nilp := -1;
        fi;
        solvable := IsSolvable(G);

        elts := AsList(G);
        N := Length(elts);
        idx := [];
        for k in [1..N] do
            idx[Position(elts, elts[k])] := k - 1;
        od;
        mul := [];
        for a in [1..N] do
            row := [];
            for b in [1..N] do
                Add(row, idx[Position(elts, elts[a] * elts[b])]);
            od;
            Add(mul, row);
        od;

        # Manual JSON output (one object per line)
        Print("{\"order\":", sz,
              ",\"index\":", i,
              ",\"description\":\"", iso, "\"",
              ",\"abelian\":", abelian,
              ",\"solvable\":", solvable,
              ",\"center_size\":", center_sz,
              ",\"derived_length\":", deriv,
              ",\"nilpotency_class\":", nilp,
              ",\"cayley_table\":[");
        for a in [1..N] do
            if a > 1 then Print(","); fi;
            Print("[");
            for b in [1..N] do
                if b > 1 then Print(","); fi;
                Print(mul[a][b]);
            od;
            Print("]");
        od;
        Print("]}\n");
    od;
od;
"""  # noqa: E501


def all_groups_of_order(*orders, use_cache=True):
    """Return all groups of the given orders as dicts with Cayley tables.

    Each dict has keys:
      order, index, description, abelian, solvable, center_size,
      derived_length, nilpotency_class, cayley_table (list-of-lists, 0-indexed)

    Returns [] if GAP is unavailable or returns no groups.
    """
    orders_list = ",".join(str(int(o)) for o in orders)
    result = []

    # Check cache first
    uncached = []
    for n in orders:
        if use_cache:
            cached = _load_cache(n)
            if cached is not None:
                result.extend(cached)
                continue
        uncached.append(n)

    if not uncached:
        return result

    if not gap_available():
        print("WARNING: GAP not available. Install via: brew install gap / "
              "conda install -c conda-forge gap", file=sys.stderr)
        return result

    uncached_str = "[" + ",".join(str(int(o)) for o in uncached) + "]"
    script = _GAP_ENUMERATE_TEMPLATE.replace("{orders_list}", uncached_str)
    try:
        raw = _run_gap(script)
        # GAP inserts newlines inside JSON objects. Strip all whitespace,
        # then split on }{ boundaries to separate individual JSON objects.
        flat = re.sub(r'\s+', '', raw)
        # Also strip stray newlines that may embed in JSON key names
        # (GAP Print can break mid-string on long descriptions)
        flat = flat.replace('\n', '').replace('\r', '')
        groups = []
        # Split on }{ to find individual JSON objects, add braces back
        parts = flat.split("}{")
        for i, part in enumerate(parts):
            s = part
            if not s.startswith("{"):
                s = "{" + s
            if not s.endswith("}"):
                s = s + "}"
            try:
                groups.append(json.loads(s))
            except json.JSONDecodeError:
                continue
        if not groups:
            print(f"WARNING: GAP returned no JSON for orders {uncached}", file=sys.stderr)
            return result
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"WARNING: GAP enumeration failed: {e}", file=sys.stderr)
        return result

    # Cache each order separately
    if use_cache:
        by_order = {}
        for g in groups:
            by_order.setdefault(g["order"], []).append(g)
        for o, gs in by_order.items():
            _save_cache(o, gs)

    result.extend(groups)
    return result


# ---------------------------------------------------------------------------
#  GAP script: subgroup lattice + normalizer quotients
# ---------------------------------------------------------------------------
_GAP_SUBGROUPS_TEMPLATE = r"""
grps := AllSmallGroups({order});
G := grps[{index}];
g_elts := AsList(G);
N_g := Length(g_elts);
g_idx := [];
for k in [1..N_g] do
    g_idx[Position(g_elts, g_elts[k])] := k - 1;
od;
subs := ConjugacyClassesSubgroups(G);
for cl in subs do
    H := Representative(cl);
    szH := Size(H);
    nrm := Normalizer(G, H);
    szN := Size(nrm);
    nrm_quot := szN / szH;
    if nrm_quot >= {min_nrm_quotient} then
        h_elts := AsList(H);
        n_elts := AsList(nrm);
        h_idx := [];
        for k in [1..Length(h_elts)] do
            Add(h_idx, g_idx[Position(g_elts, h_elts[k])]);
        od;
        n_idx := [];
        for k in [1..Length(n_elts)] do
            Add(n_idx, g_idx[Position(g_elts, n_elts[k])]);
        od;
        Print("{\"size_H\":", szH,
              ",\"size_N\":", szN,
              ",\"nrm_quotient\":", nrm_quot,
              ",\"num_conjugates\":", Size(cl),
              ",\"H_elements\":[");
        for j in [1..Length(h_idx)] do
            if j > 1 then Print(","); fi;
            Print(h_idx[j]);
        od;
        Print("]");
        Print(",\"N_elements\":[");
        for j in [1..Length(n_idx)] do
            if j > 1 then Print(","); fi;
            Print(n_idx[j]);
        od;
        Print("]}\n");
    fi;
od;
"""  # noqa: E501


def gap_coset_candidates(cayley_table, min_nrm_quotient=6, order=None, index=None):
    """For a group with the given Cayley table, find all subgroups H with
    |N_G(H)/H| >= min_nrm_quotient.

    Can be called two ways:
      gap_coset_candidates(cayley_table, min_nrm_quotient)  # unused (kept for compat)
      gap_coset_candidates(None, min_nrm_quotient, order=N, index=I)

    Returns a list of dicts, each with keys:
      size_H, size_N, nrm_quotient, num_conjugates, H_elements, N_elements

    Returns [] if GAP is unavailable or no subgroups qualify.
    """
    if not gap_available():
        print("WARNING: GAP not available for subgroup enumeration.", file=sys.stderr)
        return []

    if order is not None and index is not None:
        script = _GAP_SUBGROUPS_TEMPLATE.replace(
            "{order}", str(int(order))
        ).replace(
            "{index}", str(int(index))
        ).replace(
            "{min_nrm_quotient}", str(int(min_nrm_quotient))
        )
    else:
        # Fallback: skip (old API)
        return []

    try:
        raw = _run_gap(script)
        flat = re.sub(r'\s+', '', raw)
        results = []
        parts = flat.split("}{")
        for i, part in enumerate(parts):
            s = part
            if not s.startswith("{"):
                s = "{" + s
            if not s.endswith("}"):
                s = s + "}"
            try:
                results.append(json.loads(s))
            except json.JSONDecodeError:
                continue
        # Sort by normalizer quotient descending
        results.sort(key=lambda x: -x.get("nrm_quotient", 0))
        return results
    except (RuntimeError, json.JSONDecodeError) as e:
        print(f"WARNING: GAP subgroup enumeration failed: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
#  Python-side: conjugacy-class-invariant supports (no GAP needed)
# ---------------------------------------------------------------------------
def _conjugacy_classes_from_cayley(mul):
    """Compute conjugacy classes of a group from its Cayley table.

    Two elements are conjugate if they have the same cycle structure in the
    left-regular representation. This is a pure-Python fallback that doesn't
    need GAP.
    """
    N = mul.shape[0]
    # Compute conjugacy via union-find on the relation g ~ h*g*g^{-1}
    parent = list(range(N))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for g in range(N):
        # Find g^{-1}
        gi = int(np.where(mul[g] == 0)[0][0])
        for h in range(N):
            # Conjugate: g * h * g^{-1}
            conj = int(mul[g, int(mul[h, gi])])
            union(h, conj)

    classes = {}
    for h in range(N):
        root = find(h)
        classes.setdefault(root, []).append(h)
    return list(classes.values())


def conjugacy_class_supports(mul, weight, rng=None):
    """Generate supports that are unions of conjugacy classes.

    Yields ``(support_list, class_labels)`` tuples where support_list is a
    list of element indices forming a valid support of approximately the
    given weight, and class_labels describes which classes were used.
    """
    if rng is None:
        rng = np.random.default_rng()

    classes = _conjugacy_classes_from_cayley(mul)
    # Sort classes by size (prefer small classes for fine-grained weight control)
    classes.sort(key=len)

    # Try random combinations of classes to get close to the target weight
    for _ in range(200):
        chosen = []
        total = 0
        available = list(range(len(classes)))
        rng.shuffle(available)
        for ci in available:
            if total >= weight:
                break
            chosen.append(ci)
            total += len(classes[ci])

        if total >= weight:
            # Trim to exact weight by removing elements from the largest class
            support = []
            for ci in chosen:
                support.extend(classes[ci])
            if len(support) > weight:
                rng.shuffle(support)
                support = sorted(support[:weight])
            yield support, chosen
            break
    else:
        # Fallback: just pick random elements
        support = sorted(int(x) for x in rng.choice(mul.shape[0], size=weight, replace=False))
        yield support, []


# ---------------------------------------------------------------------------
#  Combined: enumerate groups + build 2BGA codes
# ---------------------------------------------------------------------------
def enumerate_2bga_candidates(orders, support_weights=(4, 5, 6),
                               num_random_supports=20, use_class_supports=True,
                               seed=0):
    """Enumerate groups in the given orders and yield 2BGA candidate triples.

    Yields ``(spec, HX, HZ)`` triples compatible with ``search.screen()``.
    For each group, generates both random supports and conjugacy-class-invariant
    supports (if use_class_supports is True).
    """
    from group_algebra import build_2bga

    groups = all_groups_of_order(*orders)
    if not groups:
        return

    rng = np.random.default_rng(seed)

    for g_info in groups:
        order = g_info["order"]
        cayley = np.array(g_info["cayley_table"], dtype=np.int64)
        desc = g_info["description"]
        abelian = g_info["abelian"]

        for w in support_weights:
            if w >= order:
                continue

            # Random supports
            for _ in range(num_random_supports):
                a = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                b = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                try:
                    HX, HZ = build_2bga(cayley, a, b)
                except Exception:
                    continue
                spec = {
                    "family": "2bga-gap",
                    "group_order": order,
                    "group_description": desc,
                    "support_type": "random",
                    "weight": w,
                    "a": a, "b": b,
                }
                yield (spec, HX, HZ)

            # Conjugacy-class-invariant supports
            if use_class_supports and not abelian:
                for support_a, classes_a in conjugacy_class_supports(cayley, w, rng):
                    for support_b, classes_b in conjugacy_class_supports(cayley, w, rng):
                        try:
                            HX, HZ = build_2bga(cayley, support_a, support_b)
                        except Exception:
                            continue
                        spec = {
                            "family": "2bga-gap",
                            "group_order": order,
                            "group_description": desc,
                            "support_type": "conj-class",
                            "weight": w,
                            "a": support_a, "b": support_b,
                            "classes_a": classes_a, "classes_b": classes_b,
                        }
                        yield (spec, HX, HZ)


def enumerate_coset_candidates(orders, min_nrm_quotient=6,
                                support_weights=(3, 4, 5),
                                num_random_supports=20, seed=0):
    """Enumerate coset-code candidates using GAP subgroup lattices.

    Yields ``(spec, HX, HZ)`` triples for the coset construction.
    For each (G, H) pair with large normalizer quotient, builds coset codes
    with random supports.
    """
    from coset import build_coset, normalizer
    from group_algebra import build_2bga

    groups = all_groups_of_order(*orders)
    if not groups:
        return

    rng = np.random.default_rng(seed)

    for g_info in groups:
        order = g_info["order"]
        cayley = np.array(g_info["cayley_table"], dtype=np.int64)
        desc = g_info["description"]

        if g_info["abelian"]:
            continue  # skip abelian (already covered by existing samplers)

        # Use GAP to find subgroups with large normalizer quotients
        subgroups = gap_coset_candidates(g_info["cayley_table"], min_nrm_quotient)
        if not subgroups:
            continue

        for sub in subgroups:
            H = sub["H_elements"]
            N_G_H = sub["N_elements"]
            nrm_q = sub["nrm_quotient"]
            m = len(set(int(cayley[h1, h2]) for h1 in H for h2 in H))  # |H|
            m_cosets = order // m  # [G:H]
            n = 2 * m_cosets

            # Pick support weights bounded by coset space size
            valid_weights = [w for w in support_weights if w < m_cosets]
            if not valid_weights:
                continue

            for w in valid_weights:
                for _ in range(num_random_supports):
                    a = sorted(int(x) for x in rng.choice(order, size=w, replace=False))
                    b = sorted(int(x) for x in rng.choice(N_G_H, size=min(w, len(N_G_H)), replace=False))
                    try:
                        HX, HZ = build_coset(cayley, H, a, b, check_normalizer=False)
                    except Exception:
                        continue
                    if HX.shape[1] == 0 or HX.shape[0] == 0:
                        continue
                    spec = {
                        "family": "2bga-coset-gap",
                        "group_order": order,
                        "group_description": desc,
                        "subgroup_size": len(H),
                        "coset_index": m_cosets,
                        "nrm_quotient": nrm_q,
                        "weight": w,
                        "a": a, "b": b,
                    }
                    yield (spec, HX, HZ)


if __name__ == "__main__":
    print(f"GAP available: {gap_available()}")

    if gap_available():
        # Quick test: enumerate groups of order 12
        groups = all_groups_of_order(12)
        print(f"\nGroups of order 12: {len(groups)}")
        for g in groups:
            print(f"  [{g['index']}] {g['description']}  "
                  f"abelian={g['abelian']} solvable={g['solvable']} "
                  f"|Z(G)|={g['center_size']} |D(G)|={g['derived_length']}")

        # Quick test: subgroup lattice for D12
        if len(groups) >= 4:
            g = groups[3]  # D12
            subs = gap_coset_candidates(None, min_nrm_quotient=2,
                                         order=g["order"], index=g["index"])
            print(f"\nSubgroups with |N_G(H)/H| >= 2 for {g['description']}:")
            for s in subs[:10]:
                print(f"  |H|={s['size_H']}  |N_G(H)|={s['size_N']}  "
                      f"|N_G(H)/H|={s['nrm_quotient']}  "
                      f"#conj={s['num_conjugates']}")

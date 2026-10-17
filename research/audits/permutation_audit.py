#!/usr/bin/env python3
"""Decide, where it can be decided, the permutation equivalences the gate only flags (issue #3427).

The gate has two dedup outcomes, an identical fingerprint and a shared
Weisfeiler-Leman (WL) signature, and everything between them is a human. This
audit runs over every pair of board entries that share a WL signature with
different fingerprints, and over the literature matches recorded in
`research/provenance/derived.json`, and reports one of four verdicts per pair:

* `equivalent`: a qubit permutation carries the first entry's X and Z row
  spaces onto the second's (optionally after an X/Z swap). The permutation is
  the evidence, found by nauty's canonical form of the typed Tanner graph
  (`research/provenance/iso_common.py`) or, for small codes, of the
  basis-independent hypergraph of all low-weight row-space vectors, and
  re-verified here by row-space mapping (`permutation_equivalence.check_pair`)
  with the ledger's negative control (one extra transposition must fail).
* `inequivalent`: a basis-independent invariant differs in both orientations:
  the ranks, the dimension of the intersection of the X and Z row spaces, or
  the exact count of row-space vectors of weight at most the check weight,
  which is enumerable when the rank is small. Sound; no permutation exists.
* `gb_family_no`: both entries are genuine cyclic two-block (generalized
  bicycle) codes and `verify/two_block_equivalence.py` finds no unit map,
  shift, or block swap carrying one onto the other. This is the family
  decider's verdict, the one the board already acts on; it is not a proof
  against permutations outside that group of maps.
* `undecided`: the invariants agree, the Tanner graphs are not isomorphic, and
  the row space is too large to enumerate. Nothing here says the pair is one
  code or two.

Equivalent pairs with different claimed distances are flagged under
`distance_conflict`: the lighter entry's witness transports onto the heavier
entry, so the heavier claim is over-stated by the difference (issue #1651's
shape).

The literature half rebuilds each 2BGA match from its archive row on the
committed GAP tables under `research/kit/groups/`, fetches each QECDB match
from `https://qecdb.org/api/codes/<id>` (and keeps the fetched rows in the
output so the trail does not depend on the database staying up), and skips
the Wang-Pryadko rows, whose index id carries no polynomials.

Nothing here is a gate input. The output is a JSON record under
`research/audits/`; `recheck` re-verifies every recorded permutation from
the blob hashes it cites, as `permutation_equivalence.py` does for its ledger.

    uv run --extra research python research/audits/permutation_audit.py run \
        --out research/audits/permutation_audit-<date>.json
    uv run --extra research python research/audits/permutation_audit.py recheck \
        research/audits/permutation_audit-<date>.json
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
for rel in ("verify", os.path.join("research", "provenance"), os.path.join("research", "kit"), HERE):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

import gf2  # noqa: E402
import iso_common as I  # noqa: E402
import numpy as np  # noqa: E402
import permutation_equivalence as PE  # noqa: E402
import qldpc_verify as V  # noqa: E402
import two_block_equivalence as TB  # noqa: E402

AUDIT_VERSION = 1
# The 41 submissions issue #1204 found isomorphic to a published code, the
# literature half of #3427's audit. `run --all-literature` widens this to every
# `literature` row of derived.json.
ISSUE_1204_MATCHES = (
    "214-2-25 394-2-30 422-2-31 454-2-33 "
    "60-4-8 64-18-8 70-8-10 72-8-10 72-10-9 84-2-9 96-4-10 48-4-8 56-6-7 72-8-7 80-9-9 196-12-17 "
    "15-7-3 34-2-7 40-2-8 40-6-4 40-10-4 40-12-4 42-6-6 42-10-4 42-12-4 45-9-3 45-16-4 50-2-9 50-10-4 "
    "50-18-4 51-16-5 54-2-9 54-6-7 54-8-6 54-20-4 57-18-4 58-16-3 73-37-6 85-37-5 96-18-4 96-34-4").split()
# 2**rank row-space vectors are enumerated exactly below this; above it the
# low-weight enumerator and the hypergraph encoding are skipped.
ENUM_LIMIT = 2 ** 20
QECDB_API = "https://qecdb.org/api/codes/{}"


# -- codes -------------------------------------------------------------------

def code_from_doc(slug, doc):
    return I.Code(slug, int(doc["n"]), doc["checks"]["X"], doc["checks"]["Z"],
                  {"k": doc.get("k"), "d": (doc.get("distance") or {}).get("d")})


def code_from_matrices(name, HX, HZ):
    sup = lambda H: [[int(q) for q in np.nonzero(r)[0]] for r in np.asarray(H)]  # noqa: E731
    return I.Code(name, int(np.asarray(HX).shape[1]), sup(HX), sup(HZ))


def dense(code):
    return I.dense(code.X, code.n).astype(np.int8), I.dense(code.Z, code.n).astype(np.int8)


def blob_sha(path):
    return subprocess.check_output(["git", "hash-object", path], cwd=ROOT, text=True).strip()


# -- invariants ----------------------------------------------------------------

def invariants(code):
    """Return the basis-independent invariants of ``code``, oriented (X, Z).

    The ranks, the dimension of the intersection of the row spaces, and the
    exact low-weight enumerators when the rank allows.
    """
    HX, HZ = dense(code)
    rx, rz = gf2.rank(HX), gf2.rank(HZ)
    inter = V.css_row_space_intersection_dimension(HX, HZ, rx, rz)
    X, Z = code.normalized()
    wmax = code.max_weight()
    lowx = I.low_weight_enumerator(X, wmax, limit=ENUM_LIMIT)
    lowz = I.low_weight_enumerator(Z, wmax, limit=ENUM_LIMIT)
    return {"n": code.n, "rank_X": rx, "rank_Z": rz, "intersection": inter,
            "wmax": wmax, "low_X": lowx, "low_Z": lowz}


def _oriented(inv, swap):
    if not swap:
        return (inv["rank_X"], inv["rank_Z"], inv["low_X"], inv["low_Z"])
    return (inv["rank_Z"], inv["rank_X"], inv["low_Z"], inv["low_X"])


def invariants_separate(ia, ib):
    """Name the invariant that differs in both orientations, or None."""
    if ia["n"] != ib["n"]:
        return "n"
    if ia["intersection"] != ib["intersection"]:
        return "intersection dimension"
    reasons = []
    for swap in (False, True):
        a, b = _oriented(ia, swap), _oriented(ib, swap)
        if (a[0], a[1]) != (b[0], b[1]):
            reasons.append("ranks")
            continue
        wmax = min(ia["wmax"], ib["wmax"])
        la, lb = a[2], b[2]
        lza, lzb = a[3], b[3]
        if la is not None and lb is not None and la[:wmax + 1] != lb[:wmax + 1]:
            reasons.append("low-weight enumerator of the X row space")
            continue
        if lza is not None and lzb is not None and lza[:wmax + 1] != lzb[:wmax + 1]:
            reasons.append("low-weight enumerator of the Z row space")
            continue
        return None                                   # this orientation is not refuted
    return " / ".join(reasons)


# -- the decision --------------------------------------------------------------

def rowspace_vectors(vecs, wmax):
    """Every row-space vector of weight <= wmax, or None past ENUM_LIMIT."""
    basis, piv = [], {}
    for v in vecs:
        w = v
        while w:
            h = w.bit_length() - 1
            if h in piv:
                w ^= piv[h]
            else:
                piv[h] = w
                basis.append(w)
                break
    if 2 ** len(basis) > ENUM_LIMIT:
        return None
    out, cur = [], 0
    for g in range(1, 2 ** len(basis)):
        cur ^= basis[(g & -g).bit_length() - 1]
        if cur.bit_count() <= wmax:
            out.append(cur)
    return out


def hypergraph_code(code, wmax):
    """Return the basis-independent encoding of ``code``, or None.

    All row-space vectors of weight <= wmax as the generating set, when they
    are enumerable and span the row space.
    """
    X, Z = code.normalized()
    lx, lz = rowspace_vectors(X, wmax), rowspace_vectors(Z, wmax)
    if lx is None or lz is None:
        return None
    if I.rank_ints(lx) != I.rank_ints(X) or I.rank_ints(lz) != I.rank_ints(Z):
        return None
    return I.Code(code.id + "@hyper", code.n, I.ints_to_rows(lx), I.ints_to_rows(lz))


def find_permutation(a, b):
    """(perm, swap, how) from the Tanner graph, else from the hypergraph, else None."""
    for swap in (False, True):
        perm = I.nauty_permutation(a, b, swap=swap)
        if perm is not None:
            return [perm[i] for i in range(a.n)], swap, "tanner"
    wmax = max(a.max_weight(), b.max_weight())
    ha, hb = hypergraph_code(a, wmax), hypergraph_code(b, wmax)
    if ha is not None and hb is not None:
        for swap in (False, True):
            perm = I.nauty_permutation(ha, hb, swap=swap)
            if perm is not None:
                return [perm[i] for i in range(a.n)], swap, "hypergraph"
        return None, None, "hypergraph-no"
    return None, None, None


def decide(a, b, doc_a, doc_b):
    """One pair's verdict with its evidence."""
    t0 = time.monotonic()
    out = {"first": a.id, "second": b.id, "n": a.n}
    ia, ib = invariants(a), invariants(b)
    out["invariants"] = {"first": ia, "second": ib}
    sep = invariants_separate(ia, ib)
    if sep:
        out.update(verdict="inequivalent", reason=f"{sep} differs in both orientations")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    perm, swap, how = find_permutation(a, b)
    if perm is not None:
        ok, detail = PE.check_pair(doc_a, doc_b, perm, swap=swap)
        if not ok:
            out.update(verdict="undecided", reason=f"{how} isomorphism did not verify on the row spaces", detail=detail)
        else:
            ctrl = PE.negative_control(doc_a, doc_b, perm) if not swap else None
            out.update(verdict="equivalent", permutation=perm, swap=swap, found_by=how,
                       row_spaces=detail,
                       negative_control={True: "a perturbed permutation fails",
                                         False: "skipped: the perturbation is an automorphism",
                                         None: "not run for a swapped pair"}[ctrl])
            da, db = a.meta.get("d"), b.meta.get("d")
            if da is not None and db is not None and da != db:
                out["distance_conflict"] = {"first_d": da, "second_d": db,
                                            "note": f"one code under two claims; the weight-{min(da, db)} witness "
                                                    f"transports, so the claim of {max(da, db)} is over-stated"}
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    if how == "hypergraph-no":
        out.update(verdict="inequivalent",
                   reason="the hypergraphs of all low-weight row-space vectors are not isomorphic "
                          "(basis-independent, so no permutation exists)")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    gb = None
    if TB.is_generalised_bicycle(doc_a) and TB.is_generalised_bicycle(doc_b):
        gb = TB.equivalent(doc_a, doc_b)
        if gb is None:
            out.update(verdict="gb_family_no",
                       reason="both are cyclic two-block codes and no unit map, shift, or block swap "
                              "carries one onto the other (verify/two_block_equivalence.py)")
        else:
            out.update(verdict="undecided",
                       reason=f"the two-block decider reports unit {gb[0]} (swap {gb[1]}) but no Tanner "
                              "isomorphism was found; left for a human")
        out["seconds"] = round(time.monotonic() - t0, 2)
        return out
    out.update(verdict="undecided",
               reason="invariants agree, Tanner graphs are not isomorphic, row space too large to enumerate")
    out["seconds"] = round(time.monotonic() - t0, 2)
    return out


# -- the board's WL clusters ------------------------------------------------

def wl_clusters():
    """Entries sharing a WL signature with different fingerprints, from the verifier's own reports."""
    by_sig = {}
    for e in V.board_reports(os.path.join(ROOT, "codes")):
        doc, rep = e["doc"], e["report"]
        if doc is None or rep is None:
            continue
        sig = (rep.get("signature") or {}).get("hash")
        by_sig.setdefault(sig, []).append((os.path.basename(e["path"])[:-5], rep.get("fingerprint"), doc))
    clusters = []
    for members in by_sig.values():
        if len({fp for _, fp, _ in members}) > 1:
            clusters.append(sorted(members, key=lambda m: m[0]))
    return sorted(clusters, key=lambda c: (c[0][2]["n"], c[0][0]))


def audit_board():
    pairs = []
    for members in wl_clusters():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                sa, _, da = members[i]
                sb, _, db = members[j]
                rec = decide(code_from_doc(sa, da), code_from_doc(sb, db), da, db)
                rec["first_blob"] = blob_sha(os.path.join(ROOT, "codes", sa + ".json"))
                rec["second_blob"] = blob_sha(os.path.join(ROOT, "codes", sb + ".json"))
                rec["k"] = da.get("k")
                pairs.append(rec)
                print(f"{rec['verdict']:13s} {sa} / {sb}  {rec.get('reason', rec.get('found_by', ''))}", flush=True)
    return pairs


# -- the literature matches ------------------------------------------------------

_TWO_BGA = re.compile(r"2bga:SmallGroup\((\d+),(\d+)\):a\[([\d, ]*)\]:b\[([\d, ]*)\]")


def rebuild_2bga(match_id):
    """(HX, HZ) of an archive row from its committed GAP table; identity implicit unless listed."""
    from group_algebra import build_2bga_small_group
    m = _TWO_BGA.match(match_id)
    order, gid = int(m.group(1)), int(m.group(2))

    def zero_based(text):
        idx = [int(x) - 1 for x in text.split(",") if x.strip()]
        return idx if 0 in idx else [0] + idx
    return build_2bga_small_group(order, gid, zero_based(m.group(3)), zero_based(m.group(4)))


def fetch_qecdb(record_id, fetch=None):
    """Fetch the record's H rows (Pauli strings) and parameters from the public API."""
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
    rec = fetch(QECDB_API.format(record_id))
    return {"id": record_id, "name": rec.get("name"), "n": rec.get("n"), "k": rec.get("k"),
            "css": rec.get("css"), "rows": rec["H"].split()}


def qecdb_matrices(rows):
    """CSS matrices from Pauli-string rows; a row mixing X and Z is refused."""
    n = len(rows[0])
    HX, HZ = [], []
    for r in rows:
        kinds = set(r) - {"I"}
        if kinds == {"X"}:
            HX.append([1 if c == "X" else 0 for c in r])
        elif kinds == {"Z"}:
            HZ.append([1 if c == "Z" else 0 for c in r])
        else:
            raise ValueError(f"row mixes {sorted(kinds)}; not a CSS generating set")
    return np.array(HX, dtype=np.int8).reshape(-1, n), np.array(HZ, dtype=np.int8).reshape(-1, n)


def audit_literature(fetch=None, slugs=ISSUE_1204_MATCHES):
    """Re-derive the index's literature matches for ``slugs`` (None: every literature row)."""
    with open(os.path.join(ROOT, "research", "provenance", "derived.json"), encoding="utf-8") as f:
        entries = json.load(f)["entries"]
    out = []
    for slug, ent in sorted(entries.items()):
        if ent.get("bucket") != "literature":
            continue
        if slugs is not None and slug not in slugs:
            continue
        path = os.path.join(ROOT, "codes", slug + ".json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        board = code_from_doc(slug, doc)
        for m in ent.get("matches", []):
            rec = {"slug": slug, "blob": blob_sha(path), "source": m.get("source"), "id": m.get("id"),
                   "ref": m.get("ref")}
            try:
                if m.get("source", "").startswith("lin_pryadko_2bga"):
                    HX, HZ = rebuild_2bga(m["id"])
                    lit = code_from_matrices(m["id"], HX, HZ)
                elif m.get("source") == "qecdb":
                    fetched = fetch_qecdb(m["id"].split(":", 1)[1], fetch)
                    rec["record"] = fetched
                    HX, HZ = qecdb_matrices(fetched["rows"])
                    lit = code_from_matrices(m["id"], HX, HZ)
                else:
                    rec.update(verdict="not_re_derived", reason="the index id carries no construction to rebuild from")
                    out.append(rec)
                    print(f"{rec['verdict']:13s} {slug} <- {m['id']}", flush=True)
                    continue
            except (FileNotFoundError, ValueError, KeyError, OSError) as e:
                rec.update(verdict="not_re_derived", reason=f"{type(e).__name__}: {e}")
                out.append(rec)
                print(f"{rec['verdict']:13s} {slug} <- {m['id']}  {rec['reason']}", flush=True)
                continue
            lit_doc = {"n": lit.n, "checks": {"X": lit.X, "Z": lit.Z}}
            perm, swap, how = find_permutation(lit, board)
            if perm is None:
                sep = invariants_separate(invariants(lit), invariants(board))
                rec.update(verdict="inequivalent" if sep else "undecided",
                           reason=f"{sep} differs" if sep else "no Tanner isomorphism and the invariants agree")
            else:
                ok, detail = PE.check_pair(lit_doc, doc, perm, swap=swap)
                rec.update(verdict="equivalent" if ok else "undecided", permutation=perm, swap=swap,
                           found_by=how, row_spaces=detail,
                           literature_n=lit.n, literature_k=lit.k())
            out.append(rec)
            print(f"{rec['verdict']:13s} {slug} <- {m['id']}", flush=True)
    return out


# -- the record and its re-check --------------------------------------------------

def run(out_path, fetch=None, all_literature=False):
    t0 = time.monotonic()
    board = audit_board()
    lit = audit_literature(fetch, slugs=None if all_literature else ISSUE_1204_MATCHES)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    record = {
        "audit_version": AUDIT_VERSION,
        "issue": 3427,
        "date": datetime.date.today().isoformat(),
        "head": head,
        "literature_scope": ("every literature row of derived.json" if all_literature
                             else "the 41 matches of issue #1204"),
        "semantics": "permutation[i] = j means qubit i of the first code is qubit j of the second; equivalence "
                     "means the permuted X and Z row spaces of the first equal those of the second, after an "
                     "X/Z swap when swap is true",
        "counts": {
            "board_pairs": len(board),
            "board": {v: sum(1 for p in board if p["verdict"] == v)
                      for v in ("equivalent", "inequivalent", "gb_family_no", "undecided")},
            "literature_matches": len(lit),
            "literature": {v: sum(1 for p in lit if p["verdict"] == v)
                           for v in ("equivalent", "inequivalent", "undecided", "not_re_derived")},
        },
        "board_pairs": board,
        "literature": lit,
        "seconds": round(time.monotonic() - t0, 1),
    }
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(record, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps(record["counts"], indent=1))
    return record


def recheck(path):
    """Re-verify every recorded equivalence from the blob hashes it cites."""
    with open(path, encoding="utf-8") as f:
        rec = json.load(f)
    failures = 0
    for p in rec["board_pairs"]:
        if p["verdict"] != "equivalent":
            continue
        a, b = PE.load_blob(p["first_blob"]), PE.load_blob(p["second_blob"])
        ok, detail = PE.check_pair(a, b, p["permutation"], swap=p.get("swap", False))
        failures += 0 if ok else 1
        print(f"{'EQUIVALENT' if ok else 'NOT EQUIVALENT'}  {p['first']} -> {p['second']}  "
              f"X {detail.get('X')}  Z {detail.get('Z')}")
    for p in rec["literature"]:
        if p["verdict"] != "equivalent":
            continue
        board = PE.load_blob(p["blob"])
        if p["source"] == "qecdb":
            HX, HZ = qecdb_matrices(p["record"]["rows"])
        else:
            HX, HZ = rebuild_2bga(p["id"])
        lit = code_from_matrices(p["id"], HX, HZ)
        ok, detail = PE.check_pair({"n": lit.n, "checks": {"X": lit.X, "Z": lit.Z}}, board,
                                   p["permutation"], swap=p.get("swap", False))
        failures += 0 if ok else 1
        print(f"{'EQUIVALENT' if ok else 'NOT EQUIVALENT'}  {p['id']} -> {p['slug']}  "
              f"X {detail.get('X')}  Z {detail.get('Z')}")
    print(f"{failures} failure(s)")
    return failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="audit the board's WL clusters and the literature matches")
    r.add_argument("--out", default=os.path.join(HERE, f"permutation_audit-{datetime.date.today().isoformat()}.json"))
    r.add_argument("--all-literature", action="store_true",
                   help="re-derive every literature row of derived.json, not only the 41 of issue #1204")
    c = sub.add_parser("recheck", help="re-verify the permutations a record carries")
    c.add_argument("record")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run(args.out, all_literature=args.all_literature)
        return 0
    return 1 if recheck(args.record) else 0


if __name__ == "__main__":
    sys.exit(main())

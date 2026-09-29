"""Vendored from this project's `novelty` working repository (see iso_common.py).

Isomorphism-level check: board codes against literature codes with
matrices, and board codes against each other. Writes isomorphism_matches.csv.

Equivalence tested (see common.py): permutation equivalence of the *given
generating sets*, decided exactly with nauty's canonical form of the typed
Tanner graph (qubit / X-check / Z-check), after dropping zero and duplicate
rows. A match is then re-verified by mapping the row spaces with the
recovered qubit permutation (verify_permutation), which is the definition of
code equivalence itself. Matches are also sought up to a global X/Z swap.

A non-match is NOT a proof of inequivalence: two different sparse generating
sets of the same stabilizer group can have non-isomorphic Tanner graphs.
Candidate pairs are restricted to equal (n, k) and equal (rank_X, rank_Z)
up to swap, which are necessary conditions.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iso_common import (DATA, HERE, Code, load_board_codes, iter_literature_matrices,  # noqa: E402
                    nauty_certificate, nauty_permutation, verify_permutation,
                    signature, signature_swapped)

FIELDS = ["board_slug", "board_n", "board_k", "board_d", "board_w", "board_family",
          "board_novelty", "on_frontier_now", "match_kind", "other_id", "other_source",
          "other_d", "other_w", "xz_swapped", "permutation_verified"]


def board_certificates(codes):
    certs = {}
    for slug, c in codes.items():
        certs[slug] = (nauty_certificate(c, swap=False), nauty_certificate(c, swap=True))
    return certs


def main():
    t0 = time.time()
    codes = load_board_codes()
    meta = {s: dict(c.meta, n=c.n) for s, c in codes.items()}
    certs = board_certificates(codes)
    t_board = time.time() - t0
    # index: plain certificate -> slugs
    by_cert = defaultdict(list)
    for slug, (c0, c1) in certs.items():
        by_cert[c0].append(slug)
    rows = []
    # board vs board
    seen_pairs = set()
    for slug, (c0, c1) in certs.items():
        for other in by_cert.get(c0, []):
            if other != slug and (other, slug) not in seen_pairs:
                seen_pairs.add((slug, other))
                perm = nauty_permutation(codes[slug], codes[other])
                ok = perm is not None and verify_permutation(codes[slug], codes[other], perm)
                rows.append(_row(slug, meta[slug], "board", other, "board", meta[other]["d"],
                                 meta[other]["w"], False, ok))
        if c1 != c0:
            for other in by_cert.get(c1, []):
                if other != slug and (other, slug) not in seen_pairs:
                    seen_pairs.add((slug, other))
                    perm = nauty_permutation(codes[slug], codes[other], swap=True)
                    ok = perm is not None and verify_permutation(codes[slug], codes[other], perm, swap=True)
                    rows.append(_row(slug, meta[slug], "board", other, "board", meta[other]["d"],
                                     meta[other]["w"], True, ok))
    # board vs literature
    nk = defaultdict(list)
    for slug, c in codes.items():
        nk[(c.n, c.meta["k"])].append(slug)
    # cheap necessary-condition prefilter: generating-set signature
    # (n, rank_X, rank_Z, row-weight multisets, qubit-degree multisets),
    # in either X/Z orientation, must match some board code before nauty runs
    board_sigs = set()
    for slug, c in codes.items():
        sg = signature(c)
        board_sigs.add(sg)
        board_sigs.add(signature_swapped(sg))
    n_lit = n_cand = n_sig = 0
    lit_by_cert = defaultdict(list)
    lit_meta = {}
    t1 = time.time()
    for lc in iter_literature_matrices():
        n_lit += 1
        slugs = nk.get((lc.n, lc.meta["k"]))
        if not slugs:
            continue
        n_cand += 1
        if signature(lc) not in board_sigs:
            continue
        n_sig += 1
        if n_sig % 200 == 0:
            print(f"  {n_sig} signature-matched literature codes so far ({time.time()-t1:.0f}s)", flush=True)
        cert = nauty_certificate(lc)
        lit_by_cert[cert].append(lc.id)
        lit_meta[lc.id] = {"source": lc.meta["source"], "d": lc.meta.get("d"), "w": lc.meta.get("w"),
                           "code": lc}
    for slug, (c0, c1) in certs.items():
        for swapped, cert in ((False, c0), (True, c1)):
            if swapped and c1 == c0:
                continue
            for lid in lit_by_cert.get(cert, []):
                if lid == f"board-baseline:{slug}":
                    continue  # the code's own baseline entry
                lm = lit_meta[lid]
                perm = nauty_permutation(codes[slug], lm["code"], swap=swapped)
                ok = perm is not None and verify_permutation(codes[slug], lm["code"], perm, swap=swapped)
                rows.append(_row(slug, meta[slug], "literature", lid, lm["source"], lm["d"], lm["w"],
                                 swapped, ok))
    out = os.path.join(HERE, "isomorphism_matches.csv")
    with open(out, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=FIELDS)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    lit_rows = [r for r in rows if r["match_kind"] == "literature"]
    summ = {
        "board_codes": len(codes),
        "literature_matrices": n_lit,
        "literature_candidates_same_nk": n_cand,
        "literature_candidates_same_signature": n_sig,
        "board_board_pairs": len([r for r in rows if r["match_kind"] == "board"]),
        "board_slugs_with_board_duplicate": len({r["board_slug"] for r in rows if r["match_kind"] == "board"}
                                                 | {r["other_id"] for r in rows if r["match_kind"] == "board"}),
        "board_slugs_isomorphic_to_literature": len({r["board_slug"] for r in lit_rows}),
        "board_slugs_isomorphic_to_literature_non_baseline": len(
            {r["board_slug"] for r in lit_rows if r["other_source"] != "board_baseline"}),
        "unverified_matches": len([r for r in rows if not r["permutation_verified"]]),
        "time_board_certificates_s": round(t_board, 1),
        "time_total_s": round(time.time() - t0, 1),
    }
    json.dump(summ, open(os.path.join(HERE, "iso_summary.json"), "w"), indent=1)
    print(json.dumps(summ, indent=1))
    print("wrote", out)


def _row(slug, m, kind, other, source, od, ow, swapped, ok):
    return {"board_slug": slug, "board_n": m.get("n"), "board_k": m["k"], "board_d": m["d"],
            "board_w": m["w"], "board_family": m["family"], "board_novelty": m["novelty"],
            "on_frontier_now": m["on_frontier_now"], "match_kind": kind, "other_id": other,
            "other_source": source, "other_d": od, "other_w": ow, "xz_swapped": swapped,
            "permutation_verified": ok}


if __name__ == "__main__":
    main()

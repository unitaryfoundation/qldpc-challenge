"""Would this candidate be a record, and on which axes? A pre-filter for the gate.

The gate (`verify/validate_candidate.py`, section 4) is the authority: it returns
`gates.novelty.{board_advancing, advances_by, d_only_gain, d_only_peers}`. This
answers the same question from the candidate's parameters alone, BEFORE paying
for the gate, because the gate is the expensive step (QUICKSTART.md, "the gate
is the expensive step, so screen widely and spend it only on survivors"). The
rule itself is `research/kit/frontier.novelty`, one function shared with
`./qldpc submit`, `research/kit/promote.py`, and `research/kit/prescreen.py`,
so the three pre-filters and the gate cannot disagree on it.

What the rule gets right that a glance at the board does not:

* **the cell filter.** An existing entry is only a rival if it is on the same
  board (CSS vs stabilizer) and its weight class and locality class are both
  *stricter or equal* to the candidate's. So a w = 32 code is not a rival of a
  w = 8 candidate -- it lives in `weight-9plus`, a different cell. Ranking the
  board by kd^2/n and eyeballing it ignores this and answers a different
  question.
* **`dominators` vs `beaten`.** An entry the candidate loses to (all four axes
  against) kills `board_advancing`. An entry it wins on gives one `gains` list,
  and the union of those lists is `advances_by`.
* **the two d-only questions, kept apart exactly as TRACKS.md does.**
  `d_only_gain` is `advances_by == ["d"]` with a non-empty peer set -- the board
  yielded on nothing but d somewhere, over a non-placeholder entry. `d_only_peers`
  is per-entry: entries beaten while tied on n, k and w, excluding d = 1
  placeholders (a placeholder is not a suspect distance claim). A candidate can
  have d-only peers while not being d_only_gain, and the gate's label keys on
  the peers.

Two board readings. The quick one reads `codes/*.json` directly and is instant;
it derives a laid-out entry's locality class as `local-2d-bilayer` without
measuring the interaction radius, which is right for an `unrestricted`
candidate (every entry is a rival there) and can be wrong for a planar one. So a
planar candidate reads the board the way the gate does, through
`verify/validate_candidate._board_entries()` (the memoized structural pass; a
few seconds warm, minutes on a cold checkout), and `--exact-board` or `--quick`
overrides the choice either way.

This is a pre-filter, not evidence. It reads the board's *claimed* numbers, and
every one of them is itself an upper bound. Distance comes from the gate.

    uv run --extra research python research/does_it_advance.py --n 684 --k 4 --d 125 --w 8
    uv run --extra research python research/does_it_advance.py --n 684 --k 4 --d 125 --w 8 --json

The `--json` record (issue #7442; `schema_version` 1, the keys below are the
contract, additions never remove one):

    candidate   n, k, d, w, code_type, weight_class, locality_class, cell, kd2_over_n
    board       entries (count), source ("quick" or "gate"), codes (the directory read)
    novelty     the gate's block: board_advancing, advances_by, dominators (and the
                gate's own name for it, dominated_by), d_only_gain, d_only_peers,
                beaten ([descriptor, gains]); descriptors read "[[n,k,d]] w=6 slug.json"
    collisions  slug ("n-k-d"), slug_taken_by (the file in codes/, or null),
                suggested_slug (the first free suffix when it is taken),
                same_parameters (entries with this n, k, d), ties (same n, k, d, w
                in the candidate's cell, which share the frontier rather than block it)
"""

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "research", "kit"), os.path.join(ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import frontier  # noqa: E402

SCHEMA_VERSION = 1

# verbatim from verify/validate_candidate.py
WEIGHT_ORDER = {"weight-4": 0, "weight-6": 1, "weight-8": 2, "weight-9plus": 3}
LOCAL_ORDER = {"local-2d-single": 0, "local-2d-bilayer": 1, "unrestricted": 2}


def weight_class(w):
    if w <= 4:
        return "weight-4"
    if w <= 6:
        return "weight-6"
    if w <= 8:
        return "weight-8"
    return "weight-9plus"


def load_board(codes_dir=None):
    """Return one row per entry, read from the files: quick, and best-effort on a laid-out entry's locality class."""
    codes_dir = codes_dir or os.path.join(ROOT, "codes")
    out = []
    for path in sorted(glob.glob(os.path.join(codes_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        n, k = d.get("n"), d.get("k")
        dist = d.get("distance") or {}
        dd = dist.get("d")
        if dd is None and isinstance(dist.get("X"), dict):
            dd = dist["X"].get("value")
        if dd is None or n is None or k is None:
            continue
        checks = d.get("checks") or {}
        if "S" in checks:
            w = max(len(set(s.get("X", [])) | set(s.get("Z", []))) for s in checks["S"])
        elif "X" in checks:
            w = max({*(len(r) for r in checks["X"]), *(len(r) for r in checks["Z"])})
        else:
            continue
        w = int(w)
        loc = d.get("locality", {}) or {}
        lc = d.get("locality_class")
        if not lc:
            # derive as the verifier does for the no-layout case; with a layout
            # the class also needs the measured interaction radius, which we do
            # not recompute here, so a laid-out entry's class is best-effort
            lc = "unrestricted" if not loc.get("coordinates") else "local-2d-bilayer"
        out.append(
            {
                "n": int(n),
                "k": int(k),
                "d": int(dd),
                "w": w,
                "weight_class": d.get("weight_class") or weight_class(w),
                "locality_class": lc,
                "code_type": d.get("code_type", "CSS"),
                "name": d.get("name", os.path.basename(path)),
                "slug": os.path.basename(path)[:-5],
            }
        )
    return out


def gate_board():
    """Return the board rows the gate compares against, with every class as the verifier measures it."""
    import validate_candidate

    out = []
    for b in validate_candidate._board_entries():
        row = dict(b)
        row["slug"] = str(b["name"])[:-5] if str(b["name"]).endswith(".json") else b["name"]
        out.append(row)
    return out


def candidate_row(n, k, d, w, code_type="CSS", lc="unrestricted"):
    return {
        "n": n,
        "k": k,
        "d": d,
        "w": w,
        "code_type": code_type,
        "weight_class": weight_class(w),
        "locality_class": lc,
    }


def novelty(board, n, k, d, w, code_type="CSS", lc="unrestricted"):
    """Return the gate's novelty block for these parameters (`frontier.novelty`)."""
    return frontier.novelty(candidate_row(n, k, d, w, code_type, lc), board)


def suggested_slug(slug, codes_dir):
    """Return the first free suffixed slug, as ``./qldpc submit --slug`` would need it."""
    for letter in "bcdefghijklmnopqrstuvwxyz":
        if not os.path.exists(os.path.join(codes_dir, f"{slug}-{letter}.json")):
            return f"{slug}-{letter}"
    i = 2
    while os.path.exists(os.path.join(codes_dir, f"{slug}-{i}.json")):
        i += 1
    return f"{slug}-{i}"


def collisions(board, cand, codes_dir=None):
    """Return what on the board already sits at this candidate's name or parameters.

    ``slug_taken_by`` is the file ``codes/<n>-<k>-<d>.json`` when it exists,
    which is a distinct code that needs a suffixed slug (issue #5732) unless it
    is this very code (the gate's dedup decides that; parameters cannot).
    ``ties`` are entries at the same (n, k, d, w) in the candidate's cell: not
    dominators, the frontier is shared, but a second PR for the same point
    is what AGENTS.md's dedup rule forbids.
    """
    codes_dir = codes_dir or os.path.join(ROOT, "codes")
    slug = f"{cand['n']}-{cand['k']}-{cand['d']}"
    taken = os.path.join(codes_dir, f"{slug}.json")
    taken_by = os.path.relpath(taken, ROOT) if os.path.exists(taken) else None
    same = [frontier.describe(b) for b in board if (b["n"], b["k"], b["d"]) == (cand["n"], cand["k"], cand["d"])]
    ties = [
        frontier.describe(b)
        for b in board
        if frontier.in_cell(cand, b)
        and (b["n"], b["k"], b["d"], b.get("w")) == (cand["n"], cand["k"], cand["d"], cand["w"])
    ]
    return {
        "slug": slug,
        "slug_taken_by": taken_by,
        "suggested_slug": suggested_slug(slug, codes_dir) if taken_by else None,
        "same_parameters": same,
        "ties": ties,
    }


def record(board, cand, *, source, codes_dir=None):
    """Return the ``--json`` record: the candidate, the board read, the novelty block, and the collisions."""
    nov = novelty(board, cand["n"], cand["k"], cand["d"], cand["w"], cand["code_type"], cand["locality_class"])
    nov = dict(nov)
    nov["dominators"] = list(nov["dominated_by"])
    codes_dir = codes_dir or os.path.join(ROOT, "codes")
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": dict(cand, cell=nov["cell"], kd2_over_n=round(cand["k"] * cand["d"] ** 2 / cand["n"], 3)),
        "board": {"entries": len(board), "source": source, "codes": os.path.relpath(codes_dir, ROOT)},
        "novelty": nov,
        "collisions": collisions(board, cand, codes_dir),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--d", type=int, required=True)
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--code-type", default="CSS", choices=["CSS", "stabilizer"])
    ap.add_argument("--locality", default="unrestricted", choices=list(LOCAL_ORDER))
    ap.add_argument("--json", action="store_true", help="print the record documented in the module docstring")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--codes", default=None, help="the board directory (default codes/)")
    how = ap.add_mutually_exclusive_group()
    how.add_argument("--quick", action="store_true", help="read the files directly even for a planar candidate")
    how.add_argument("--exact-board", action="store_true", help="read the board as the gate does, every class measured")
    args = ap.parse_args(argv)

    exact = args.exact_board or (args.locality != "unrestricted" and not args.quick)
    if exact and args.codes:
        print("--exact-board reads the repository's own codes/; --codes is ignored", file=sys.stderr)
    board = gate_board() if exact else load_board(args.codes)
    cand = candidate_row(args.n, args.k, args.d, args.w, args.code_type, args.locality)
    rec = record(board, cand, source="gate" if exact else "quick", codes_dir=None if exact else args.codes)
    nov = rec["novelty"]
    eff = rec["candidate"]["kd2_over_n"]

    if args.json:
        print(json.dumps(rec, indent=1))
        return 0

    print(
        f"candidate [[{args.n},{args.k},{args.d}]] w={args.w} {args.code_type} "
        f"kd^2/n={eff:.3f}  cell={nov['cell'][0]} x {nov['cell'][1]}  (board: {rec['board']['source']})"
    )
    print(f"  board_advancing : {nov['board_advancing']}")
    print(f"  advances_by     : {nov['advances_by'] or '--'}")
    print(f"  d_only_gain     : {nov['d_only_gain']}   (advances_by == ['d'] and board_advancing)")
    print(f"  d_only_peers    : {len(nov['d_only_peers'])}")
    for desc in nov["d_only_peers"][: args.limit]:
        print(f"      tied on n,k,w with {desc}")
    if nov["dominators"]:
        print(f"  dominated_by ({len(nov['dominators'])}), first {args.limit}:")
        for desc in nov["dominators"][: args.limit]:
            print(f"      {desc}")
    print(f"  beaten entries  : {len(nov['beaten'])}  (axes: {nov['advances_by'] or '--'})")
    for desc, gains in nov["beaten"][: args.limit]:
        print(f"      {desc} on {'+'.join(gains)}")
    col = rec["collisions"]
    if col["slug_taken_by"]:
        print(
            f"  slug {col['slug']} is taken by {col['slug_taken_by']}; "
            f"a distinct code needs --slug {col['suggested_slug']}"
        )
    if col["ties"]:
        print(f"  ties at this point ({len(col['ties'])}): {', '.join(col['ties'][: args.limit])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

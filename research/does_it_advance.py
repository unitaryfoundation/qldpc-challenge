"""Would this candidate be a record, and on which axes? A pre-filter for the gate.

The gate (`verify/validate_candidate.py`, section 4) is the authority: it returns
`gates.novelty.{board_advancing, advances_by, d_only_gain, d_only_peers}`. This
mirrors that computation so a sweep can rank and drop candidates BEFORE paying
for the gate, because the gate is the expensive step (QUICKSTART.md, "the gate
is the expensive step, so screen widely and spend it only on survivors").

Mirrored, including the parts that are easy to get wrong:

* **the cell filter.** An existing entry is only a rival if it is on the same
  board (CSS vs stabilizer) and its weight class and locality class are both
  *stricter or equal* to the candidate's. So a w = 32 code is not a rival of a
  w = 8 candidate -- it lives in `weight-9plus`, a different cell. Ranking the
  board by kd^2/n and eyeballing it ignores this and answers a different
  question.
* **`dominators` vs `dominated`.** An entry the candidate loses to (all four
  axes against) kills `board_advancing`. An entry it wins on gives one `gains`
  list, and the union of those lists is `advances_by`.
* **the two d-only questions, kept apart exactly as TRACKS.md does.**
  `d_only_gain` is `advances_by == ["d"]` -- the board yielded on nothing but
  d anywhere. `d_only_peers` is per-entry: entries beaten while tied on n, k and
  w. A candidate can have d-only peers while not being d_only_gain, and the
  gate's label keys on the peers.

This is a pre-filter, not evidence. It reads the board's *claimed* numbers, and
every one of them is itself an upper bound. Distance comes from the gate.

    uv run --extra research python research/does_it_advance.py --n 684 --k 4 --d 125 --w 8
    uv run --extra research python research/does_it_advance.py --n 684 --k 4 --d 125 --w 8 --json
"""

import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def load_board():
    """(n, k, d, w, weight_class, locality_class, code_type, name) per entry."""
    out = []
    for path in sorted(glob.glob(os.path.join(ROOT, "codes", "*.json"))):
        try:
            with open(path) as fh:
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
            }
        )
    return out


def novelty(board, n, k, d, w, code_type="CSS", lc="unrestricted"):
    """Replicate validate_candidate's section 4. Returns the novelty dict."""
    wc = weight_class(w)
    dominators, dominated = [], []
    for b in board:
        if not (
            b["code_type"] == code_type
            and WEIGHT_ORDER.get(b["weight_class"], 9) <= WEIGHT_ORDER.get(wc, 9)
            and LOCAL_ORDER.get(b["locality_class"], 9) <= LOCAL_ORDER.get(lc, 9)
        ):
            continue  # not in this cell: neither rival nor beaten entry
        bw = b["w"]
        if (
            b["n"] <= n
            and b["k"] >= k
            and b["d"] >= d
            and bw <= w
            and (b["n"] < n or b["k"] > k or b["d"] > d or bw < w)
        ):
            dominators.append(b)
            continue
        gains = [
            ax for ax, better in (("n", b["n"] > n), ("k", b["k"] < k), ("d", b["d"] < d), ("w", bw > w)) if better
        ]
        if gains and b["n"] >= n and b["k"] <= k and b["d"] <= d and bw >= w:
            dominated.append((b, gains))

    board_advancing = not dominators
    advances_by = sorted({ax for _, gains in dominated for ax in gains})
    d_only_peers = [b for b, gains in dominated if gains == ["d"]]
    return {
        "cell": [wc, lc],
        "board": code_type,
        "board_advancing": board_advancing,
        "dominated_by": dominators,
        "advances_by": advances_by,
        "d_only_gain": bool(board_advancing) and advances_by == ["d"],
        "d_only_peers": d_only_peers,
        "beaten": dominated,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--d", type=int, required=True)
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--code-type", default="CSS", choices=["CSS", "stabilizer"])
    ap.add_argument("--locality", default="unrestricted", choices=list(LOCAL_ORDER))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    board = load_board()
    nov = novelty(board, args.n, args.k, args.d, args.w, code_type=args.code_type, lc=args.locality)
    eff = args.k * args.d * args.d / args.n

    if args.json:
        slim = dict(nov)
        slim["dominated_by"] = [f"{b['n']},{b['k']},{b['d']} w={b['w']} {b['name']}" for b in nov["dominated_by"]]
        slim["d_only_peers"] = [f"{b['n']},{b['k']},{b['d']} w={b['w']} {b['name']}" for b in nov["d_only_peers"]]
        slim["beaten"] = [[f"{b['n']},{b['k']},{b['d']}", gains] for b, gains in nov["beaten"]]
        print(
            json.dumps(
                {
                    "candidate": {"n": args.n, "k": args.k, "d": args.d, "w": args.w, "kd2_over_n": round(eff, 3)},
                    "novelty": slim,
                },
                indent=1,
            )
        )
        return

    print(
        f"candidate [[{args.n},{args.k},{args.d}]] w={args.w} {args.code_type} "
        f"kd^2/n={eff:.3f}  cell={nov['cell'][0]} x {nov['cell'][1]}"
    )
    print(f"  board_advancing : {nov['board_advancing']}")
    print(f"  advances_by     : {nov['advances_by'] or '--'}")
    print(f"  d_only_gain     : {nov['d_only_gain']}   (advances_by == ['d'] and board_advancing)")
    print(f"  d_only_peers    : {len(nov['d_only_peers'])}")
    for b in nov["d_only_peers"][: args.limit]:
        print(f"      tied on n,k,w with {b['name']} -> [[{b['n']},{b['k']},{b['d']}]]")
    if nov["dominated_by"]:
        print(f"  dominated_by ({len(nov['dominated_by'])}), first {args.limit}:")
        for b in nov["dominated_by"][: args.limit]:
            print(f"      [[{b['n']},{b['k']},{b['d']}]] w={b['w']} {b['name']}")
    print(f"  beaten entries  : {len(nov['beaten'])}  (axes: {nov['advances_by'] or '--'})")
    for b, gains in nov["beaten"][: args.limit]:
        print(f"      [[{b['n']},{b['k']},{b['d']}]] w={b['w']} on {'+'.join(gains)}  {b['name']}")


if __name__ == "__main__":
    main()

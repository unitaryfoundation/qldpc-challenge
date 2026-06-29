"""qldpc submit: one command from parity checks to a verified submission.

The friction in contributing used to be "read CONTRIBUTING.md, learn the JSON
schema, hand-write a distance witness, hope CI agrees." This collapses that into
a single command, the way ecdsa.fail does: you bring H_X and H_Z, the tool

  1. computes n, k (= n - rank H_X - rank H_Z) and the max check weight,
  2. searches for the lightest logical on each side (RIS) and records it as a
     self-certifying distance witness,
  3. assembles a schema-valid submission,
  4. runs the full trustless verifier locally (the same gate CI runs), and
  5. writes codes/<n>-<k>-<d>.json and prints the steps to open the PR
     (or opens it for you with --open-pr).

If verification fails, nothing is written: you see exactly which check failed
before anything leaves your machine.

Usage:
  uv run python cli/qldpc.py submit mycode.npz --authors @me
  uv run python cli/qldpc.py submit mycode.npz --authors @me "Jane Roe" \\
      --construction "bivariate bicycle (x^3+y+y^2, ...)" --model "Opus 4.8"
  ./qldpc submit mycode.npz --authors @me        # via the launcher shim

Input:
  .npz  with H_X and H_Z under keys hx/HX/H_X and hz/HZ/H_Z (dense 0/1 arrays
        or scipy sparse). Optional 'coords' (n x 2) for the 2d-local tracks.
  .json an existing draft carrying a checks block (re-verify / re-score it).
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "verify"))

import gf2                       # noqa: E402
import heuristic_distance as hd  # noqa: E402
from qldpc_verify import verify  # noqa: E402


# ----------------------------------------------------------------------------
# loading parity checks
# ----------------------------------------------------------------------------
def _as_dense_gf2(a):
    """A dense 0/1 numpy array from a dense or scipy-sparse matrix."""
    if hasattr(a, "toarray"):
        a = a.toarray()
    return (np.asarray(a) % 2).astype(np.uint8)


def _pick(d, names):
    for nm in names:
        if nm in d:
            return d[nm]
    return None


def load_checks(path):
    """Return (HX, HZ, coords_or_None). Accepts .npz (matrices) or .json
    (a draft with a checks block)."""
    if path.endswith(".json"):
        doc = json.load(open(path))
        n = doc["n"]
        HX = _matrix_from_supports(doc["checks"]["X"], n)
        HZ = _matrix_from_supports(doc["checks"]["Z"], n)
        coords = None
        if "locality" in doc:
            coords = np.asarray(doc["locality"]["coordinates"], dtype=float)
        return HX, HZ, coords, doc
    z = np.load(path, allow_pickle=True)
    HX = _pick(z, ("hx", "HX", "H_X", "Hx"))
    HZ = _pick(z, ("hz", "HZ", "H_Z", "Hz"))
    if HX is None or HZ is None:
        raise SystemExit(
            f"{path}: need H_X and H_Z arrays (keys hx/HX/H_X and hz/HZ/H_Z); "
            f"found {list(z.keys())}")
    HX, HZ = _as_dense_gf2(HX), _as_dense_gf2(HZ)
    coords = _pick(z, ("coords", "coordinates", "xy"))
    if coords is not None:
        coords = np.asarray(coords, dtype=float)
    return HX, HZ, coords, None


def _matrix_from_supports(supports, n):
    H = np.zeros((len(supports), n), dtype=np.uint8)
    for i, s in enumerate(supports):
        H[i, list(s)] = 1
    return H


def _supports(H):
    return [sorted(int(q) for q in np.where(row)[0]) for row in H]


# ----------------------------------------------------------------------------
# building the submission
# ----------------------------------------------------------------------------
def build_submission(HX, HZ, args):
    n = HX.shape[1]
    if HZ.shape[1] != n:
        raise SystemExit(f"H_X has {n} columns but H_Z has {HZ.shape[1]}")
    if bool(((HX @ HZ.T) % 2).any()):
        raise SystemExit("H_X H_Z^T != 0 over GF(2): not a CSS code "
                         "(check your matrices / ordering)")
    k = n - gf2.rank(HX) - gf2.rank(HZ)
    if k < 1:
        raise SystemExit(f"computed k={k}: no logical qubits, nothing to submit")
    wmax = int(max((row.sum() for row in np.vstack([HX, HZ])), default=0))

    # lightest logical on each side -> self-certifying distance upper bound.
    print(f"  building submission... n={n} k={k} w={wmax}", flush=True)
    print(f"  searching for distance witnesses ({args.trials} RIS trials)...",
          flush=True)
    dX, witX = hd.ris_min_logical(HX, HZ, trials=args.trials, seed=args.seed)
    dZ, witZ = hd.ris_min_logical(HZ, HX, trials=args.trials, seed=args.seed)
    if dX is None or dZ is None:
        raise SystemExit("RIS found no logical operator on one side; "
                         "cannot certify a distance")
    d = min(dX, dZ)
    print(f"  distance (RIS upper bound) d<={d}  (d_X<={dX}, d_Z<={dZ})",
          flush=True)

    dist = {
        "d": int(d),
        "X": {"value": int(dX), "confidence": "upper_bound",
              "witness": sorted(int(q) for q in np.where(witX)[0])},
        "Z": {"value": int(dZ), "confidence": "upper_bound",
              "witness": sorted(int(q) for q in np.where(witZ)[0])},
    }
    prov = {"authors": args.authors,
            "construction": args.construction or "contributed via qldpc submit",
            "origin": "submission",
            "date": args.date or datetime.date.today().isoformat()}
    if args.model:
        prov["model"] = args.model
    if args.notes:
        prov["notes"] = args.notes

    doc = {
        "schema_version": "0.1",
        "name": args.name or f"[[{n},{k},{d}]]",
        "code_type": "CSS",
        "n": n, "k": int(k),
        "checks": {"X": _supports(HX), "Z": _supports(HZ)},
        "distance": dist,
        "provenance": prov,
    }
    # Layer-2 family tag (optional). Track membership is computed by the verifier
    # from H and the layout, so the CLI no longer writes a self-declared tracks
    # field; provide a layout below and the locality class is derived.
    if args.family:
        doc["family"] = args.family
    if args._coords is not None:
        if len(args._coords) != n:
            raise SystemExit(f"coords has {len(args._coords)} rows, need n={n}")
        loc = {"coordinates": [[float(x), float(y)] for x, y in args._coords]}
        if args.layers:
            loc["layers"] = int(args.layers)
        doc["locality"] = loc
    return doc


# ----------------------------------------------------------------------------
# submit command
# ----------------------------------------------------------------------------
def cmd_submit(args):
    HX, HZ, coords, _draft = load_checks(args.code)
    if args.coords:                      # explicit coords file overrides
        cz = np.load(args.coords) if args.coords.endswith(".npz") else None
        coords = (_pick(cz, ("coords", "coordinates", "xy"))
                  if cz is not None else np.loadtxt(args.coords))
        coords = np.asarray(coords, dtype=float)
    args._coords = coords

    doc = build_submission(HX, HZ, args)

    print("  verifying (CSS / k / weight / witnesses / locality)...", flush=True)
    report = verify(doc, refute=True)
    for c in report["checks"]:
        if not c["ok"]:
            print(f"    FAIL  {c['check']}: {c['detail']}")
    if not report["ok"]:
        print("\nverification FAILED; nothing written. Fix the issues above.")
        return 1
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    print(f"  OK  verified. score kd^2/n = {round(k * d * d / n, 3)}")

    slug = f"{n}-{k}-{d}"
    out = os.path.join(args.out, f"{slug}.json")
    if args.dry_run:
        print(f"\n--dry-run: would write {out}")
        print(json.dumps(doc, indent=1)[:600] + " ...")
        return 0
    if os.path.exists(out) and not args.force:
        print(f"\n{out} already exists. Use --force to overwrite, or rename.")
        return 1
    os.makedirs(args.out, exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(f"  wrote {out}")

    if args.open_pr:
        return open_pr(slug, out)
    print("\nnext: open a PR with this file")
    print(f"  git checkout -b submit-{slug}")
    print(f"  git add {out}")
    print(f"  git commit -m 'Add [[{n},{k},{d}]]'")
    print(f"  git push -u origin submit-{slug}")
    print("  gh pr create --fill        (or use the link git push prints)")
    print("\nor re-run with --open-pr to do this automatically.")
    return 0


def open_pr(slug, out):
    n_k_d = slug.replace("-", ",")
    branch = f"submit-{slug}"
    cmds = [
        ["git", "checkout", "-b", branch],
        ["git", "add", out],
        ["git", "commit", "-m", f"Add [[{n_k_d}]]"],
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--fill"],
    ]
    for c in cmds:
        print(f"  $ {' '.join(c)}", flush=True)
        r = subprocess.run(c, cwd=_ROOT)
        if r.returncode != 0:
            print(f"  command failed ({r.returncode}); finish the remaining "
                  f"steps by hand.")
            return r.returncode
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="qldpc", description="qLDPC challenge submission tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="build, verify, score, and stage a code")
    s.add_argument("code", help=".npz with H_X/H_Z (+ optional coords) or a "
                                ".json draft")
    s.add_argument("--authors", nargs="+", required=True,
                   help="one or more: @github-handle and/or 'First Last'")
    s.add_argument("--construction", default="",
                   help="how the code was built (family, polynomials, search)")
    s.add_argument("--model", default="",
                   help="self-reported model that produced it, named to a specific "
                        "version, e.g. 'Claude Opus 4.8' (not a bare 'Claude'), or "
                        "'human' (claimed, not verified; the verifier requires a "
                        "version if a model is named)")
    s.add_argument("--notes", default="")
    s.add_argument("--date", default="",
                   help="submission date (YYYY-MM-DD); defaults to today")
    s.add_argument("--name", default="")
    s.add_argument("--family", choices=[
                       "bivariate-bicycle", "generalized-bicycle", "2bga-coset",
                       "hypergraph-product", "lifted-product", "balanced-product",
                       "quantum-tanner", "tile", "topological", "other"],
                   help="construction family tag (a filter, not a ranking; "
                        "track membership is computed from H and the layout)")
    s.add_argument("--coords", default="",
                   help="coordinates file (.npz key coords, or whitespace .txt); "
                        "the verifier derives the 2d-local class from it")
    s.add_argument("--layers", type=int, default=0,
                   help="physical layers for a 2d-local layout (2 = bilayer)")
    s.add_argument("--trials", type=int, default=20000,
                   help="RIS trials for the distance witness search")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", default=os.path.join(_ROOT, "codes"))
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing codes/<slug>.json")
    s.add_argument("--dry-run", action="store_true",
                   help="build and verify but do not write the file")
    s.add_argument("--open-pr", action="store_true",
                   help="create the branch, commit, push, and open the PR")
    s.set_defaults(func=cmd_submit)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

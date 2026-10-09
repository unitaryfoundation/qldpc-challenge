r"""qldpc submit: one command from parity checks to a verified submission.

The friction in contributing used to be "read CONTRIBUTING.md, learn the JSON
schema, hand-write a distance witness, hope CI agrees." This collapses that into
a single command, the way ecdsa.fail does: you bring H_X and H_Z, the tool

  1. computes n, k (= n - rank H_X - rank H_Z) and the max check weight,
  2. searches for the lightest logical on each side (RIS) and records it as a
     self-certifying distance witness,
  3. assembles a schema-valid submission,
  4. runs the full trustless verifier locally (the same gate CI runs),
  5. generates the circuit tier (RFC 0001): memory_x and memory_z
     syndrome-extraction circuits on a schedule the code's structure supports
     (research/circuit_autogen.py), searches their detector error models for
     d_circ witnesses, and runs verify/circuit_verify.py on them; a code the
     generator cannot schedule within the tier's caps is submitted without
     circuits, and --circuits DIR brings your own,
  6. fills the PR body's "what frontier does this advance?" section by
     comparing against the current board (reusing the site's Pareto logic),
     and
  7. writes codes/<n>-<k>-<d>.json plus circuits/<n>-<k>-<d>/ and prints the
     steps to open the PR (or opens it for you with --open-pr).

If verification fails, nothing is written: you see exactly which check failed
before anything leaves your machine.

Usage:
  uv run python cli/qldpc.py submit mycode.npz --authors @me
  uv run python cli/qldpc.py submit mycode.npz --authors @me "Jane Roe" \
      --construction "bivariate bicycle (x^3+y+y^2, ...)" --model "Opus 4.8"
  ./qldpc submit mycode.npz --authors @me        # via the launcher shim
  ./qldpc submit mycode.npz --authors @me --no-circuit   # code tier only

Input:
  .npz  with H_X and H_Z under keys hx/HX/H_X and hz/HZ/H_Z (dense 0/1 arrays
        or scipy sparse). Optional 'coords' (n x 2) for the 2d-local tracks.
        A general stabilizer code instead carries its binary symplectic
        matrix S = (A | B) under key s/S (m x 2n), or its halves under a/A
        and b/B (m x n each). It is typed code_type "stabilizer": one
        Pauli-weight distance side P, no circuit tier, its own board.
  .json an existing draft carrying a checks block (re-verify / re-score it).
"""

import argparse
import datetime
import glob
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "verify"))
sys.path.insert(0, os.path.join(_ROOT, "site"))
sys.path.insert(0, os.path.join(_ROOT, "research"))
sys.path.insert(0, os.path.join(_ROOT, "research", "kit"))

import gf2  # noqa: E402
import heuristic_distance as hd  # noqa: E402

# Reuse the site's computed-cell + Pareto-frontier helpers so the PR body
# states exactly what the board will show (no drift between the two).
import coordination  # noqa: E402
from build import LOCALITY_LABEL, WEIGHT_LABEL, cells, pareto  # noqa: E402
from campaign import curve_from_summary, write_curve  # noqa: E402
from check_authorship import HANDLE  # noqa: E402
from qldpc_verify import is_css_up_to_local_clifford, verify  # noqa: E402


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
    """Return (HX, HZ, coords_or_None, draft_or_None).

    Accepts .npz (matrices) or .json (a draft with a checks block). For a
    general stabilizer code the pair is (A, B), the two halves of the
    symplectic matrix S = (A | B), and the returned draft (a dict with
    code_type "stabilizer", or None) tells build_submission which it got.
    """
    if path.endswith(".json"):
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}: not valid JSON ({e})")
        n = doc["n"]
        coords = None
        if "locality" in doc:
            coords = np.asarray(doc["locality"]["coordinates"], dtype=float)
        if doc.get("code_type") == "stabilizer":
            gens = doc["checks"]["S"]
            A = _matrix_from_supports([g["X"] for g in gens], n)
            B = _matrix_from_supports([g["Z"] for g in gens], n)
            return A, B, coords, doc
        HX = _matrix_from_supports(doc["checks"]["X"], n)
        HZ = _matrix_from_supports(doc["checks"]["Z"], n)
        return HX, HZ, coords, doc
    z = np.load(path, allow_pickle=True)
    coords = _pick(z, ("coords", "coordinates", "xy"))
    if coords is not None:
        coords = np.asarray(coords, dtype=float)
    S = _pick(z, ("s", "S"))
    A = _pick(z, ("a", "A"))
    B = _pick(z, ("b", "B"))
    if S is not None or A is not None or B is not None:
        if S is not None:
            S = _as_dense_gf2(S)
            if S.ndim != 2 or S.shape[1] % 2:
                raise SystemExit(f"{path}: key s must be an m x 2n matrix "
                                 f"(A | B); got shape {S.shape}")
            n = S.shape[1] // 2
            A, B = S[:, :n], S[:, n:]
        elif A is None or B is None:
            raise SystemExit(f"{path}: a stabilizer code needs both a and b "
                             f"(the X and Z halves of S), or s = (A | B); "
                             f"found {list(z.keys())}")
        else:
            A, B = _as_dense_gf2(A), _as_dense_gf2(B)
            if A.shape != B.shape:
                raise SystemExit(f"{path}: a has shape {A.shape} but b has "
                                 f"shape {B.shape}; both are m x n")
        return A, B, coords, {"code_type": "stabilizer"}
    HX = _pick(z, ("hx", "HX", "H_X", "Hx"))
    HZ = _pick(z, ("hz", "HZ", "H_Z", "Hz"))
    if HX is None or HZ is None:
        raise SystemExit(
            f"{path}: need H_X and H_Z arrays (keys hx/HX/H_X and hz/HZ/H_Z), "
            f"or a stabilizer code's s = (A | B) (or a and b); "
            f"found {list(z.keys())}")
    HX, HZ = _as_dense_gf2(HX), _as_dense_gf2(HZ)
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
def build_stabilizer_submission(A, B, args):
    """Build the submission of a general stabilizer code S = (A | B).

    Isotropy in place of CSS commutation, k = n - rank S, check weight
    |A_i union B_i|, and one Pauli-weight distance witness (RIS by Pauli
    weight, tightened by the accelerator on the doubled matrices and
    re-scored). Writes code_type "stabilizer" at schema 0.4. A code whose
    every row is pure X or pure Z, or becomes so under single-qubit
    Cliffords, is refused here with the same instruction the verifier gives:
    type it CSS.
    """
    n = A.shape[1]
    if B.shape != A.shape:
        raise SystemExit(f"A has shape {A.shape} but B has shape {B.shape}")
    if bool(((A @ B.T + B @ A.T) % 2).any()):
        raise SystemExit("A B^T + B A^T != 0 over GF(2): the generators do not "
                         "commute (check your matrices / ordering)")
    if all(not (A[i].any() and B[i].any()) for i in range(A.shape[0])):
        raise SystemExit("every generator is pure X or pure Z: this is a CSS "
                         "code; submit it as H_X / H_Z (keys hx, hz) so it is "
                         "typed CSS and ranked on the CSS board")
    found = is_css_up_to_local_clifford(A, B)
    if found is not None:
        types, ops = found
        kinds = ", ".join(sorted({v for v in ops.values()}))
        xs = [i for i, t in enumerate(types) if t == "X"]
        raise SystemExit(
            f"single-qubit Cliffords on {len(ops)} qubit(s) (X,Y,Z -> {kinds}) "
            f"make every generator pure X or pure Z: this is a CSS code up to a "
            f"local Clifford, which the verifier rejects. Submit its CSS image "
            f"as H_X / H_Z (keys hx, hz): the supports of generators {xs[:8]}"
            f"{', ...' if len(xs) > 8 else ''} ({len(xs)} of {len(types)}) as "
            f"H_X rows and the rest as H_Z rows")
    S = np.concatenate([A, B], axis=1)
    k = n - gf2.rank(S)
    if k < 1:
        raise SystemExit(f"computed k={k}: no logical qubits, nothing to submit")
    wmax = int(max(((A[i] | B[i]).sum() for i in range(A.shape[0])), default=0))

    print(f"  building stabilizer submission... n={n} k={k} w={wmax}", flush=True)
    print(f"  searching for a Pauli-weight distance witness ({args.trials} RIS "
          f"trials)...", flush=True)
    dP, witP = hd.ris_min_pauli_logical(A, B, trials=args.trials, seed=args.seed)
    if dP is None:
        raise SystemExit("RIS found no logical operator; cannot certify a distance")
    if hd._fast is not None and args.fast_trials > 0:
        # accelerator on the symplectic doubling; its Hamming weight is an
        # upper bound on the Pauli weight, so the proposal is mapped back,
        # validated by gf2, and re-scored before it may tighten the claim
        print(f"  accelerator pass on the doubled matrices ({args.fast_trials} "
              f"trials)...", flush=True)
        HX2, HZ2 = hd.doubled_matrices(A, B)
        wf, side, sup = hd._fast.distance_rand_witness(
            HX2, HZ2, args.fast_trials, args.seed, 8, 8)
        if wf is not None and side in ("X", "Z"):
            v = np.zeros(2 * n, dtype=np.int8)
            v[list(sup)] = 1
            v = hd._pauli_from_doubled(v, side, n)
            wp = int(hd.pauli_weight_rows(v[None, :], n)[0])
            if wp < dP and hd.valid_pauli_logical(v, A, B):
                dP, witP = wp, v
                print(f"    accelerator tightened d to {wp}", flush=True)
    print(f"  distance (RIS upper bound, Pauli weight) d<={dP}", flush=True)

    dist = {"d": int(dP),
            "P": {"value": int(dP), "confidence": "upper_bound",
                  "witness": hd.pauli_witness(witP, n)}}
    prov = {"authors": args.authors,
            "construction": args.construction or "contributed via qldpc submit",
            "origin": "submission",
            "date": args.date or datetime.date.today().isoformat()}
    if args.model:
        prov["model"] = args.model
    if args.notes:
        prov["notes"] = args.notes
    budget = search_budget_from_args(args)
    if budget:
        prov["search_budget"] = budget
    gens = [{"X": _supports(A[i:i + 1])[0], "Z": _supports(B[i:i + 1])[0]}
            for i in range(A.shape[0])]
    doc = {
        "schema_version": "0.4",         # code_type stabilizer is a 0.4 feature
        "name": args.name or f"[[{n},{k},{dP}]]",
        "code_type": "stabilizer",
        "n": n, "k": int(k),
        "checks": {"S": gens},
        "distance": dist,
        "provenance": prov,
    }
    if args.family:
        doc["family"] = args.family
    _attach_layout(doc, args, n)
    return doc


def _attach_layout(doc, args, n):
    if args._coords is not None:
        if len(args._coords) != n:
            raise SystemExit(f"coords has {len(args._coords)} rows, need n={n}")
        coords = [[float(v) for v in row] for row in args._coords]
        if any(len(row) not in (2, 3) for row in coords):
            raise SystemExit("coords rows must be [x, y] or [x, y, z]")
        doc["locality"] = {
            "coordinates": coords,
            "layers": int(args.layers),
        }


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
    # Let the C++ accelerator tighten the claim when it can. The Python search
    # slows sharply with n, so on a large code it stops far above the lightest
    # logical and the entry would claim a distance the submitter can already
    # disprove. Anything the accelerator returns is checked by gf2 before it is
    # used, and it is only adopted when it is strictly lighter.
    if hd._fast is not None and args.fast_trials > 0:
        print(f"  accelerator pass ({args.fast_trials} trials)...", flush=True)
        wf, side, sup = hd._fast.distance_rand_witness(
            HX, HZ, args.fast_trials, args.seed, 8, 8)
        if wf is not None and side in ("X", "Z"):
            v = np.zeros(n, dtype=np.int8)
            v[list(sup)] = 1
            H_ker, H_row = (HZ, HX) if side == "X" else (HX, HZ)
            cur = dX if side == "X" else dZ
            if int(v.sum()) < cur and hd._valid_logical(v, H_ker, H_row):
                if side == "X":
                    dX, witX = int(v.sum()), v
                else:
                    dZ, witZ = int(v.sum()), v
                print(f"    accelerator tightened d_{side} to {int(v.sum())}",
                      flush=True)
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
    budget = search_budget_from_args(args)
    if budget:
        prov["search_budget"] = budget

    doc = {
        # search_budget is a 0.3 feature; without it the document stays at
        # the oldest version that describes it, so older readers accept it.
        "schema_version": "0.3" if budget else "0.1",
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
    _attach_layout(doc, args, n)
    return doc


# ----------------------------------------------------------------------------
# the search budget (provenance.search_budget, schema 0.3)
# ----------------------------------------------------------------------------
# What the search cost is not reconstructible after the fact, so the tool
# records it at submission time from whatever the contributor measured. The
# verifier checks none of it; the block exists so cost per discovery can be
# compared across entries. Individual --budget-* flags override keys of a
# --budget-json file, and an empty result leaves the document without the
# block (and at schema 0.1).
BUDGET_KEYS = ("candidates_screened", "ris_trials_per_side", "cpu_hours",
               "gpu_hours", "llm_tokens", "wall_clock_hours", "tool", "notes")


def _parse_llm_tokens(items):
    """Parse 'MODEL=COUNT' strings into {model: int}.

    The model name may itself contain '=': the count is whatever follows the
    last one.
    """
    out = {}
    for item in items or ():
        model, sep, count = str(item).rpartition("=")
        if not sep or not model.strip() or not count.strip().isdigit():
            raise SystemExit(
                f"--budget-llm-tokens expects MODEL=COUNT (e.g. "
                f"'Claude Opus 4.8=1800000'), got {item!r}")
        out[model.strip()] = int(count)
    return out


def search_budget_from_args(args):
    """Assemble provenance.search_budget from the submit arguments.

    Reads the --budget-* flags and/or a --budget-json value (a path, or an
    inline JSON object starting with '{'). Returns {} when nothing was given.
    """
    budget = {}
    raw = getattr(args, "budget_json", None)
    if raw:
        try:
            if raw.lstrip().startswith("{"):
                loaded = json.loads(raw)
            else:
                with open(raw, encoding="utf-8") as f:
                    loaded = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise SystemExit(f"--budget-json: cannot read {raw!r} ({e})")
        if not isinstance(loaded, dict):
            raise SystemExit("--budget-json must hold a JSON object")
        unknown = sorted(set(loaded) - set(BUDGET_KEYS))
        if unknown:
            raise SystemExit(
                f"--budget-json: unknown key(s) {unknown}; allowed: "
                f"{list(BUDGET_KEYS)}")
        budget.update(loaded)
    for key in BUDGET_KEYS:
        if key == "llm_tokens":
            tokens = _parse_llm_tokens(getattr(args, "budget_llm_tokens", None))
            if tokens:
                budget["llm_tokens"] = {**budget.get("llm_tokens", {}), **tokens}
            continue
        value = getattr(args, f"budget_{key}", None)
        if value is not None and value != "":
            budget[key] = value
    return budget


# ----------------------------------------------------------------------------
# the pull request
# ----------------------------------------------------------------------------
# `gh pr create --fill` copies the commit message, so a one-line commit gives a
# PR with an empty body and the reviewer learns nothing about the code (#404).
# We build the title and body ourselves from what submit() already knows: the
# computed track membership, the distance confidence, the construction, and the
# note pointer. Everything stated here is data the verifier just produced or
# text the contributor supplied; the one thing the tool cannot know — which
# board entry this beats — is left as an explicit TODO rather than invented.
def _descriptor(args):
    """Short human tag for the PR title, e.g. 'bivariate-bicycle code'."""
    con = (args.construction or "").strip()
    if con:
        head = con.split("(")[0].split(";")[0].strip(" ,.")
        if 0 < len(head) <= 60:
            return head
    if args.family:
        return f"{args.family} code"
    return ""


def _box(ticked, text):
    return f"- [{'x' if ticked else ' '}] {text}"


def _board_identities():
    """Return the board's identity sets as verify/validate_candidate.py reads them.

    One memoized structural pass (qldpc_verify.board_reports) serves this, the
    frontier comparison, and the site build alike, so after the first caller
    in a process it is free.
    """
    import validate_candidate as vc
    return vc._board_entries(), vc._identity_sets


def _board_codes_dir():
    """The directory `verify/validate_candidate.py` reads the board from."""
    import validate_candidate as vc
    return vc._CODES


def _self_entry_name(out_dir, out_file):
    """The board entry name this run is about to create, or None.

    A candidate can only match *itself* when it is being written into the
    directory the board is read from -- then the entry it is about to add and
    the entry the dedup finds are the same file. With `--out` pointing
    elsewhere (a scratch directory, as the CLI tests use) an entry of the same
    basename is a *different* file on purpose, and must keep being reported as
    a possible equivalent.

    Matching on the basename alone conflates the two cases, and quietly stops
    the equivalence box from doing its job.
    """
    try:
        if os.path.abspath(out_dir) != os.path.abspath(_board_codes_dir()):
            return None
    except Exception:
        return None
    return os.path.basename(out_file)


def board_dedup(report, *, exclude=None):
    """Compare a verified candidate against the board the way the validator does.

    Returns {"checked", "match", "kind"}: exact fingerprint first, then WL
    signature, each through the local-Hadamard images on both sides. This is
    the validator's own dedup verdict (verify/validate_candidate.py), computed
    here so the drafted PR body can tick the equivalence box with evidence
    instead of leaving a prompt a human has to answer by hand (issue #2328).

    `exclude` is the candidate's own file name once it is on disk, and it is
    what makes the comparison mean what the box says. The candidate is being
    compared against the board *as it will be once this PR lands*, so its own
    freshly written entry is not a match -- it is the entry this PR adds. A
    genuinely equivalent entry under a *different* name still matches, which is
    the case the box is for.

    Without this the comparison was made after `codes/<slug>.json` had been
    written, so the candidate was in the board it compared against, matched
    itself on its own fingerprint, and the equivalence box stayed unticked on
    every run -- which `verify/check_prose.py` then refuses, making
    `--open-pr` unable to complete on an unedited draft.
    """
    try:
        board, identity_sets = _board_identities()
        fps, sigs = identity_sets(report)
    except Exception as e:
        print(f"  note: board dedup skipped ({e}); the equivalence box stays "
              f"unticked for a human to answer")
        return {"checked": False, "match": None, "kind": None}

    others = [b for b in board if b["name"] != exclude]

    def fps_of(b):
        return {b["fingerprint"]} | set(b.get("css_fingerprints") or [])

    def sigs_of(b):
        return {b["sig"]} | set(b.get("css_sigs") or [])

    exact = next((b["name"] for b in others if fps & fps_of(b)), None)
    if exact:
        return {"checked": True, "match": exact, "kind": "exact fingerprint"}
    wl = next((b["name"] for b in others if sigs & sigs_of(b)), None)
    if wl:
        return {"checked": True, "match": wl, "kind": "WL signature"}
    return {"checked": True, "match": None, "kind": None}


def _equivalence_box(dedup):
    """Return the equivalence checklist line, ticked only on evidence.

    No match on a checked board: ticked, and it says what was checked, so an
    unedited draft passes the prose gate and --open-pr can succeed. A match,
    or no board to check against: unticked, naming the entry, so the gate
    holds the PR until a human has said in `provenance.notes` why this is a
    different code.
    """
    if dedup and dedup.get("checked") and not dedup.get("match"):
        return _box(True, "Checked against the current board by exact "
                         "fingerprint and WL signature, local-Hadamard images "
                         "included: no equivalent entry")
    if dedup and dedup.get("match"):
        return _box(False, f"Possibly equivalent to `{dedup['match']}` "
                          f"({dedup['kind']}): say in `provenance.notes` why "
                          f"this is a different code, or withdraw")
    return _box(False, "If this may be equivalent to an existing entry, noted "
                      "in `provenance.notes` (the board could not be loaded "
                      "for the automatic check)")


def _repo_path(path):
    """Repo-relative path when the file is inside the repo, else absolute.
    Keeps the body readable when --out points somewhere else entirely.
    """
    rel = os.path.relpath(path, _ROOT)
    return os.path.abspath(path) if rel.startswith(os.pardir) else rel


def pr_title(n, k, d, descriptor):
    head = f"Add [[{n},{k},{d}]]"
    return f"{head} {descriptor}" if descriptor else head


def pr_body(doc, report, args, out, note_out=None):
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    comp = report.get("computed", {})
    wmax = comp.get("max_check_weight")
    track = " / ".join(x for x in (comp.get("locality_class"),
                                   comp.get("weight_class")) if x)
    stab = doc.get("code_type") == "stabilizer"
    conf = {side: doc["distance"][side]["confidence"]
            for side in (("P",) if stab else ("X", "Z")) if side in doc["distance"]}
    conf_line = ", ".join(f"{s}: {c}" for s, c in conf.items())
    rel_out = _repo_path(out)

    def box(checked, text):
        return f"- [{'x' if checked else ' '}] {text}"

    lines = [
        "## Code submission",
        "",
        f"- Parameters: [[n, k, d]] = [[{n},{k},{d}]]",
        f"- Tracks: {track} (computed by the verifier from H and the layout)"
        + ("; general stabilizer code, ranked on the stabilizer board"
           if stab else ""),
        f"- Distance confidence: {conf_line}"
        + (" (Pauli weight, one side)" if stab else ""),
    ]
    circ = doc.get("circuit")
    if circ:
        dc = circ["d_circ"]
        slug = os.path.splitext(os.path.basename(out))[0]
        lines.append(
            f"- Circuit tier: d_circ <= {min(dc['X']['value'], dc['Z']['value'])} "
            f"(X {dc['X']['value']}, Z {dc['Z']['value']}) at rounds "
            f"{circ['rounds']}, witness-backed, memory circuits under "
            f"`circuits/{slug}/`")
    lines.append("")
    if args.family:
        lines += [f"Family tag: {args.family} (a self-declared filter, never "
                  f"used for ranking).", ""]
    # Checklist boxes are ticked only when the tool can vouch for them. The
    # construction box reflects whether --construction was given; the
    # equivalence box reflects the board dedup `qldpc submit` ran (see
    # _equivalence_box): ticked with the evidence when nothing matched,
    # otherwise left for a human, which the prose gate enforces.
    lines += [
        "### Checklist",
        box(True, "One JSON file under `codes/`, conforming to "
                  "`schema/code.schema.json`"),
        box(True, "Distance witness(es) included for each reported side"),
        box(True, f"`python verify/qldpc_verify.py {rel_out}` passes locally"),
        box(True, f"`python verify/circuit_verify.py {rel_out}` passes locally")
        if circ else None,
        box(bool((args.construction or "").strip()),
            "Construction and references filled in under `provenance`")
        if (args.construction or "").strip() else None,
        _equivalence_box(getattr(args, "_dedup", None)),
        "",
        "### What frontier does this advance?",
        "(Computed by `qldpc submit` against the current board; review and "
        "edit.)",
    ]
    front = frontier_summary(doc, report)
    if front:
        lines += front
    else:
        lines += ["(Name the track and the existing entry this beats or "
                  "extends, and on which axis.)"]
    lines += [
        f"Score kd^2/n = {round(k * d * d / n, 3)}, max check weight {wmax}, "
        f"locality class {comp.get('locality_class', 'unknown')}.",
        "",
    ]
    if (args.construction or "").strip():
        lines += [f"Construction: {args.construction.strip()}", ""]
    if note_out:
        lines += [f"Research note: `{_repo_path(note_out)}`", ""]
    else:
        lines += [f"(Add a research note at notes/{n}-{k}-{d}.md; see "
                  f"notes/TEMPLATE.md.)", ""]
    # No draft footer: 'edit before requesting review' is itself a scaffolding
    # marker the prose check rejects. The reminder lives in the CLI output.
    return "\n".join(ln for ln in lines if ln is not None)


def write_pr_body(slug, body):
    """Stage the body where --open-pr and the manual path can both use it."""
    fd, path = tempfile.mkstemp(prefix=f"qldpc-pr-{slug}-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    return path


# ----------------------------------------------------------------------------
# frontier comparison (reuses the site's own cell + Pareto logic)
# ----------------------------------------------------------------------------
def _load_board_entries(quiet=False):
    """The board's current entries as the site sees them (verified, earned
    distance). Returns [] if the site builder cannot be imported or the board
    is empty, so the frontier section degrades gracefully to a TODO.

    This runs a structural verification pass over ``codes/`` and is the
    single most expensive thing the CLI does. ``verify/qldpc_verify.py`` already
    memoizes it -- per entry, on disk, keyed by the entry bytes and the
    validator closure digest -- so a warm checkout measures ~2 s here while a
    cold one takes minutes. The memo lives inside the checkout, which means a
    freshly created git worktree starts cold. Either way it used to print
    nothing until it finished, so ``targets`` looked hung; twice on a harness
    with a 120 s limit before these two lines existed. They go to stderr, which
    keeps stdout clean for ``--json``, and report the measured time rather than
    an estimate, because warm-versus-cold is a hundredfold difference and the
    reader cannot otherwise tell which one they are paying.

    ``quiet`` suppresses them for library callers that do their own reporting.
    """
    try:
        from build import load_entries
    except Exception as e:
        print(f"  note: could not load the current board for frontier "
              f"comparison ({e}); leaving the frontier section as a TODO")
        return []
    if not quiet:
        print("  loading the board (structural verification pass over codes/)...",
              file=sys.stderr)
    t0 = time.time()
    try:
        entries = load_entries()
    except Exception as e:
        print(f"  note: could not load the current board for frontier "
              f"comparison ({e}); leaving the frontier section as a TODO")
        return []
    if not quiet:
        print(f"  loaded {_plural(len(entries), 'entry', 'entries')} in "
              f"{time.time() - t0:.1f}s", file=sys.stderr)
    return entries


def _entry_for(doc, report):
    """A board-shaped entry for the candidate, mirroring site/build.load_entries
    (n, k, d, w, locality/weight class, eff). The site's pareto()/cells() only
    read these keys, so this is enough to compare against the board.
    """
    comp = report.get("computed", {})
    n, k = doc["n"], doc["k"]
    earned = report.get("earned_distance", {}).get("d")
    d = earned["value"] if isinstance(earned, dict) else (earned or doc["distance"]["d"])
    return {
        "slug": f"{n}-{k}-{d}",
        "n": n, "k": k, "d": d,
        "code_type": doc.get("code_type", "CSS"),
        "eff": round(k * d * d / n, 3),
        "w": comp.get("max_check_weight"),
        "locality_class": comp.get("locality_class", "unrestricted"),
        "weight_class": comp.get("weight_class", "weight-9plus"),
    }


def frontier_summary(doc, report):
    """A human summary of where the candidate lands on the current board:
    which track cells it belongs to, whether it sits on each cell's Pareto
    frontier, and which existing entries it strictly dominates (and on which
    axis). Returns a list of markdown lines (may be empty if the board is
    unavailable).
    """
    entries = _load_board_entries()
    if not entries:
        return []
    cand = _entry_for(doc, report)
    lines = []
    for cell in cells(cand):
        L, W = cell
        # peers share the cell and the board: CSS and stabilizer codes
        # rank separately
        idxs = [i for i, e in enumerate(entries) if cell in cells(e)
                and e.get("code_type", "CSS") == cand["code_type"]]
        peers = [entries[i] for i in idxs]
        # pareto() returns the set of indices on the frontier; the candidate is
        # appended last, so its index is len(peers).
        on_front = len(peers) in pareto(peers + [cand])
        # existing entries the candidate strictly dominates on (n, k, d, w)
        dominated = [e for e in peers
                     if e["n"] >= cand["n"] and e["k"] <= cand["k"]
                     and e["d"] <= cand["d"] and e["w"] >= cand["w"]
                     and (e["n"] > cand["n"] or e["k"] < cand["k"]
                          or e["d"] < cand["d"] or e["w"] > cand["w"])]
        dominated.sort(key=lambda e: (-e["eff"], e["n"]))
        head = (f"- **{LOCALITY_LABEL[L]} / {WEIGHT_LABEL[W]}**: "
                f"{'on the Pareto frontier' if on_front else 'not on the frontier'}")
        if dominated:
            names = ", ".join(f"[[{e['n']},{e['k']},{e['d']}]]"
                              for e in dominated)
            head += f" — dominates {names}"
        lines.append(head)
    return lines


# ----------------------------------------------------------------------------
# submit command
# ----------------------------------------------------------------------------
def validate_authors(authors, anonymous=False):
    """Return normalized authors or fail before producing an unbound record."""
    normalized = [str(author).strip() for author in authors]
    if any(not author for author in normalized):
        raise SystemExit(
            "Author values must not be empty or whitespace-only. Remove the "
            "empty value or replace it with a name or @handle."
        )
    malformed = [
        author for author in normalized
        if author.startswith("@") and HANDLE.fullmatch(author) is None
    ]
    if malformed:
        values = ", ".join(repr(author) for author in malformed)
        raise SystemExit(
            f"Invalid author {values}. GitHub authors must use @yourhandle "
            "with letters, numbers, or hyphens only."
        )

    has_handle = any(HANDLE.fullmatch(author) for author in normalized)
    if has_handle and anonymous:
        raise SystemExit(
            "--anonymous cannot be combined with a GitHub @handle; remove "
            "--anonymous to keep the submission bound to that account."
        )
    if has_handle:
        return normalized

    if not anonymous:
        raise SystemExit(
            "No GitHub @handle found in --authors. Add @yourhandle (the @ is "
            "required), or pass --anonymous to confirm that the submission "
            "will not be bound to a GitHub account."
        )

    print(
        "  WARNING: no GitHub @handle was provided. This submission will be "
        "recorded as anonymous and will not be bound to a GitHub account.",
        flush=True,
    )
    return normalized


def dry_run_summary(doc, report, out):
    """Print a screen-sized preview of what submit would write.

    The parameters and score, the distance claim per side, the computed track
    cells, and the provenance the contributor chose. Replaces the old
    truncated JSON prefix, which never reached the fields a contributor
    actually wants to confirm (issue #637).
    """
    comp = report.get("computed", {})
    entry = _entry_for(doc, report)
    dist = doc["distance"]
    per_side = []
    stab = doc.get("code_type") == "stabilizer"
    for side in (("P",) if stab else ("X", "Z")):
        s = dist.get(side, {})
        witness = "witness found" if s.get("witness") else "no witness"
        per_side.append(f"{side}: <= {s.get('value')} ({s.get('confidence')}, {witness})")
    track_cells = ", ".join(
        f"{LOCALITY_LABEL.get(L, L)} / {WEIGHT_LABEL.get(W, W)}"
        for L, W in cells(entry)
    )
    lines = [
        f"  code         [[{doc['n']},{doc['k']},{dist['d']}]]"
        + ("  (general stabilizer code, stabilizer board)" if stab else ""),
        f"  score        kd^2/n = {entry['eff']}",
        f"  checks       max weight {entry['w']} ({comp.get('weight_class', '?')})",
        f"  locality     {comp.get('locality_class', 'unrestricted')}",
        f"  track cells  {track_cells or '(none computed)'}",
        f"  distance     d <= {dist['d']} (upper_bound)",
        "               " + "  |  ".join(per_side),
    ]
    circ = doc.get("circuit")
    if circ:
        dc = circ["d_circ"]
        slug = os.path.splitext(os.path.basename(out))[0]
        lines.append(
            f"  circuit      d_circ <= {min(dc['X']['value'], dc['Z']['value'])} "
            f"(X {dc['X']['value']}, Z {dc['Z']['value']}), rounds "
            f"{circ['rounds']} -> circuits/{slug}/memory_{{x,z}}.{{stim,dem}}")
    prov = doc.get("provenance", {})
    for label, value in (
        ("authors", ", ".join(prov.get("authors", []))),
        ("family", doc.get("family")),
        ("model", prov.get("model")),
        ("construction", prov.get("construction")),
        ("notes", prov.get("notes")),
    ):
        if value:
            lines.append(f"  {label:<12} {value}")
    lines.append("  next         --json prints the full document; drop --dry-run to write")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# the circuit tier (RFC 0001, issue #505; default since issue #1848)
# ----------------------------------------------------------------------------
def schema_version_for(doc):
    """Return the oldest schema version that describes the document.

    0.4 for a stabilizer code, 0.3 with a search budget, 0.2 with a circuit
    block, else 0.1.
    """
    if doc.get("code_type") == "stabilizer":
        return "0.4"
    if (doc.get("provenance") or {}).get("search_budget"):
        return "0.3"
    if doc.get("circuit"):
        return "0.2"
    return "0.1"


def attach_circuit_tier(doc, args):
    """Generate the memory circuits (or take the submitter's from --circuits),
    run the tier's fast-path verifier on them exactly as CI will, and on
    success put the circuit block on `doc` and return {filename: text} for
    circuits/<slug>/. Returns None, leaving `doc` alone, when no verifiable
    tier can be produced for this code; a failing --circuits directory is a
    hard error, since the submitter asked for those circuits specifically.
    """
    import circuit_autogen as ca  # noqa: E402  (stim; loaded only when used)
    from circuit_verify import verify_circuit  # noqa: E402
    from qldpc_verify import structure_errors  # noqa: E402

    def log(msg):
        print(f"    {msg}", flush=True)

    print("  circuit tier: " + ("reading circuits from " + args.circuits
                                if args.circuits else
                                "generating memory circuits (--no-circuit "
                                "skips this step)..."), flush=True)
    try:
        if args.circuits:
            block, files, family = ca.from_files(
                doc, args.circuits, rounds=args.circuit_rounds,
                seed=args.circuit_seed, seconds=args.circuit_seconds, log=log)
        else:
            block, files, family = ca.generate(
                doc, coords=args._coords, rounds=args.circuit_rounds,
                seed=args.circuit_seed, max_candidates=args.circuit_candidates,
                seconds=args.circuit_seconds, log=log)
    except ca.CircuitUnavailable as e:
        if args.circuits:
            raise SystemExit(f"--circuits: {e}")
        print(f"  circuit tier skipped: {e}")
        return None
    trial = dict(doc)
    trial["circuit"] = block
    trial["schema_version"] = schema_version_for(trial)
    with tempfile.TemporaryDirectory(prefix="qldpc-circuits-") as tmp:
        for name, text in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8",
                      newline="\n") as f:
                f.write(text)
        report = verify_circuit(trial, tmp)
    problems = [f"{c['check']}: {c['detail']}" for c in report["checks"]
                if not c["ok"]] + structure_errors(trial)
    if problems or not report["ok"]:
        for p in problems:
            print(f"    FAIL  {p}")
        if args.circuits:
            raise SystemExit("--circuits: the supplied circuits did not pass "
                             "verify/circuit_verify.py; nothing written.")
        print("  circuit tier skipped: the generated circuits did not verify "
              "(a generator bug; please report it with this output). The "
              "code tier is unaffected.")
        return None
    doc["circuit"] = block
    doc["schema_version"] = trial["schema_version"]
    dc = block["d_circ"]
    print(f"  OK  circuit tier verified: d_circ <= "
          f"{min(dc['X']['value'], dc['Z']['value'])} (X {dc['X']['value']}, "
          f"Z {dc['Z']['value']}), rounds {block['rounds']}, {family}")
    return files


def _result(args):
    """Return the result object `--json` prints; a throwaway dict otherwise."""
    if not hasattr(args, "_result"):
        args._result = {}
    return args._result


def cmd_submit(args):
    res = _result(args)
    res["stage"] = "build"
    args.authors = validate_authors(args.authors, args.anonymous)
    if args.no_circuit and args.circuits:
        raise SystemExit("--no-circuit and --circuits contradict each other")
    HX, HZ, coords, _draft = load_checks(args.code)
    if args.coords:                      # explicit coords file overrides
        cz = np.load(args.coords) if args.coords.endswith(".npz") else None
        coords = (_pick(cz, ("coords", "coordinates", "xy"))
                  if cz is not None else np.loadtxt(args.coords))
        coords = np.asarray(coords, dtype=float)
    args._coords = coords

    stabilizer = (_draft or {}).get("code_type") == "stabilizer"
    if stabilizer:
        if args.circuits:
            raise SystemExit("--circuits: the circuit tier is not available "
                             "for stabilizer codes; drop the flag")
        if not args.no_circuit:
            print("  circuit tier: not available for stabilizer codes (the "
                  "memory experiments are per basis); submitting the code "
                  "tier only", flush=True)
            args.no_circuit = True
        doc = build_stabilizer_submission(HX, HZ, args)
        print("  verifying (isotropy / k / weight / Pauli witness / locality)...",
              flush=True)
    else:
        doc = build_submission(HX, HZ, args)
        print("  verifying (CSS / k / weight / witnesses / locality)...", flush=True)
    res["stage"] = "verify"
    report = verify(doc, refute=True)
    for c in report["checks"]:
        if not c["ok"]:
            print(f"    FAIL  {c['check']}: {c['detail']}")
    if not report["ok"]:
        print("\nverification FAILED; nothing written. Fix the issues above.")
        res["error"] = {"stage": "verify", "message": "verification failed",
                        "failed_checks": [
                            {"check": c["check"], "detail": c["detail"]}
                            for c in report["checks"] if not c["ok"]]}
        return 1
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    print(f"  OK  verified. score kd^2/n = {round(k * d * d / n, 3)}")

    slug = f"{n}-{k}-{d}"
    res.update(slug=slug, n=n, k=k, d=d, code_type=doc.get("code_type", "CSS"),
               score=round(k * d * d / n, 3),
               earned_distance=report.get("earned_distance"))
    out = os.path.join(args.out, f"{slug}.json")
    circuits_dir = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                "circuits", slug)
    if not args.dry_run and not args.force:
        for p in ([out] if args.no_circuit else [out, circuits_dir]):
            if os.path.exists(p):
                print(f"\n{p} already exists. Use --force to overwrite, or "
                      f"rename.")
                res["error"] = {"stage": "write", "message": f"{p} already "
                                f"exists; use --force to overwrite, or rename"}
                return 1

    circuit_files = None if args.no_circuit else attach_circuit_tier(doc, args)

    if args.dry_run:
        print(f"\n--dry-run: would write {out}" +
              (f" and {circuits_dir}/" if circuit_files else ""))
        res.update(stage="dry-run", dry_run=True, would_write=out,
                   would_write_circuits=circuits_dir if circuit_files else None,
                   doc=doc)
        if not args.json:
            print(dry_run_summary(doc, report, out))
        return 0
    res["stage"] = "write"
    os.makedirs(args.out, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(f"  wrote {out}")
    res["code_path"] = out
    if circuit_files:
        os.makedirs(circuits_dir, exist_ok=True)
        for name, text in circuit_files.items():
            with open(os.path.join(circuits_dir, name), "w",
                      encoding="utf-8", newline="\n") as f:
                f.write(text)
        print(f"  wrote {circuits_dir}/memory_{{x,z}}.{{stim,dem}}")
    else:
        circuits_dir = None
    res["circuits_dir"] = circuits_dir

    # the public research note (notes/<slug>.md): how the code was found —
    # search narrative, sweep sizes, confirmation ladder, dead ends. Requested
    # for every submission; rendered on the code's site page and in the
    # research log. See notes/README.md and notes/TEMPLATE.md.
    note_out = None
    if args.note_file:
        with open(args.note_file, encoding="utf-8") as f:
            note_md = f.read()
        if len(note_md.encode()) > 10 * 1024:
            print(f"\n{args.note_file} exceeds the 10 KiB note cap; trim it.")
            res["error"] = {"stage": "note", "message": f"{args.note_file} "
                            f"exceeds the 10 KiB note cap"}
            return 1
        note_out = os.path.join(_ROOT, "notes", f"{slug}.md")
        os.makedirs(os.path.dirname(note_out), exist_ok=True)
        with open(note_out, "w", encoding="utf-8", newline="\n") as f:
            f.write(note_md)
        print(f"  wrote {note_out}")
    else:
        print("\n  note: no --note-file given. Submissions should ship a "
              "research note\n  (notes/{}.md) — the search story, sweep "
              "sizes, ladder, dead ends.\n  See notes/TEMPLATE.md; the site "
              "renders it beside your code.".format(slug))

    res["note_path"] = note_out
    res["stage"] = "draft"
    # The candidate's own file is on disk by now (written above), so when this
    # run is writing into the board's own directory the dedup is told to skip it:
    # the question the equivalence box asks is whether some OTHER entry already
    # carries this code, and the file this run just added is not an answer to it.
    args._dedup = board_dedup(
        report, exclude=_self_entry_name(args.out, out))
    title = pr_title(n, k, d, _descriptor(args))
    body_file = write_pr_body(slug, pr_body(doc, report, args, out, note_out))
    branch = f"submit-{slug}"
    pr_author = next((a.lstrip("@") for a in args.authors
                      if isinstance(a, str) and a.startswith("@")), None)
    res.update(title=title, body_file=body_file, branch=branch,
               pr_author=pr_author, dedup=args._dedup,
               base_ref=args.base_ref or None)
    files = [out] + ([note_out] if note_out else []) + \
        ([circuits_dir] if circuits_dir else [])
    steps = [
        f"git checkout -b {branch}" + (f" {args.base_ref}" if args.base_ref else ""),
        "git add " + " ".join(files),
        f"git commit -m {title!r}",
        f"git push -u origin {branch}",
        f"gh pr create --title {title!r} --body-file {body_file}",
    ]
    res["next_steps"] = steps

    if args.open_pr:
        res["stage"] = "open-pr"
        return open_pr(slug, out, note_out, title, body_file,
                       root=_ROOT, circuits_dir=circuits_dir,
                       pr_author=pr_author, base_ref=args.base_ref or None,
                       res=res)
    print("\nnext: open a PR with " +
          ("these files" if note_out or circuits_dir else "this file"))
    for step in steps:
        print(f"  {step}")
    print(f"\nthe PR body was drafted for you from the verified submission:"
          f"\n  {body_file}"
          f"\nit follows .github/pull_request_template.md — read it and fill"
          f"\nin the 'what frontier does this advance?' section before review.")
    print("\nor re-run with --open-pr to do this automatically.")
    return 0


def open_pr(slug, out, note_out=None, title=None, body_file=None, root=None,
            circuits_dir=None, pr_author=None, base_ref=None, res=None):
    """Branch, commit, push, and open the PR; the result goes into `res`.

    `pr_author` feeds the prose pre-flight the same handle CI passes, so a
    green pre-flight means what a green CI run means. `base_ref` starts the
    branch from that ref (say origin/main) and returns to the branch that was
    checked out afterwards, so successive --open-pr runs from one checkout
    yield independent one-code PRs, which is what the scope check requires.
    """
    res = res if res is not None else {}
    n_k_d = slug.replace("-", ",")
    branch = f"submit-{slug}"
    title = title or f"Add [[{n_k_d}]]"
    # Pre-flight: run the same prose check CI runs, on the drafted body and
    # the staged files, BEFORE any git command touches the working tree. A
    # body the gate would reject stops here with the checker's own output.
    root = root or _ROOT
    if body_file:
        checker = os.path.join(root, "verify", "check_prose.py")
        if os.path.exists(checker):
            files = [os.path.relpath(out, root)] + (
                [os.path.relpath(note_out, root)] if note_out else [])
            cmd = [sys.executable, os.path.relpath(checker, root),
                   "--root", root, "--body-file", body_file, "--files", *files]
            if pr_author:
                cmd += ["--pr-author", pr_author]
            pre = subprocess.run(cmd, cwd=root, check=False)
            if pre.returncode != 0:
                print(f"\nprose pre-flight FAILED ({pre.returncode}); no PR "
                      f"was opened. Fix the issues above (the drafted body is "
                      f"at {body_file}) and re-run with --open-pr.")
                res["error"] = {"stage": "prose-preflight",
                                "returncode": pre.returncode,
                                "message": "the drafted body or staged files "
                                           "fail verify/check_prose.py; fix "
                                           "them and re-run with --open-pr"}
                return 1
    add = ["git", "add", out] + ([note_out] if note_out else []) + \
        ([circuits_dir] if circuits_dir else [])
    # --title/--body-file rather than --fill: the body is the filled-in
    # pull request template, which the commit message does not carry (#404).
    create = ["gh", "pr", "create", "--title", title]
    create += ["--body-file", body_file] if body_file else ["--fill"]
    checkout = ["git", "checkout", "-b", branch] + ([base_ref] if base_ref else [])
    cmds = [
        checkout,
        add,
        ["git", "commit", "-m", title],
        ["git", "push", "-u", "origin", branch],
        create,
    ]
    previous = None
    if base_ref:
        head = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                              cwd=_ROOT, capture_output=True, text=True,
                              check=False)
        previous = head.stdout.strip() if head.returncode == 0 else None
    res["commands"] = [" ".join(c) for c in cmds]
    for c in cmds:
        print(f"  $ {' '.join(c)}", flush=True)
        r = subprocess.run(c, cwd=_ROOT, capture_output=True, text=True,
                           check=False)
        if r.stdout:
            print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
        if r.stderr:
            print(r.stderr, end="" if r.stderr.endswith("\n") else "\n",
                  file=sys.stderr)
        if r.returncode != 0:
            print(f"  command failed ({r.returncode}); finish the remaining "
                  f"steps by hand.")
            if body_file:
                print(f"  the drafted PR body is at {body_file}")
            res["error"] = {"stage": "open-pr", "command": " ".join(c),
                            "returncode": r.returncode,
                            "message": (r.stderr or r.stdout or "").strip()[-2000:]}
            return r.returncode
        if c is create:
            m = re.search(r"https://\S+/pull/\d+", r.stdout or "")
            res["pr_url"] = m.group(0) if m else None
            res["pr_number"] = int(res["pr_url"].rsplit("/", 1)[1]) if m else None
    if previous and previous != "HEAD":
        back = subprocess.run(["git", "checkout", previous], cwd=_ROOT,
                              capture_output=True, text=True, check=False)
        res["returned_to"] = previous if back.returncode == 0 else None
        if back.returncode != 0:
            print(f"  note: could not return to {previous} ({back.stderr.strip()})")
    print("\nthe PR body was drafted from the verified submission; fill in the"
          "\n'what frontier does this advance?' section before review "
          "(gh pr edit).")
    return 0


def cmd_targets(args):
    """Print per-cell occupancy and frontier, so a newcomer can see what to aim at.

    Reuses the site's own cells() and pareto(), the pair that decides records on
    the published board, so these are the board's numbers rather than a second
    opinion about them.

    Claims are the one thing here that is not a fact about the board. They are
    notes from concurrent sessions about where they are aiming, they expire, and
    nothing enforces them -- see coordination.claim. They are handled before the
    board is loaded so that taking or dropping one costs nothing, and so an empty
    cell can be claimed, which is the case worth claiming. The cell name is the
    one thing validated on that path, against the axis labels, which are module
    constants -- see _claim_cell.
    """
    res = _result(args)
    if args.claim or args.release:
        return _claim_action(args)
    if args.prune:
        gone = coordination.prune_claims()
        res["pruned"] = gone
        print(f"pruned {gone} expired claim(s)")
        return 0

    entries = _load_board_entries()
    if not entries:
        raise SystemExit("could not load the board; run this from a checkout")

    by_cell = {}
    for e in entries:
        for cell in cells(e):
            by_cell.setdefault(cell, []).append(e)

    def matches(L, W):
        if not args.cell:
            return True
        toks = [x for x in re.split(r"[/, ]+", args.cell.lower()) if x]
        hay = f"{L} {W} {LOCALITY_LABEL.get(L, L)} {WEIGHT_LABEL.get(W, W)}".lower()
        return all(tok in hay for tok in toks)

    def eff(e):
        return e["k"] * e["d"] ** 2 / e["n"]

    claims = coordination.live_claims()
    by_cell_name = {c["cell"]: c for c in claims}
    res["claims"] = claims

    rows = [(c, v) for c, v in sorted(by_cell.items()) if matches(*c)]
    if not rows:
        raise SystemExit(f"no cell matched {args.cell!r}. Weight classes: "
                         f"{sorted({c[1] for c in by_cell})}; locality classes: "
                         f"{sorted({c[0] for c in by_cell})}")

    for (L, W), peers in rows:
        front = [peers[i] for i in sorted(pareto(peers))]
        print(f"\n{LOCALITY_LABEL.get(L, L)} / {WEIGHT_LABEL.get(W, W)}")
        print(f"  {len(peers)} codes, {len(front)} nondominated, "
              f"best kd2/n {max(eff(e) for e in peers):.2f}")
        held = by_cell_name.get(f"{W}/{L}")
        if held:
            who = held["session_id"]
            if held.get("campaign"):
                who += f" ({held['campaign']})"
            print(f"  claimed by {who}, expires {held['expires_at']} "
                  f"-- advisory, not enforced")
        if args.n:
            near = [e for e in front if e["n"] <= args.n]
            if not near:
                print(f"  nothing at n <= {args.n}: any verified code here "
                      f"lands on the frontier")
            else:
                print(f"  at n <= {args.n}, {len(near)} entries to get past; "
                      f"the ones to beat:")
                for e in sorted(near, key=eff, reverse=True)[:args.top]:
                    print(f"    [[{e['n']},{e['k']},{e['d']}]] w={e['w']} "
                          f"kd2/n={eff(e):.2f}")
                continue
        for e in sorted(front, key=eff, reverse=True)[:args.top]:
            print(f"    [[{e['n']},{e['k']},{e['d']}]] w={e['w']} "
                  f"kd2/n={eff(e):.2f}")
        if len(front) > args.top:
            print(f"    ... {len(front) - args.top} more nondominated")

    print(f"\n{len(entries)} codes across {len(by_cell)} populated cells. "
          f"A code counts in every cell it qualifies for (the classes nest), "
          f"so these counts overlap by design.")
    print("Nondominated means no other code in the cell beats it on all of "
          "n, k, d and check weight at once, which is what earns a record star.")
    if claims:
        print(f"\n{_plural(len(claims), 'live claim')}, advisory and expiring "
              f"(nothing enforces them; see `qldpc targets --help`):")
        for c in claims:
            what = f"  {c['cell']}: {c['session_id']}"
            if c.get("campaign"):
                what += f" ({c['campaign']})"
            print(f"{what}, expires {c['expires_at']}")
    return 0


def _recent_code_rows(days, family):
    """Codes added to codes/ in the last `days` days whose slug, family, or
    name mentions `family`."""
    r = subprocess.run(["git", "log", "--diff-filter=A", f"--since={days} days ago",
                        "--name-only", "--pretty=format:%as", "--", "codes/"],
                       cwd=_ROOT, capture_output=True, text=True)
    rows, date = [], ""
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) == 10 and line[4] == line[7] == "-":
            date = line
            continue
        if not line.endswith(".json"):
            continue
        slug = os.path.splitext(os.path.basename(line))[0]
        fam = name = ""
        try:
            with open(os.path.join(_ROOT, line), encoding="utf-8") as fh:
                doc = json.load(fh)
            fam, name = doc.get("family") or "", doc.get("name") or ""
        except (OSError, ValueError):
            pass
        if family and family.lower() not in f"{slug} {fam} {name}".lower():
            continue
        rows.append({"date": date, "slug": slug, "family": fam, "name": name})
    return rows


def cmd_brief(args):
    """One bounded snapshot before a search: the cell's frontier and bar, what
    was screened there, what landed for the family, and the fieldnotes that
    touch it (#2955, item 4). Composes targets, screened, recent."""
    res = _result(args)
    entries = _load_board_entries()
    if not entries:
        raise SystemExit("could not load the board; run this from a checkout")
    by_cell = {}
    for e in entries:
        for cell in cells(e):
            by_cell.setdefault(cell, []).append(e)
    toks = [x for x in re.split(r"[/, ]+", args.cell.lower()) if x]

    def matches(L, W):
        hay = f"{L} {W} {LOCALITY_LABEL.get(L, L)} {WEIGHT_LABEL.get(W, W)}".lower()
        return all(tok in hay for tok in toks)

    def eff(e):
        return e["k"] * e["d"] ** 2 / e["n"]

    picked = [(c, v) for c, v in sorted(by_cell.items()) if matches(*c)]
    if not picked:
        raise SystemExit(f"no cell matched {args.cell!r}. Weight classes: "
                         f"{sorted({c[1] for c in by_cell})}; locality classes: "
                         f"{sorted({c[0] for c in by_cell})}")
    fam = args.family.lower()
    cells_out = []
    for (L, W), peers in picked:
        front = sorted((peers[i] for i in pareto(peers)), key=eff, reverse=True)
        members = [e for e in peers if fam and fam in (e.get("family") or "").lower()]
        cells_out.append({
            "cell": f"{W}/{L}", "codes": len(peers), "nondominated": len(front),
            "bar_kd2_over_n": round(max(eff(e) for e in peers), 3),
            "frontier": [{"n": e["n"], "k": e["k"], "d": e["d"], "w": e["w"],
                          "kd2_over_n": round(eff(e), 3), "slug": e.get("slug")}
                         for e in front[:args.top]],
            "family_codes": len(members),
            "family_best_kd2_over_n": round(max((eff(e) for e in members), default=0.0), 3),
        })
    screened, quality, summaries = ([], [], 0)
    if args.family:
        screened, quality, summaries = screening_rows(family=args.family)
    recent = _recent_code_rows(args.days, args.family)
    notes = []
    for f in sorted(glob.glob(os.path.join(_ROOT, "fieldnotes", "*.md"))):
        if f.endswith("README.md"):
            continue
        title, topics = _fieldnote_meta(f)
        hay = f"{os.path.basename(f)} {title} {' '.join(topics)}".lower()
        if (fam and fam in hay) or any(tok in hay for tok in toks):
            notes.append({"path": os.path.relpath(f, _ROOT), "title": title, "topics": topics})
    claims = []
    if hasattr(coordination, "live_claims"):
        claims = [c for c in coordination.live_claims()
                  if any(c.get("cell") == x["cell"] for x in cells_out)]
    res.update(query={"cell": args.cell, "family": args.family, "days": args.days},
               cells=cells_out, screened=screened[:args.limit], screened_total=len(screened),
               summaries_read=summaries, screen_quality=quality,
               recent=recent[:args.limit], recent_total=len(recent),
               fieldnotes=notes[:args.limit], fieldnotes_total=len(notes), claims=claims)

    for c in cells_out:
        print(f"{c['cell']}: {c['codes']} codes, {c['nondominated']} nondominated, "
              f"bar kd2/n {c['bar_kd2_over_n']}"
              + (f"; {c['family_codes']} from {args.family}, best {c['family_best_kd2_over_n']}"
                 if args.family else ""))
        for e in c["frontier"]:
            print(f"    [[{e['n']},{e['k']},{e['d']}]] w={e['w']} kd2/n={e['kd2_over_n']}")
        if c["nondominated"] > args.top:
            print(f"    ... {c['nondominated'] - args.top} more nondominated")
    for cl in claims:
        print(f"  claimed by {cl['session_id']}"
              + (f" ({cl['campaign']})" if cl.get("campaign") else "")
              + f", expires {cl['expires_at']} (advisory)")
    if args.family:
        print(f"\nscreened, {args.family}: {len(screened)} record(s) across {summaries} "
              f"campaign summaries" + ("" if screened else " (nothing recorded: screen before you ladder)"))
        for r in screened[:args.limit]:
            depth = (f"d<={r['screened_d']} at {r['trials']} trials" if r["screened_d"] is not None
                     else "depth not recorded")
            pretty = ", ".join(f"{k}={v}" for k, v in sorted(r["params"].items()))
            print(f"    {r['campaign_id']}  {pretty or '(no params)'}  {depth}"
                  + (f"  {r['verdict']}" if r.get("verdict") else ""))
    print(f"\nlanded in {args.days} days" + (f" for {args.family}" if args.family else "")
          + f": {len(recent)} code(s)")
    for r in recent[:args.limit]:
        print(f"    {r['date']}  {r['slug']}  {r['family']}")
    print(f"\nfieldnotes touching this: {len(notes)}")
    for nrow in notes[:args.limit]:
        print(f"    {nrow['path']}  {nrow['title'][:70]}")
    return 0


def _claim_action(args):
    """``--claim`` / ``--release``, kept off the board path deliberately.

    The cell name is checked here, against the axis labels the listing itself
    uses. They are module constants, so checking costs no board load and an
    empty cell stays claimable; it is the pair that is checked, and written
    weight-first, because the listing matches a claim by exactly
    ``f"{W}/{L}"`` -- a typo or the reverse order writes a note no reader can
    find, and a claim nobody can see is worse than a refused one. This is the
    CLI declining to write, not ``verify/`` declining to pass: nothing here
    enforces anything.
    """
    cell = _claim_cell(args.claim or args.release)
    res = _result(args)
    if args.claim:
        rec = coordination.claim(cell, campaign=args.campaign,
                                 note=args.note, minutes=args.ttl)
        res["claim"] = rec
        print(f"claimed {rec['cell']} for {rec['expires_at']} "
              f"({rec['session_id']})")
        gone = rec.get("displaced")
        if gone:
            print(f"  note: {gone['session_id']} had a live claim on this cell"
                  + (f" ({gone['campaign']})" if gone.get("campaign") else "")
                  + ". Nothing blocks either of you; it is your call whether "
                    "two ladders on one cell are worth paying for.")
        return 0
    dropped = coordination.release(cell)
    res["released"] = {"cell": cell, "by_this_session": dropped}
    if dropped:
        print(f"released {cell}")
    else:
        print(f"no live claim of this session's on {cell} "
              f"(already expired, held by another session, or never made)")
    return 0


def _claim_cell(name):
    """Return ``name`` as the canonical ``<weight>/<locality>`` cell, or exit.

    Both parts have to be names the board's own axes use, and the pair comes
    out weight-first whatever order it was typed in: ``unrestricted/weight-6``
    is the same cell as ``weight-6/unrestricted`` to a reader and not to a
    string match, so writing it as typed would be a second, silent claim on a
    cell somebody else is already holding. Anything else is refused with the
    valid names, which is the difference between a note and a note on nothing.
    """
    parts = [p for p in re.split(r"[/,\s]+", (name or "").strip().lower()) if p]
    weight = [p for p in parts if p in WEIGHT_LABEL]
    local = [p for p in parts if p in LOCALITY_LABEL]
    if len(parts) != 2 or len(weight) != 1 or len(local) != 1:
        raise SystemExit(
            f"{name!r} is not a cell. A cell is <weight>/<locality>:\n"
            f"  weight:   {', '.join(WEIGHT_LABEL)}\n"
            f"  locality: {', '.join(LOCALITY_LABEL)}")
    return f"{weight[0]}/{local[0]}"


def _plural(n, word, plural=None):
    return f"{n} {word}" if n == 1 else f"{n} {plural or word + 's'}"


def _fieldnote_meta(path):
    """Read a fieldnote's title and topics.

    Taken from its YAML frontmatter, falling back to the first heading and no
    topics. Only the frontmatter is read.
    """
    title, topics = "", []
    try:
        with open(path, encoding="utf-8") as f:
            if f.readline().strip() != "---":
                f.seek(0)
                for line in f:
                    if line.startswith("#"):
                        return line.lstrip("#").strip(), []
                return "", []
            for line in f:
                head = line.rstrip("\n")
                if head.strip() == "---":
                    break
                if head.startswith("title:"):
                    title = head[6:].strip().strip('"')
                elif head.startswith("topics:"):
                    topics = [t.strip().strip('"')
                              for t in head[7:].strip().strip("[]").split(",")
                              if t.strip()]
    except OSError:
        pass
    return title, topics


def cmd_recent(args):
    """What moved on the board recently: codes merged, research notes, and
    fieldnotes, from git history. The 'stay current' step — read this (and
    the linked notes) before spending compute, so a new search starts from
    the community's frontier of knowledge, not just the frontier of scores.

    Bounded by default: a count line plus the newest --limit rows per section,
    because a busy fortnight is hundreds of codes and printing all of them
    buries the reader (and fills an agent's context). --full prints every row;
    --family / --topic narrow both sections to what a given search cares
    about.
    """
    since = f"--since={args.days} days ago"
    want = [t.lower() for t in (args.family, args.topic) if t]

    def added(path):
        r = subprocess.run(
            ["git", "log", "--diff-filter=A", since, "--name-only",
             "--pretty=format:%as", "--", path],
            cwd=_ROOT, capture_output=True, text=True)
        out, date = [], ""
        for line in r.stdout.splitlines():
            if not line.strip():
                continue
            if len(line) == 10 and line[4] == line[7] == "-":
                date = line
            else:
                out.append((date, line.strip()))
        return out

    def code_row(date, f):
        """Build one code row, reading its JSON for the family tag.

        Called only for rows that are printed or filtered on, never for the
        whole history.
        """
        slug = os.path.splitext(os.path.basename(f))[0]
        fam, name = "", ""
        try:
            with open(os.path.join(_ROOT, f), encoding="utf-8") as fh:
                doc = json.load(fh)
            fam, name = doc.get("family") or "", doc.get("name") or ""
        except (OSError, ValueError):
            pass
        has_note = os.path.exists(os.path.join(_ROOT, "notes", slug + ".md"))
        return {"date": date, "slug": slug, "family": fam, "name": name,
                "note": has_note,
                "hay": f"{slug} {fam} {name}".lower()}

    codes = [code_row(d, f) for d, f in added("codes/")
             if f.endswith(".json")]
    camps = campaign_rows(since)
    fnotes = []
    for d, f in added("fieldnotes/"):
        if not f.endswith(".md") or f.endswith("README.md"):
            continue
        title, topics = _fieldnote_meta(os.path.join(_ROOT, f))
        fnotes.append({"date": d, "path": f, "title": title, "topics": topics,
                       "hay": f"{f} {title} {' '.join(topics)}".lower()})

    n_codes, n_fnotes, n_camps = len(codes), len(fnotes), len(camps)
    if want:
        codes = [c for c in codes if any(w in c["hay"] for w in want)]
        fnotes = [f for f in fnotes if any(w in f["hay"] for w in want)]
        camps = [c for c in camps if any(w in c["hay"] for w in want)]
    n_note = sum(1 for c in codes if c["note"])

    def public(rows):
        return [{k: v for k, v in r.items() if k != "hay"} for r in rows]

    _result(args).update(
        days=args.days, filters=want,
        counts={"codes": n_codes, "fieldnotes": n_fnotes,
                "campaigns": n_camps, "codes_with_note": n_note},
        codes=public(codes), fieldnotes=public(fnotes),
        campaigns=public(camps))

    lim = None if args.full else max(1, args.limit)
    filt = f" matching {' + '.join(want)}" if want else ""
    print(f"board activity, last {args.days} days{filt}: "
          f"{_plural(len(codes), 'code')} ({n_note} with a research note), "
          f"{_plural(len(fnotes), 'fieldnote')}, "
          f"{_plural(len(camps), 'campaign summary', 'campaign summaries')}")
    if want:
        print(f"  (of {_plural(n_codes, 'code')}, "
              f"{_plural(n_fnotes, 'fieldnote')}, and "
              f"{_plural(n_camps, 'campaign summary', 'campaign summaries')} "
              f"in the window)")

    shown = codes if lim is None else codes[:lim]
    if shown:
        print("codes:")
    for c in shown:
        tag = f"notes/{c['slug']}.md" if c["note"] else "no research note"
        fam = f"  {c['family']}" if c["family"] else ""
        print(f"  {c['date']}  [[{c['slug'].replace('-', ',')}]]{fam}  ({tag})")
    if lim is not None and len(codes) > lim:
        print(f"  ... {len(codes) - lim} more (--limit N, --full)")

    shown = fnotes if lim is None else fnotes[:lim]
    if shown:
        print("fieldnotes (negative results / calibration):")
    for f in shown:
        print(f"  {f['date']}  {f['path']}")
        if f["title"]:
            topics = f"  [{', '.join(f['topics'])}]" if f["topics"] else ""
            print(f"      {f['title']}{topics}")
    if lim is not None and len(fnotes) > lim:
        print(f"  ... {len(fnotes) - lim} more (--limit N, --full)")

    shown = camps if lim is None else camps[:lim]
    if shown:
        print("campaign summaries (committed research/campaigns/*/summary.json):")
    for c in shown:
        fams = f"  [{', '.join(c['families'])}]" if c["families"] else ""
        # A crash is not a result, so it is shown apart from the negatives
        # and only when there is one to show.
        aborted = (f", {c['aborted_experiments']} aborted"
                   if c["aborted_experiments"] else "")
        print(f"  {c['date']}  {c['path']}")
        print(f"      {c['campaign_id']}: {c['status']}, "
              f"{_plural(c['experiments'], 'experiment')}, "
              f"{_plural(c['survivors'], 'survivor')}, "
              f"{_plural(c['frontier_advances'], 'frontier advance')}, "
              f"{_plural(c['negative_results'], 'negative result')}"
              f"{aborted}{fams}")
    if lim is not None and len(camps) > lim:
        print(f"  ... {len(camps) - lim} more (--limit N, --full)")

    print("full log: docs research-log page, or ls notes/ fieldnotes/ "
          "research/campaigns/")
    return 0


def campaign_rows(since):
    """Return the committed campaign summaries touched in the window, as data.

    Item 4 of issue #2314: a campaign that commits
    research/campaigns/<id>/summary.json (schema/campaign.schema.json, written
    by research/kit/campaign.py) is consumable here without reading its
    report, so the next session learns what was screened, what survived, and
    what did not, from the summary rather than from prose. Summaries are
    rewritten in place as a campaign runs, so the date is the file's last
    commit in the window, not its first.
    """
    root = os.path.join(_ROOT, "research", "campaigns")
    rows = []
    if not os.path.isdir(root):
        return rows
    for cid in sorted(os.listdir(root)):
        path = os.path.join(root, cid, "summary.json")
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, _ROOT)
        r = subprocess.run(
            ["git", "log", "-1", since, "--pretty=format:%as", "--", rel],
            cwd=_ROOT, capture_output=True, text=True, check=False)
        date = r.stdout.strip()
        if not date:
            continue                     # not committed, or not in the window
        try:
            with open(path, encoding="utf-8") as fh:
                summ = json.load(fh)
        except (OSError, ValueError):
            continue
        exps = summ.get("experiments") or []
        fams = sorted({e.get("family") for e in exps if e.get("family")})
        stopped = summ.get("stopped_by") or {}
        row = {
            "date": date, "path": rel,
            "campaign_id": summ.get("campaign_id") or cid,
            "campaign_name": summ.get("campaign_name") or "",
            "status": summ.get("status") or "",
            "stopped_by": stopped.get("type"),
            "families": fams,
            "experiments": len(exps),
            "survivors": len(summ.get("survivors") or []),
            "frontier_advances": summ.get("frontier_advances") or 0,
            "negative_results": len(summ.get("negative_results") or []),
            "aborted_experiments": summ.get("aborted_experiments") or 0,
            "budget_consumed": (summ.get("budget") or {}).get("consumed") or {},
            "report": summ.get("report") or "",
        }
        row["hay"] = (f"{row['campaign_id']} {row['campaign_name']} "
                      f"{' '.join(fams)} {row['report']}").lower()
        rows.append(row)
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows



# ---------------------------------------------------------------------------
# screened: the shared screening registry, read across committed summaries
# ---------------------------------------------------------------------------
# Issue #2726. research/candidates/ is gitignored working output, so a family
# screened and discarded leaves nothing behind and the next session pays for
# it again. The committed record is research/campaigns/<id>/summary.json, and
# this is the reader over all of them: one call answers whether a family
# member was screened, at what depth, and how it went. Advisory only -- the
# gate remains the only thing that admits a code.

def screening_rows(family="", params=None, verdicts=()):
    """Experiment rows across committed summaries, filtered.

    ``params`` matches as a subset: a row matches when every queried key is
    present on it and compares equal, so a query on the ring alone finds
    every member screened over that ring. Values compare as strings, since a
    campaign that wrote l as "6" and one that wrote 6 screened the same
    member.
    """
    root = os.path.join(_ROOT, "research", "campaigns")
    want = {str(k): str(v) for k, v in (params or {}).items()}
    rows, quality, summaries = [], [], 0
    if not os.path.isdir(root):
        return rows, quality, summaries
    for cid in sorted(os.listdir(root)):
        path = os.path.join(root, cid, "summary.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                summ = json.load(fh)
        except (OSError, ValueError):
            continue
        summaries += 1
        rel = os.path.relpath(path, _ROOT)
        ident = summ.get("campaign_id") or cid
        backfilled = bool(summ.get("backfilled"))
        for q in summ.get("screen_quality") or []:
            if family and q.get("family") != family:
                continue
            quality.append(dict(q, campaign_id=ident, path=rel))
        for exp in summ.get("experiments") or []:
            if family and exp.get("family") != family:
                continue
            if verdicts and exp.get("verdict") not in verdicts:
                continue
            got = {str(k): str(v) for k, v in (exp.get("params") or {}).items()}
            if any(got.get(k) != v for k, v in want.items()):
                continue
            screened = exp.get("screened") or {}
            rows.append({
                "campaign_id": ident, "path": rel,
                "backfilled": backfilled,
                "family": exp.get("family") or "", "seed": exp.get("seed"),
                "params": exp.get("params") or {},
                "screened_d": screened.get("d"),
                "trials": screened.get("trials"),
                "backend": screened.get("backend") or "",
                "rung": screened.get("rung"),
                "verdict": exp.get("verdict") or "",
                "mode": exp.get("mode") or "",
                "survivors": exp.get("survivors") or 0,
                "note": exp.get("note") or "",
            })
    return rows, quality, summaries


def _kv_pairs(items):
    """Parse repeated --param k=v into pairs, rejecting a bare token."""
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--param wants key=value, got {item!r}")
        k, v = item.split("=", 1)
        yield k.strip(), v.strip()


def _print_registry_coverage(rows, quality):
    """Say how much of the registry is actually usable, once, at the end.

    The per-row lines above are honest one at a time -- each says "depth not
    recorded" rather than inventing a number -- but a reader who stops after the
    first screenful cannot tell a well-populated registry from an empty one, and
    the rows are printed campaign by campaign, so one large structural campaign
    can fill the whole visible window with its depth-less rows. The aggregate is
    the thing that answers "can I trust this to tell me what was already tried".

    A row without a depth is not necessarily a gap: a structural or solver
    reading has no trial count by nature, and a backfilled summary records why.
    So this reports coverage and says what a depth-less row costs, rather than
    calling the registry incomplete.
    """
    if not rows:
        return
    with_depth = sum(1 for r in rows if r["screened_d"] is not None)
    with_trials = sum(1 for r in rows if r["trials"])
    with_verdict = sum(1 for r in rows if r["verdict"])
    print(f"  registry coverage: {with_depth} of {len(rows)} rows carry a screened "
          f"weight ({with_trials} a trial count), {with_verdict} a verdict.")
    if len(rows) - with_depth:
        print("    a row with no depth cannot tell you whether the member is worth "
              "retrying deeper or was screened hard and dropped; check that "
              "campaign's backfilled note before paying for it again.")
    if not quality:
        print("    no screen-quality rows: nothing committed yet pairs a screened "
              "distance with a gate verdict, so the screen's ordering is uncalibrated "
              "against the gate for every family.")


def cmd_screened(args):
    """Report whether this family at these parameters was already screened.

    The question to ask before paying for a ladder. Reads only committed
    campaign summaries, so a row here is a record someone left deliberately,
    not a reading of one machine's working directory.
    """
    params = dict(_kv_pairs(args.param))
    if args.params:
        try:
            params.update(json.loads(args.params))
        except ValueError as e:
            raise SystemExit(f"--params is not JSON: {e}") from None
    rows, quality, summaries = screening_rows(
        family=args.family, params=params,
        verdicts=tuple(args.verdict) if args.verdict else ())

    _result(args).update(query={"family": args.family, "params": params,
                                "verdict": list(args.verdict or [])},
                         summaries_read=summaries, matches=len(rows),
                         rows=rows, screen_quality=quality)

    what = args.family or "any family"
    if params:
        what += " at " + ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
    if not rows:
        print(f"{what}: no committed campaign summary records screening it "
              f"({summaries} read)")
        return
    print(f"{what}: {_plural(len(rows), 'screening record')} across "
          f"{_plural(summaries, 'campaign summary', 'campaign summaries')}")
    lim = None if args.full else max(1, args.limit)
    for r in (rows if lim is None else rows[:lim]):
        depth = (f"d<={r['screened_d']} at {r['trials']} trials"
                 if r["screened_d"] is not None else
                 (f"{r['trials']} trials, no weight recorded"
                  if r["trials"] else "depth not recorded"))
        if r["backend"]:
            depth += f" ({r['backend']})"
        tail = f"  {r['verdict']}" if r["verdict"] else "  verdict not recorded"
        if r["backfilled"]:
            tail += ", backfilled"
        pretty = ", ".join(f"{k}={v}" for k, v in sorted(r["params"].items()))
        shown = pretty or "(no construction parameters recorded)"
        print(f"  {r['campaign_id']}  {r['family']}  {shown}")
        print(f"    {depth}{tail}")
    if lim is not None and len(rows) > lim:
        print(f"  ... {len(rows) - lim} more (--limit N, --full)")
    _print_registry_coverage(rows, quality)
    for q in quality:
        if q.get("spearman") is None:
            print(f"screen quality, {q['family']}: undefined over "
                  f"{_plural(q.get('pairs') or 0, 'pair')} ({q['campaign_id']})")
        else:
            print(f"screen quality, {q['family']}: Spearman "
                  f"{q['spearman']:+.2f} over "
                  f"{_plural(q.get('pairs') or 0, 'pair')} ({q['campaign_id']})")


# ---------------------------------------------------------------------------
# curve: best-so-far verified efficiency against trials spent (issue #2735)
# ---------------------------------------------------------------------------
# Two series on one axis, because the failure this exists to show is the
# disagreement between them. A screen that inflates at low depth reads above
# the cell bar while the gate admits nothing near it, which is the 2026-09-20
# shape: 5.3M trials on a ladder whose deep rungs had already settled below
# the bar. Derived from the rows a campaign already commits; it measures
# nothing.

def _cell_bar(cell_query):
    """Best kd^2/n on the board in the named cell, using the site's own cells."""
    entries = _load_board_entries()
    if not entries:
        return None, None
    toks = [t for t in re.split(r"[/, ]+", cell_query.lower()) if t]
    best, label = None, None
    for e in entries:
        for L, W in cells(e):
            hay = (f"{L} {W} {LOCALITY_LABEL.get(L, L)} "
                   f"{WEIGHT_LABEL.get(W, W)}").lower()
            if not all(t in hay for t in toks):
                continue
            if best is None or (e.get("eff") or 0) > best:
                best, label = e.get("eff") or 0, f"{L}/{W}"
    return best, label


def _plot(curve, width=58, height=14):
    """Render the curve as text: '#' verified best-so-far, 'o' screened."""
    pts = [(p["trials_cumulative"], p["screened_kd2_over_n"],
            p["verified_best_kd2_over_n"])
           for f in curve["families"] for p in f["points"]]
    ys = [v for _, s, v in pts for v in (s, v) if v is not None]
    bar = (curve.get("bar") or {}).get("kd2_over_n")
    if bar is not None:
        ys.append(bar)
    xs = [x for x, _, _ in pts if x > 0]
    if not ys or not xs:
        return ["  (nothing to plot: no row carries both a reading and a "
                "trial count)"]
    lo_y, hi_y = min(ys), max(ys)
    if hi_y == lo_y:
        hi_y = lo_y + 1.0
    lo_x, hi_x = math.log10(min(xs)), math.log10(max(xs))
    if hi_x == lo_x:
        hi_x += 1.0

    grid = [[" "] * width for _ in range(height)]

    def cell(x, y):
        col = int(round((math.log10(x) - lo_x) / (hi_x - lo_x) * (width - 1)))
        row = int(round((hi_y - y) / (hi_y - lo_y) * (height - 1)))
        return max(0, min(height - 1, row)), max(0, min(width - 1, col))

    if bar is not None:
        r, _ = cell(max(xs), bar)
        grid[r] = ["-"] * width
    for x, s, v in pts:
        if x <= 0:
            continue
        if s is not None:
            r, c = cell(x, s)
            grid[r][c] = "o"
    for x, s, v in pts:
        if x > 0 and v is not None:
            r, c = cell(x, v)
            grid[r][c] = "#"

    out = []
    for i, row in enumerate(grid):
        label = f"{hi_y:8.2f}" if i == 0 else (
            f"{lo_y:8.2f}" if i == height - 1 else " " * 8)
        out.append(f"  {label} |{''.join(row)}")
    out.append(" " * 10 + f"  +{'-' * width}")
    out.append(" " * 10 + f"   {_si(min(xs)):<{width - 10}}"
                          f"{_si(max(xs)):>10}")
    out.append(" " * 10 + "   cumulative trials (log scale)")
    return out


def _si(v):
    """Shorten a trial count so a reader takes it in at a glance."""
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if v >= cut:
            return f"{v / cut:g}{suffix}"
    return f"{v:g}"


def cmd_curve(args):
    """Plot best-so-far verified efficiency against trials spent, per family."""
    path = os.path.join(_ROOT, "research", "campaigns", args.campaign,
                        "summary.json")
    if not os.path.exists(path):
        raise SystemExit(f"no committed summary at "
                         f"{os.path.relpath(path, _ROOT)}")
    with open(path, encoding="utf-8") as fh:
        summary = json.load(fh)

    bar, source = args.bar, "--bar"
    if bar is None:
        camp = os.path.join(os.path.dirname(path), "campaign.json")
        if os.path.exists(camp):
            with open(camp, encoding="utf-8") as fh:
                obj = (json.load(fh).get("campaign") or {}).get("objective")
            if (obj or {}).get("target") is not None:
                bar, source = obj["target"], "the campaign's objective.target"
    if bar is None and args.cell:
        bar, label = _cell_bar(args.cell)
        source = f"the board's best in {label}" if label else None
    if bar is None:
        source = None

    curve = curve_from_summary(summary, bar=bar, bar_source=source)
    _result(args).update(curve=curve)

    if args.write:
        out = os.path.join(os.path.dirname(path), "curve.json")
        write_curve(curve, out)
        print(f"wrote {os.path.relpath(out, _ROOT)}")

    h = curve["headline"]
    print(f"{curve['campaign_id']}: best verified kd^2/n "
          f"{_fmt(h['best_verified_kd2_over_n'])} over "
          f"{_si(h['trials_spent'])} trials")
    if bar is None:
        print("  no bar: pass --bar, or --cell to take the board's best in a "
              "cell, or give the campaign an objective.target")
    else:
        print(f"  bar {bar:g} ({source})")
        if h["reached_bar"]:
            print(f"  reached it after {_si(h['trials_to_bar'])} trials")
        elif h["screened_reached_bar_but_gate_did_not"]:
            print("  never reached it, and the screen did: the ladder read "
                  "above the bar and the gate admitted nothing there")
        else:
            print("  never reached it, and neither did the screen")
    for line in _plot(curve):
        print(line)
    print("  # best verified so far, o each screened reading, - the bar")
    for f in curve["families"]:
        print(f"  {f['family']}: {_fmt(f['best_verified_kd2_over_n'])} "
              f"verified over {_si(f['trials_spent'])} trials"
              + (f", bar at {_si(f['trials_to_bar'])}"
                 if f["trials_to_bar"] is not None else ""))


def _fmt(v):
    """Format an efficiency, or say it is absent."""
    return "none" if v is None else f"{v:.2f}"


# ---------------------------------------------------------------------------
# reproduce: one command that re-runs an entry's evidence chain (issue #2220)
# ---------------------------------------------------------------------------
# Orchestration only. Every stage below calls the trusted module that already
# owns it -- validate_candidate, circuit_verify, ler_verify, certify -- so
# there is no second implementation of any check here, and verify/ is imported
# read-only. The receipt this produces is NON-AUTHORITATIVE: running it never
# changes whether an entry passes, what tier it holds, or where it ranks.

REPRO_STAGES = ("verify", "circuits", "ler", "certify", "construction")

# What a stage can come back as. Kept apart on purpose: "the claim re-derived
# bit for bit" and "a Monte Carlo re-measurement landed inside the declared
# interval" are different evidence, and collapsing them would overstate the
# weaker one.
ST_SKIPPED = "skipped"                      # flag not requested
ST_NOT_APPLICABLE = "not_applicable"        # the entry makes no such claim
ST_NOT_REPRODUCIBLE = "not_reproducible"    # the claim exists, nothing can re-derive it
ST_BUDGET = "budget_exceeded"               # hit its declared bound
ST_VERIFIED = "verified"                    # trusted gate passed at the declared seed
ST_RECONSTRUCTED = "reconstructed"          # code object rebuilt and fingerprint matched
ST_CERTIFIED = "certified"                  # certify.py re-run and agreed with certs/
ST_BENCH = "benchmark_reproduced"           # circuits bit-exact / ler within its interval
ST_FAILED = "failed"                        # ran, and disagreed


def _repro_root():
    return _ROOT


def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _repro_manifest(slug):
    """Read the committed manifest for an entry, or None.

    A manifest is optional because everything except the construction status is
    derivable from the entry itself. It exists to declare the one thing the
    entry cannot: whether the search that found the code was committed.
    """
    path = os.path.join(_repro_root(), "repro", f"{slug}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _stage_decl(manifest, stage):
    return ((manifest or {}).get("stages") or {}).get(stage) or {}


def _repro_environment():
    """Record what this reproduction is actually running under."""
    env = {"python": sys.version.split()[0]}
    try:
        import stim
        env["stim"] = stim.__version__
    except Exception:
        env["stim"] = None
    lock = os.path.join(_repro_root(), "uv.lock")
    env["uv_lock_sha256"] = _sha256_file(lock) if os.path.exists(lock) else None
    try:
        import validate_candidate as _vc
        env["validator_source_sha256"] = _vc.source_sha256()
    except Exception:
        env["validator_source_sha256"] = None
    env["commit"] = _git_head()
    return env


def _git_head():
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_repro_root(),
                             capture_output=True, text=True, check=False)
        return out.stdout.strip() or None
    except OSError:
        return None


def _repro_verify(doc, decl, seed):
    """Stage 1: the trusted gate, at the declared seed."""
    import validate_candidate as vc
    verdict = vc.validate_candidate(doc, seed=seed, refute=False)
    gates = verdict.get("gates", {})
    cand = verdict.get("candidate", {})
    ok = bool(gates.get("verify", {}).get("ok"))
    return {
        "status": ST_VERIFIED if ok else ST_FAILED,
        "seed": verdict.get("validator", {}).get("seed", seed),
        "computed": {"n": cand.get("n"), "k": cand.get("k"), "d": cand.get("d"),
                     "fingerprint": cand.get("fingerprint"),
                     "signature": cand.get("signature")},
        "detail": "structural checks and both witnesses re-checked"
        if ok else "; ".join(c["detail"] for c in
                             gates.get("verify", {}).get("checks", [])
                             if not c.get("ok"))[:400],
    }


def _repro_circuits(doc, slug, decl):
    """Stage 2: re-derive the .dem from the committed .stim, bit for bit."""
    if not doc.get("circuit"):
        return {"status": ST_NOT_APPLICABLE, "detail": "no circuit block"}
    from circuit_verify import verify_circuit
    cdir = os.path.join(_repro_root(), "circuits", slug)
    if not os.path.isdir(cdir):
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": f"circuits/{slug}/ is not in the tree"}
    rep = verify_circuit(doc, cdir)
    bad = [c["detail"] for c in rep.get("checks", []) if not c.get("ok")]
    return {
        "status": ST_BENCH if rep.get("ok") else ST_FAILED,
        "determinism": "bit_exact_under_pin",
        "stim_version": (doc.get("circuit") or {}).get("stim_version"),
        "detail": "detector error model re-derived from the committed .stim"
        if rep.get("ok") else "; ".join(bad)[:400],
    }


def _repro_ler(doc, slug, decl):
    """Stage 3: the LER arithmetic exactly, then a seeded re-measurement.

    ``verify_ler`` owns both halves. Agreement here is agreement inside the
    entry's own ci95, which is what a Monte Carlo claim can offer and is
    reported as such rather than as a match.
    """
    circ = doc.get("circuit") or {}
    if not circ.get("ler"):
        return {"status": ST_NOT_APPLICABLE, "detail": "no circuit.ler block"}
    from ler_verify import verify_ler
    cdir = os.path.join(_repro_root(), "circuits", slug)
    if not os.path.isdir(cdir):
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": f"circuits/{slug}/ is not in the tree"}
    rep = verify_ler(doc, cdir)
    bad = [c["detail"] for c in rep.get("checks", []) if not c.get("ok")]
    if any("ldpc is not installed" in b for b in bad):
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": "the decoder is missing; install the research extra"}
    return {
        "status": ST_BENCH if rep.get("ok") else ST_FAILED,
        "determinism": "arithmetic_exact_remeasurement_within_ci95",
        "detail": "ler_per_round and ci95 recomputed, and re-measured on an "
                  "independent seed inside the declared interval"
        if rep.get("ok") else "; ".join(bad)[:400],
    }


def _repro_certify(doc, slug, decl):
    """Stage 4: re-run the bounded exact certifier and compare to certs/."""
    cert_path = os.path.join(_repro_root(), "certs", f"{slug}.json")
    if not os.path.exists(cert_path):
        return {"status": ST_NOT_APPLICABLE, "detail": "no committed cert"}
    with open(cert_path, encoding="utf-8") as f:
        committed = json.load(f)
    tlim = decl.get("tlim_seconds", 600)
    try:
        from certify import certify
    except ImportError as e:
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": f"the certifier is unavailable: {e}"}
    got = certify(doc, tlim=tlim)
    if not got.get("d_exact") and committed.get("d_exact"):
        return {"status": ST_BUDGET,
                "detail": f"the solver did not close both sides within "
                          f"{tlim}s; the committed cert claims exact"}
    same = (got.get("d_exact") == committed.get("d_exact")
            and all(got.get("sides", {}).get(s, {}).get("value")
                    == committed.get("sides", {}).get(s, {}).get("value")
                    for s in ("X", "Z")))
    return {
        "status": ST_CERTIFIED if same else ST_FAILED,
        "tlim_seconds": tlim,
        "solver": got.get("solver"),
        "detail": "re-certified and agreed with certs/" + slug + ".json"
        if same else f"disagrees with the committed cert: {got.get('sides')}",
    }


def _repro_construction(doc, slug, decl):
    """Stage 5: re-derive H_X and H_Z from a committed recipe, if there is one.

    The code object always reconstructs, because the matrices are in the entry.
    What usually does not is the SEARCH that found it. An entry with no
    committed recipe says not_reproducible and says why, which is a first-class
    answer rather than a gap.
    """
    status = decl.get("status")
    if status in (None, "not_reproducible"):
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": decl.get("reason")
                or "no constructor recipe is declared for this entry"}
    if status == "not_applicable":
        return {"status": ST_NOT_APPLICABLE, "detail": decl.get("reason", "")}
    script = decl.get("script")
    if not script:
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": "the manifest declares the stage applicable but "
                          "names no script"}
    path = os.path.join(_repro_root(), script)
    if not os.path.exists(path):
        return {"status": ST_NOT_REPRODUCIBLE,
                "detail": f"{script} is not in this tree"}
    cmd = [sys.executable, path] + [str(a) for a in decl.get("args", [])]
    budget = decl.get("budget_seconds", 900)
    try:
        run = subprocess.run(cmd, cwd=_repro_root(), capture_output=True,
                             text=True, timeout=budget, check=False)
    except subprocess.TimeoutExpired:
        return {"status": ST_BUDGET,
                "detail": f"{script} exceeded {budget}s"}
    if run.returncode != 0:
        return {"status": ST_FAILED,
                "detail": f"{script} exited {run.returncode}: "
                          f"{run.stderr.strip()[:300]}"}
    # The recipe is matched by the fingerprint the verifier computes, not by
    # the bytes of a rebuilt file: two runs may order rows differently and
    # still be the same stabilizer code.
    from qldpc_verify import verify as _verify
    want = (_verify(doc) or {}).get("fingerprint")
    got = None
    for line in (run.stdout or "").splitlines():
        if line.strip().startswith("fingerprint="):
            got = line.strip().split("=", 1)[1].strip()
    if got is None:
        return {"status": ST_FAILED,
                "detail": f"{script} printed no 'fingerprint=' line to compare"}
    return {
        "status": ST_RECONSTRUCTED if got == want else ST_FAILED,
        "script": script,
        "detail": "the recipe rebuilt this entry's stabilizer code"
        if got == want else f"rebuilt a different code ({got} != {want})",
    }


def cmd_reproduce(args):
    """Re-run one board entry's evidence chain and write a receipt.

    The cheap deterministic core (the trusted gate) runs by default; every
    expensive stage is opt-in behind its own flag, because an exact
    certification or an LER re-measurement is minutes to hours and CI is not
    where they belong.
    """
    slug = args.slug[:-5] if args.slug.endswith(".json") else args.slug
    slug = os.path.basename(slug)
    path = os.path.join(_repro_root(), "codes", f"{slug}.json")
    if not os.path.exists(path):
        print(f"no such board entry: codes/{slug}.json", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    manifest = _repro_manifest(slug)
    digest = _sha256_file(path)

    want = {s: getattr(args, s) for s in REPRO_STAGES}
    if args.all:
        want = {s: True for s in REPRO_STAGES}
    want["verify"] = True                     # the core is never skipped

    print(f"reproduce {slug}  sha256={digest[:16]}...")
    if manifest:
        print(f"  manifest: repro/{slug}.json (version "
              f"{manifest.get('manifest_version')})")
        declared = manifest.get("artifact_sha256")
        if declared and declared != digest:
            print("  note: the entry has changed since the manifest was "
                  "written; both digests are in the receipt")
    else:
        print("  manifest: none committed; stages derived from the entry")

    runners = {
        "verify": lambda d: _repro_verify(doc, d, args.seed),
        "circuits": lambda d: _repro_circuits(doc, slug, d),
        "ler": lambda d: _repro_ler(doc, slug, d),
        "certify": lambda d: _repro_certify(doc, slug, d),
        "construction": lambda d: _repro_construction(doc, slug, d),
    }
    stages = {}
    for name in REPRO_STAGES:
        decl = _stage_decl(manifest, name)
        if not want[name]:
            stages[name] = {"status": ST_SKIPPED,
                            "detail": f"--{name} not requested"}
        elif decl.get("status") == "not_applicable":
            stages[name] = {"status": ST_NOT_APPLICABLE,
                            "detail": decl.get("reason", "declared not applicable")}
        else:
            stages[name] = runners[name](decl)
        st = stages[name]
        print(f"  {name:<13} {st['status']:<22} {st.get('detail', '')[:90]}")

    failed = [n for n, s in stages.items() if s["status"] == ST_FAILED]
    overall = "disagreed" if failed else "reproduced"
    receipt = {
        "receipt_version": "1",
        "receipt_kind": "reproduction",
        "artifact": {"slug": slug, "path": f"codes/{slug}.json",
                     "sha256": digest,
                     "manifest_sha256": (
                         _sha256_file(os.path.join(_repro_root(), "repro",
                                                   f"{slug}.json"))
                         if manifest else None),
                     "manifest_artifact_sha256": (manifest or {}).get(
                         "artifact_sha256")},
        "environment": _repro_environment(),
        "stages": stages,
        "overall": overall,
        "authority": "non-authoritative: this receipt records a reproduction "
                     "attempt and never changes an entry's verdict, tier, or "
                     "ranking",
    }
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(receipt, f, indent=2, sort_keys=True)
            f.write("\n")
        print(f"  receipt -> {args.out}")
    print(f"  overall: {overall}")
    return 1 if failed else 0


def main(argv=None):
    # Windows consoles default to a legacy code page, and the summaries print
    # "≤" (d <= 12, weight ≤ 6). Without this the run dies in the final print,
    # after the search and the verification have already succeeded.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")

    p = argparse.ArgumentParser(
        prog="qldpc", description="qLDPC challenge submission tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="build, verify, and prepare a code submission")
    s.add_argument("code", help=".npz with H_X/H_Z (+ optional coords) or a "
                                ".json draft")
    s.add_argument("--authors", nargs="+", required=True,
                   help="one or more: @github-handle and/or 'First Last'")
    s.add_argument("--anonymous", action="store_true",
                   help="explicitly submit without a GitHub @handle; the "
                        "entry will not be bound to an account")
    s.add_argument("--construction", default="",
                   help="how the code was built (family, polynomials, search)")
    s.add_argument("--model", default="",
                   help="self-reported model that produced it, named to a specific "
                        "version, e.g. 'Claude Opus 4.8' (not a bare 'Claude'), or "
                        "'human' (claimed, not verified; the verifier requires a "
                        "version if a model is named)")
    s.add_argument("--notes", default="")
    s.add_argument("--note-file", default="",
                   help="markdown research note staged as notes/<slug>.md and "
                        "rendered publicly beside the code: the search story "
                        "— hypothesis, sweep sizes, confirmation ladder, dead "
                        "ends (see notes/TEMPLATE.md; 10 KiB cap)")
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
                   help="coordinates file (.npz key coords, or whitespace .txt), "
                        "one [x, y] or [x, y, z] row per qubit; the verifier "
                        "derives the 2d-local class from a planar layout")
    s.add_argument("--layers", type=int, default=1,
                   help="physical layers for a 2d-local layout "
                        "(1 = single layer, 2 = bilayer); default 1")
    b = s.add_argument_group(
        "search budget",
        "optional provenance.search_budget block (schema 0.3): what the search "
        "that produced this code cost. Self-reported and unchecked; recorded so "
        "cost per discovery is comparable across entries. Flags override keys "
        "of --budget-json.")
    b.add_argument("--budget-json", default="", metavar="FILE_OR_JSON",
                   help="JSON object with any of: candidates_screened, "
                        "ris_trials_per_side, cpu_hours, gpu_hours, llm_tokens "
                        "(model -> tokens), wall_clock_hours, tool, notes; a "
                        "file path or an inline '{...}'")
    b.add_argument("--budget-candidates-screened", type=int, default=None,
                   metavar="N", help="codes built and screened before this one")
    b.add_argument("--budget-ris-trials-per-side", type=int, default=None,
                   metavar="N", help="deepest RIS budget spent per side on this "
                                     "code during the search")
    b.add_argument("--budget-cpu-hours", type=float, default=None, metavar="H")
    b.add_argument("--budget-gpu-hours", type=float, default=None, metavar="H")
    b.add_argument("--budget-llm-tokens", action="append", default=None,
                   metavar="MODEL=COUNT",
                   help="tokens consumed per model, repeatable, e.g. "
                        "'Claude Opus 4.8=1800000'")
    b.add_argument("--budget-wall-clock-hours", type=float, default=None,
                   metavar="H")
    b.add_argument("--budget-tool", default="",
                   help="the search harness, e.g. 'research/kit/search.py + gf2_fast'")
    b.add_argument("--budget-notes", default="",
                   help="what the numbers cover and what they leave out")
    c = s.add_argument_group(
        "circuit tier",
        "memory_x and memory_z syndrome-extraction circuits (RFC 0001) are "
        "generated, searched for d_circ witnesses, verified, and written under "
        "circuits/<slug>/ by default: an interleaved two-block schedule for "
        "bicycle-type codes, a layout zigzag for surface patches, and a "
        "generic sequential schedule otherwise. d_circ is penalty-only, so a "
        "circuit can discount an entry but never inflate it.")
    c.add_argument("--no-circuit", action="store_true",
                   help="submit the code tier only, no circuits")
    c.add_argument("--circuits", default="", metavar="DIR",
                   help="use your own memory_x.stim and memory_z.stim from DIR "
                        "(canonical noise recipe, see verify/circuit_tools.py) "
                        "instead of generating them; the .dem files are "
                        "derived with the pinned stim and the witnesses "
                        "searched for you")
    c.add_argument("--circuit-rounds", type=int, default=None, metavar="R",
                   help="extraction rounds per memory circuit (default d, the "
                        "minimum the verifier accepts)")
    c.add_argument("--circuit-candidates", type=int, default=6, metavar="N",
                   help="schedules screened at two rounds before the deep "
                        "search settles on one (default 6)")
    c.add_argument("--circuit-seconds", type=float, default=180.0,
                   metavar="S",
                   help="wall-clock cap per basis for the deep witness search "
                        "(default 180; the CI gate targets 120)")
    c.add_argument("--circuit-seed", type=int, default=0)
    s.add_argument("--trials", type=int, default=20000,
                   help="RIS trials for the distance witness search")
    s.add_argument("--fast-trials", type=int, default=2_000_000,
                   help="gf2_fast trials used to tighten the claim "
                        "(0 disables the accelerator)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", default=os.path.join(_ROOT, "codes"))
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing codes/<slug>.json")
    s.add_argument("--dry-run", action="store_true",
                   help="build and verify but do not write the file")
    s.add_argument("--json", action="store_true",
                   help="print exactly one JSON object on stdout describing "
                        "the result (stage, slug, code_path, note_path, "
                        "title, body_file, branch, next_steps, pr_url, or "
                        "error) and move the human-readable output to "
                        "stderr; with --dry-run the object carries the full "
                        "submission under `doc`")
    s.add_argument("--open-pr", action="store_true",
                   help="create the branch, commit, push, and open the PR")
    s.add_argument("--base-ref", default="",
                   help="start the submission branch from this ref (e.g. "
                        "origin/main) and return to the current branch "
                        "afterwards, so successive --open-pr runs from one "
                        "checkout produce independent one-code PRs")
    s.set_defaults(func=cmd_submit)

    r = sub.add_parser("recent", help="what landed recently: codes, research "
                                      "notes, fieldnotes (read before you "
                                      "search)")
    r.add_argument("--days", type=int, default=14)
    r.add_argument("--limit", type=int, default=10,
                   help="rows per section (default 10); --full for all")
    r.add_argument("--full", action="store_true",
                   help="print every row instead of the newest --limit")
    r.add_argument("--family", default="",
                   help="only rows mentioning this family tag, e.g. "
                        "bivariate-bicycle")
    r.add_argument("--topic", default="",
                   help="only rows mentioning this topic, matched against "
                        "fieldnote topics and titles and against code names")
    r.add_argument("--json", action="store_true",
                   help="print one JSON record on stdout (codes, fieldnotes, "
                        "and campaign summaries in the window, with counts) "
                        "instead of the listing")
    r.set_defaults(func=cmd_recent)

    sc = sub.add_parser("screened",
                        help="was this family at these parameters already "
                             "screened, at what depth, and how did it go "
                             "(committed campaign summaries only)")
    sc.add_argument("--family", default="",
                    help="family tag, e.g. generalized-bicycle")
    sc.add_argument("--param", action="append", default=[], metavar="K=V",
                    help="construction parameter to match, repeatable; "
                         "matched as a subset, so --param ring=Z_341 finds "
                         "every member screened over that ring")
    sc.add_argument("--params", default="",
                    help="the same as a JSON object")
    sc.add_argument("--verdict", action="append", default=[],
                    choices=["passed", "refuted", "duplicate", "dominated",
                             "not_run"],
                    help="only rows with this gate verdict, repeatable")
    sc.add_argument("--limit", type=int, default=20,
                    help="rows to print (default 20); --full for all")
    sc.add_argument("--full", action="store_true")
    sc.add_argument("--json", action="store_true",
                    help="print one JSON record on stdout instead of the "
                         "listing")
    sc.set_defaults(func=cmd_screened)

    cv = sub.add_parser("curve",
                        help="best-so-far verified efficiency against trials "
                             "spent, per family, for one campaign")
    cv.add_argument("campaign", help="campaign id, the directory under "
                                     "research/campaigns/")
    cv.add_argument("--bar", type=float, default=None,
                    help="the reference kd^2/n to beat; defaults to the "
                         "campaign's objective.target when it has one")
    cv.add_argument("--cell", default="",
                    help="take the bar from the board's best in this cell, "
                         "e.g. 'unrestricted/weight-6'")
    cv.add_argument("--write", action="store_true",
                    help="also write research/campaigns/<id>/curve.json")
    cv.add_argument("--json", action="store_true",
                    help="print the curve as one JSON record on stdout")
    cv.set_defaults(func=cmd_curve)

    rp = sub.add_parser("reproduce",
                        help="re-run one entry's evidence chain and write a "
                             "reproduction receipt")
    rp.add_argument("slug", help="board entry, e.g. 25-1-5")
    rp.add_argument("--verify", action="store_true",
                    help="the trusted gate (always runs; the flag is for "
                         "symmetry with the others)")
    rp.add_argument("--circuits", action="store_true",
                    help="re-derive the detector error model from the "
                         "committed .stim under the pinned version")
    rp.add_argument("--ler", action="store_true",
                    help="recheck the ler arithmetic and re-measure on an "
                         "independent seed (needs the research extra)")
    rp.add_argument("--certify", action="store_true",
                    help="re-run the bounded exact certifier and compare it "
                         "with certs/<slug>.json")
    rp.add_argument("--construction", action="store_true",
                    help="re-derive the code from its committed recipe, when "
                         "the manifest declares one")
    rp.add_argument("--all", action="store_true",
                    help="every applicable stage; expensive")
    rp.add_argument("--seed", type=int, default=None,
                    help="seed for the trusted gate")
    rp.add_argument("--out", default="",
                    help="write the reproduction receipt to this path")
    rp.set_defaults(func=cmd_reproduce)

    g = sub.add_parser("targets", help="which track cells are open: occupancy "
                                       "and frontier per cell (read before you "
                                       "build)")
    g.add_argument("--cell", default=None,
                   help="focus one cell, e.g. 'weight-6/unrestricted'")
    g.add_argument("--n", type=int, default=None,
                   help="what a code at this blocklength would need")
    g.add_argument("--top", type=int, default=6,
                   help="frontier entries to list per cell (default 6)")
    g.add_argument("--claim", default="",
                   metavar="CELL",
                   help="note that this run is aiming at CELL, e.g. "
                        "'weight-6/unrestricted'. CELL is checked against the "
                        "board's axis names and written weight-first; a name "
                        "that is not a cell is refused with the valid ones. "
                        "Advisory and expiring: it is a note to other "
                        "sessions, not a reservation, and nothing enforces "
                        "it. Two runs may hold one cell at once; the second "
                        "write says whose it displaced")
    g.add_argument("--release", default="", metavar="CELL",
                   help="drop this run's claim on CELL (expiry is the "
                        "backstop; the same cell name is checked)")
    g.add_argument("--campaign", default="",
                   help="campaign id to record alongside a claim, so a reader "
                        "knows who is spending what on this cell")
    g.add_argument("--note", default="",
                   help="one line of context for a claim, e.g. what rung the "
                        "run is at")
    g.add_argument("--ttl", type=int, default=coordination.DEFAULT_CLAIM_MINUTES,
                   metavar="MINUTES",
                   help=f"how long a claim lives (default "
                        f"{coordination.DEFAULT_CLAIM_MINUTES}). Raise it for "
                        f"a long ladder; a claim outliving its run is a squat")
    g.add_argument("--prune", action="store_true",
                   help="delete expired claims and report how many went")
    g.add_argument("--json", action="store_true",
                   help="print one JSON record on stdout instead of the "
                        "listing; carries the live claims as data")
    g.set_defaults(func=cmd_targets)

    b = sub.add_parser("brief", help="one snapshot before a search: a cell's frontier "
                       "and bar, what was screened there, what landed, the fieldnotes")
    b.add_argument("--cell", required=True, help="e.g. 'weight-6/unrestricted'")
    b.add_argument("--family", default="", help="family tag to filter screening, recent codes, and notes")
    b.add_argument("--days", type=int, default=30, help="window for recent codes (default 30)")
    b.add_argument("--top", type=int, default=6, help="frontier entries per cell (default 6)")
    b.add_argument("--limit", type=int, default=8, help="rows per section (default 8)")
    b.add_argument("--json", action="store_true", help="print one JSON record instead")
    b.set_defaults(func=cmd_brief)

    args = p.parse_args(argv)
    if getattr(args, "json", False):
        return _run_json(args)
    return args.func(args)


def _run_json(args):
    """Run the command with a machine-readable contract (issue #2328).

    Everything the command prints goes to stderr; stdout receives exactly one
    JSON object, the command's result record, whether it succeeded or not. A
    usage error raised as SystemExit(<message>) becomes
    {"ok": false, "error": {"class": "usage", "message": ...}} with exit code
    2, so a caller never has to parse prose to learn what happened.
    """
    import contextlib
    res = _result(args)
    stdout = sys.stdout
    rc = 1
    try:
        with contextlib.redirect_stdout(sys.stderr):
            rc = args.func(args)
    except SystemExit as e:
        code = e.code
        if isinstance(code, str):
            res["error"] = {"class": "usage", "message": code}
            rc = 2
        else:
            rc = 0 if code is None else int(code)
            if rc:
                res.setdefault("error", {"class": "exit", "message": f"exit {rc}"})
    rc = 0 if rc is None else int(rc)
    res["ok"] = rc == 0
    res["exit_code"] = rc
    if rc and "error" in res and "class" not in res["error"]:
        res["error"]["class"] = res["error"].get("stage", "error")
    stdout.write(json.dumps(res, indent=1, default=str) + "\n")
    stdout.flush()
    return rc


if __name__ == "__main__":
    sys.exit(main())

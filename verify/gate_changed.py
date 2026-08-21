"""Distance-refutation gate for the codes changed in a PR (CI).

Runs independent bounded, fixed-seed refutation searches -- python RIS
(heuristic_distance), the syndrome decoder (decode/distance, needs ldpc), and,
for frontier-advancing claims, a ~150x-deeper accelerated RIS pass (gf2_fast,
built via `make fast`) whose finds only count after the pinned python stack
validates the witness -- only on the code/example submissions changed in this
PR, and exits non-zero if ANY finds a logical lighter than the claimed distance
(an over-claim). With the extension built, deep claims get 1 python RIS seed
(the audited floor / canary) plus the fast pass; without it they get the full
pre-accelerator battery of 3 python seeds, so a missing or broken extension can
never leave the gate shallower than it was. The syndrome-decoder cross-check is
skipped if ldpc is unavailable. Bulk
re-verification of the whole board stays cheap -- only new/changed files pay the
search cost. The RIS budget is ADAPTIVE (see _budget): trials scale with code
size, so a small code gets near-exhaustive coverage and a large one a
proportionate search; frontier-advancing codes get several independent deep
seeds (tens of thousands of trials each) before they earn the record.

The gate prices the DIFF, not just the code (issue #654): each changed file
is classified against its base-revision counterpart, because what changed
determines what could newly be over-claimed. A layout-only diff (checks and
distance byte-identical to base) skips refutation entirely -- the claim
already survived the gate when it merged and the weekly board sweep keeps
attacking it; everything a layout adds is recomputed deterministically by the
verifier. A tightening diff (a refutation-shaped correction: values strictly
down, new witnesses of exactly the new weights, upper_bound confidence,
nothing else touched) gets the standard shallow pass -- the entry just became
strictly less wrong, and the weekly sweep provides depth. A diff that adds or
raises witness_provenance.survived_samples gets the deep battery regardless
of record status: a survival stamp claims a deep null result and deters
future refuters, so it is itself the claim being vetted. Anything else --
new codes, edited checks, raised values, unclassifiable diffs -- fails closed
to the full existing behavior. Classification is recomputed from the git
diff, never taken from the PR's framing.

Entries with a circuit block (RFC 0001, issue #505) additionally face the
circuit-tier refutation (_circuit_refute): a bounded RIS search on each memory
circuit's re-derived DEM, hunting an undetected logical fault set lighter than
the claimed d_circ. The circuit search is priced by the same diff principle
(circuit_gate_needed): it runs when the circuit claim surface changed -- the
JSON's circuit block, or anything under circuits/<slug>/, whose diffs
map_changed routes here even when the JSON is untouched -- or when the entry
is new; an untouched circuit claim already survived its own gate. In
particular a diff that only adds or edits a circuit block classifies as
layout-only for the CODE tier (checks and distance are unchanged) yet still
pays the circuit search: the code-tier skip must never skip the claim that
actually changed.

Usage:
  python verify/gate_changed.py [--code-root PATH] [BASE] [files...]
    --code-root PATH  repository tree containing the submitted codes
    BASE     git ref to diff against (default origin/main); ignored if files given
    files    explicit code JSONs to gate (otherwise computed from the diff)
"""
import glob
import json
import os
import secrets
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import circuit_tools as CT
import gf2
import heuristic_distance as H
from circuit_verify import MAX_DEM_MECHANISMS, SIDE_FILES
from qldpc_verify import file_size_error
from validate_candidate import validate_candidate
from build_receipt import make_receipt, write_receipt

try:
    import gf2_fast as GF          # optional C++ accelerator (make fast); the
except ImportError:                # gate degrades to the python passes without it
    GF = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fixed thread count for the fast pass so its verdict is reproducible from the
# printed seed alone (the per-thread RNG streams depend on the split).
FAST_THREADS = 4


def _load_syndrome():
    """The syndrome-decoder cross-check (decode/distance.py); needs ldpc. Returns
    the module or None so the gate degrades to RIS-only without it."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "decode"))
        import distance as sd
        return sd
    except Exception:
        return None


def map_changed(paths):
    """Changed paths -> the code JSONs the gate must run on. A change under
    circuits/<slug>/ is a change to that entry's circuit-tier claim surface
    (the DEM the witnesses live in), so it maps back to codes/<slug>.json --
    a schedule swap cannot dodge the gate by leaving the JSON untouched."""
    files = []
    for p in paths:
        if p.startswith("circuits/") and p.count("/") >= 2:
            p = f"codes/{p.split('/')[1]}.json"
        if p.endswith(".json") and p not in files:
            files.append(p)
    return files


def changed_codes(base, code_root=ROOT):
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD", "--",
             "codes", "verify/fixtures", "circuits"],
            cwd=code_root, text=True)
    except Exception as e:
        print(f"could not compute diff vs {base}: {e}; failing closed")
        return None
    return map_changed(out.split())


def changed_codes_status(base: str, code_root: str = ROOT) -> dict | None:
    """{path: status} for codes changed vs base (A/M/D), rename-split like
    check_authorship.changed_codes so a refutation's rename stays visible."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD",
             "--", "codes"],
            cwd=code_root, text=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    changes = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        if status == "R" and len(parts) >= 3:
            if parts[1].endswith(".json"):
                changes[parts[1]] = "D"
            if parts[2].endswith(".json"):
                changes[parts[2]] = "A"
        elif parts[1].endswith(".json"):
            changes[parts[1]] = status
    return changes


def load_base_doc(base: str, path: str, code_root: str) -> dict | None:
    """Base-revision content of path, or None if unavailable."""
    try:
        out = subprocess.check_output(["git", "show", f"{base}:{path}"],
                                      cwd=code_root, text=True,
                                      stderr=subprocess.DEVNULL)
        return json.loads(out)
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError):
        return None


def base_doc_for(f: str, doc: dict, base: str, code_root: str) -> dict | None:
    """The base doc this file revises: itself when modified, or the deleted
    codes/<n>-<k>-*.json a refutation renamed away. None for new codes or on
    any ambiguity (which downstream fails closed to the full gate)."""
    changes = changed_codes_status(base, code_root)
    if changes is None:
        return None
    if changes.get(f) == "M":
        return load_base_doc(base, f, code_root)
    prefix = os.path.join(os.path.dirname(f),
                          f"{doc.get('n')}-{doc.get('k')}-")
    dels = [p for p, s in changes.items() if s == "D" and p.startswith(prefix)]
    if len(dels) == 1:
        return load_base_doc(base, dels[0], code_root)
    return None


def structural_ok(verdict: dict) -> bool:
    """The structural soundness of a board edit, from a validate_candidate
    verdict. validate_candidate is the NEW-candidate pipeline: its overall
    'passed' includes gates that are meaningless for an in-place edit of a
    file already on the board -- dedup flags the code as an exact duplicate
    of itself, and novelty judges board advancement. What the gate must not
    say ok about is a file the VERIFIER rejects, so only gates.verify.ok is
    authoritative here."""
    return bool(((verdict.get("gates") or {}).get("verify") or {}).get("ok"))


def layout_entered_tighter_class(base_doc: dict | None, new_doc: dict) -> bool:
    """True when the diff's layout moves the code into a tighter locality
    class than it had at base. For a layout-only diff this is the only way
    the code can become a NEW record of a 2d-local cell (its n, k, d, w are
    unchanged, so record status in cells it already occupied cannot change);
    such a claim has never faced the deep battery and must not skip it."""
    return _locality_rank(new_doc) < _locality_rank(base_doc or {"n": new_doc.get("n"), "checks": new_doc.get("checks")})


def _survival_raised(base_doc: dict | None, new_doc: dict | None) -> bool:
    """True if any side adds or raises witness_provenance.survived_samples."""
    bd = (base_doc or {}).get("distance") or {}
    nd = (new_doc or {}).get("distance") or {}
    for side in ("X", "Z"):
        bs = ((bd.get(side) or {}).get("witness_provenance") or {})
        ns = ((nd.get(side) or {}).get("witness_provenance") or {})
        nv = ns.get("survived_samples")
        if nv is None:
            continue
        bv = bs.get("survived_samples")
        if bv is None or nv > bv:
            return True
    return False


def classify_diff(base_doc: dict | None, new_doc: dict) -> tuple[str, str]:
    """Classify a changed code's diff for refutation pricing. Returns
    (cls, reason) with cls in {'new', 'stamp', 'layout-only', 'tightening',
    'full'}. Structural facts only -- witness validity is the verifier's job
    (verify_all runs before this gate in CI); anything unclassifiable is
    'full' (fail closed)."""
    try:
        if base_doc is None:
            return "new", "no base counterpart"
        if _survival_raised(base_doc, new_doc):
            return "stamp", ("witness_provenance.survived_samples added or "
                             "raised: the survival claim is what needs vetting")
        frozen = ("checks", "n", "k", "code_type")
        for key in frozen:
            if base_doc.get(key) != new_doc.get(key):
                return "full", f"field '{key}' changed"
        if base_doc.get("distance") == new_doc.get("distance"):
            if base_doc.get("locality") != new_doc.get("locality"):
                return "layout-only", "checks and distance unchanged from base"
            return "layout-only", ("checks and distance unchanged from base "
                                   "(metadata-only diff)")
        if base_doc.get("locality") != new_doc.get("locality"):
            return "full", "distance and locality both changed (mixed diff)"
        bd, nd = base_doc.get("distance") or {}, new_doc.get("distance") or {}
        tightened = 0
        for side in ("X", "Z"):
            bs, ns = bd.get(side), nd.get(side)
            if bs is None or ns is None:
                return "full", f"distance.{side} missing"
            if bs == ns:
                continue
            bv, nv = bs.get("value"), ns.get("value")
            if not (isinstance(bv, int) and isinstance(nv, int) and nv < bv):
                return "full", (f"distance.{side}.value did not strictly "
                                "decrease")
            if len(ns.get("witness") or []) != nv:
                return "full", (f"distance.{side} witness weight does not "
                                "equal the new value")
            if ns.get("confidence") != "upper_bound":
                return "full", (f"distance.{side}.confidence is not "
                                "upper_bound at the corrected value")
            tightened += 1
        if tightened == 0:
            return "full", "distance changed without a side strictly decreasing"
        if nd.get("d") != min(nd[s].get("value") for s in ("X", "Z")):
            return "full", "distance.d is not min(dX, dZ)"
        return "tightening", (f"{tightened} side(s) strictly decreased with "
                              "matching witnesses")
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        # every malformed-document shape fails closed; a genuine bug in this
        # function should raise and surface in CI, not silently price full
        return "full", f"unclassifiable ({type(e).__name__}: {e})"


def _locality_rank(doc):
    """Home locality class as a tightness rank: 0 = local-2d-single,
    1 = local-2d-bilayer, 2 = unrestricted. Mirrors the verifier's derivation
    (TRACKS.md): an honest layout -- full coverage, at most `layers` qubits per
    site, distinct sites unit-spaced -- earns a class when the measured check
    radius is within the class cap; anything else is unrestricted. Used only
    to pick the refutation BUDGET; the authoritative classification stays in
    qldpc_verify."""
    import math
    from collections import Counter
    loc = doc.get("locality")
    n = doc["n"]
    if not loc or len(loc.get("coordinates", [])) != n:
        return 2
    coords = loc["coordinates"]
    layers = loc.get("layers", 1)

    def diam(sup):
        pts = [coords[q] for q in sup]
        return max((math.dist(a, b) for a in pts for b in pts), default=0.0)
    radius = max((diam(s) for s in doc["checks"]["X"] + doc["checks"]["Z"]),
                 default=0.0)
    mult = Counter(tuple(c) for c in coords)
    sites = sorted(mult)
    min_sp = min((math.dist(a, b) for i, a in enumerate(sites)
                  for b in sites[i + 1:]), default=float("inf"))
    if min_sp < 1.0:
        return 2
    for rank, (lay, cap) in enumerate(((1, 4.0), (2, 7.0))):
        if layers <= lay and max(mult.values()) <= lay and radius <= cap:
            return rank
    return 2


def _weight_rank(w):
    """Check-weight class as a tightness rank: weight-4 < weight-6 < weight-8
    < any weight."""
    return 0 if w <= 4 else 1 if w <= 6 else 2 if w <= 8 else 3


def board_record_slugs(code_root=ROOT):
    """Slugs that are records of their own primary-track CELL: undominated on
    (n, k, d, w) among board codes whose locality and weight classes are
    stricter or equal (the codes that share the cell under TRACKS.md nesting).
    A code that claims a cell record gets deeper refutation than a dominated
    one, so over-claims pay extra scrutiny exactly where gaming would matter.
    Cell-aware on purpose: a 2D-local record is a record even when a nonlocal
    code beats it globally, and it deserves the deep battery too."""
    rows = []
    for p in sorted(glob.glob(os.path.join(code_root, "codes", "*.json"))):
        try:
            d = json.load(open(p))
            ck = d.get("checks", {})
            w = max((len(s) for s in ck.get("X", []) + ck.get("Z", [])), default=0)
            rows.append((os.path.splitext(os.path.basename(p))[0],
                         d["n"], d["k"], d["distance"]["d"], w,
                         _weight_rank(w), _locality_rank(d)))
        except Exception:
            continue
    rec = set()
    for i, a in enumerate(rows):
        dominated = any(
            j != i
            and b[5] <= a[5] and b[6] <= a[6]          # shares a's home cell
            and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3] and b[4] <= a[4]
            and (b[1] < a[1] or b[2] > a[2] or b[3] > a[3] or b[4] < a[4])
            for j, b in enumerate(rows))
        if not dominated:
            rec.add(a[0])
    return rec


def _budget(n, deep, fast=False):
    """Adaptive refutation depth for a code with n qubits: (trials, seconds, seeds).

    Trials scale with n (the RIS target formula, without the flat 8000 cap the
    quick in-verifier pass uses), so small codes get near-exhaustive coverage and
    large codes a proportionate search instead of whatever fits a flat time box.
    The wall-clock cap scales alongside (per-trial cost measured at ~0.5-1.3+
    ms/trial for n = 72..336, with headroom); whichever binds first ends the
    search. Small codes finish their target early (measured: the deep pass on
    n=72 completes 33.6k trials in ~20 s/seed and stops); large codes fill the
    cap, which is therefore the CI cost ceiling. Either way this strictly
    deepens the old behavior, where the trial target was flat-capped at 8000 --
    reached in ~10 s -- so the deep pass's extra 120 s bought nothing.

    Deep (frontier-advancing) claims get independent seeds at ~60k-scale trial
    targets: the depth that exposed real over-claims which 8k-trial passes let
    through. How many python seeds depends on whether the C++ accelerator is
    available (``fast``): with it, ONE python seed remains as the audited floor
    and in-production canary (it would expose a false-negative bug in the
    extension by finding what the fast pass missed), and the reallocated
    wall-clock goes into a ~150x-deeper fast pass; without it, the pre-
    accelerator battery of 3 seeds runs unchanged, so a missing or broken
    extension can never leave the gate shallower than it was. Worst case per
    record claim is ~4 min of python RIS + the fast pass (or 3 x 240 s python-
    only); dominated rows stay cheap."""
    per_trial = 0.0005 + 2.5e-6 * n              # seconds/trial, measured (both sides)
    if deep:
        trials = 25000 + 120 * n
        seconds = min(240.0, max(120.0, trials * per_trial * 3))
        return trials, seconds, (1 if fast else 3)
    trials = 2500 + 40 * n
    seconds = min(90.0, max(10.0, trials * per_trial * 4))
    return trials, seconds, 1


# Circuit-tier refutation budget (RFC 0001 step 6). Per-trial RIS cost on
# ker(H_dem) fits ~cost * mechanisms^3, dominated by the packed RREF. With
# the in-C++ DEM trial loop (gf2_fast.dem_rand_witness: kernel packed once,
# pivot-order permutation instead of physical column moves, 4 threads;
# measured 2026-08-21: 0.76 ms at m=1687, 10.8 ms at m=5353, 330 ms at
# m=12411) the asymptotic constant is ~2e-13; the pure numpy fallback loop
# measured ~1.9e-11 (85 ms at m=1651), hence the 100x factor. The budget
# targets a wall-clock per basis and converts it to trials through the fit;
# the hard time cap inside ris_dem bounds CI even where the fit is off. At
# MAX_DEM_MECHANISMS (~3.1 s/trial) the 120 s target buys ~38 trials, so the
# cap is genuinely searchable at full depth.
CIRCUIT_TRIAL_COST = 2.0e-13          # seconds per trial per mechanisms^3
CIRCUIT_PY_FACTOR = 100               # numpy-loop fallback slowdown, measured
CIRCUIT_SECONDS = 120.0               # wall-clock target per basis
CIRCUIT_MAX_TRIALS = 20_000
CIRCUIT_MIN_TRIALS = 12


def _circuit_budget(m, fast):
    per = CIRCUIT_TRIAL_COST * m ** 3 * (1 if fast else CIRCUIT_PY_FACTOR)
    per = max(per, 0.002)
    trials = int(max(CIRCUIT_MIN_TRIALS if fast else 3,
                     min(CIRCUIT_MAX_TRIALS, CIRCUIT_SECONDS / per)))
    return trials, CIRCUIT_SECONDS * 1.5


def circuit_gate_needed(base_doc, doc, circuits_diffed):
    """Diff-priced circuit gate decision: search only when the circuit claim
    surface changed -- the JSON's circuit block or the artifacts under
    circuits/<slug>/ -- or when there is no base to have gated it. An
    untouched claim already survived its own gate and the code-tier skip
    logic must never be the thing that skips a CHANGED circuit claim."""
    if "circuit" not in doc:
        return False
    if base_doc is None:
        return True
    return base_doc.get("circuit") != doc.get("circuit") or circuits_diffed


def _circuits_diffed(base, code_root, slug):
    """Did anything under circuits/<slug>/ change vs base? Fails closed (True)
    when the diff cannot be computed."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base}...HEAD", "--",
             f"circuits/{slug}"], cwd=code_root, text=True)
        return bool(out.strip())
    except Exception:
        return True


def _circuit_refute(doc, circuits_dir, seed, trials_override=None):
    """RFC 0001 step 6: independent bounded RIS on the DEM of each committed
    memory circuit, hunting an undetected logical fault set lighter than the
    claimed d_circ. The DEM is RE-DERIVED from the .stim with the pinned stim
    -- the search substrate is never the committed .dem taken on faith -- and
    a find only counts after the pinned witness check confirms it, exactly
    the layering the code-distance gate uses. Returns (hits, notes): hits
    maps basis -> (found_weight, witness, claimed); notes are per-basis "ok"
    summaries. Raises on unreadable artifacts (caller fails closed)."""
    import stim
    hits, notes = {}, []
    for side in ("X", "Z"):
        claim = int(doc["circuit"]["d_circ"][side]["value"])
        base = os.path.join(circuits_dir, SIDE_FILES[side])
        circuit = stim.Circuit(open(base + ".stim").read())
        dem = CT.derive_dem(circuit)
        m = dem.num_errors
        if m > MAX_DEM_MECHANISMS:
            raise ValueError(f"{side}: {m} mechanisms exceeds the tier cap "
                             f"{MAX_DEM_MECHANISMS}")
        Hd, L = CT.dem_matrices(dem)
        # `fast` keys on the DEM entry point specifically: a stale extension
        # without it drops ris_dem to the numpy loop and must be budgeted so.
        trials, cap = _circuit_budget(
            m, CT._GF is not None and hasattr(CT._GF, "dem_rand_witness"))
        if trials_override:
            trials = trials_override
        w, wit = CT.ris_dem(Hd, L, trials, seed=seed, max_seconds=cap)
        if w is not None and w < claim and \
                not CT.witness_errors(dem, wit, w):
            hits[side] = (w, wit, claim)
        else:
            notes.append(f"{side} ok (m={m}, {trials} trials, "
                         f"lightest {w} vs claimed {claim})")
    return hits, notes


def _fast_refute(doc, seed, trials):
    """Deep RIS via the optional C++ accelerator, kept SOUND the same way the
    python passes are: the accelerator only proposes (weight, side, support);
    the find counts as a refutation only after the pinned python stack confirms
    the support is a genuine nontrivial logical of that weight, lighter than
    the claim. An invalid or non-improving find is reported as a miss, never
    trusted. Returns the refute_check tuple shape: (refuted, d, witness, trials)."""
    n = doc["n"]
    HX = H._matrix(doc["checks"]["X"], n)
    HZ = H._matrix(doc["checks"]["Z"], n)
    w, side, support = GF.distance_rand_witness(
        HX, HZ, trials=trials, seed=seed, pair_depth=8, threads=FAST_THREADS)
    claimed = int(doc["distance"]["d"])
    if not side or w >= claimed:
        return False, (w if side else None), None, trials
    v = np.zeros(n, dtype=np.int8)
    v[list(support)] = 1
    Hcheck = HZ if side == "X" else HX
    L = gf2.logical_basis(HX, HZ) if side == "X" else gf2.logical_basis(HZ, HX)
    valid = (int(v.sum()) == w
             and not ((Hcheck @ v) % 2).any()
             and bool(((L @ v) % 2).any()))
    if not valid:
        return False, None, None, trials
    return True, w, sorted(int(q) for q in support), trials


def main(argv):
    rest = [a for a in argv if not a.endswith(".json")]
    seed = None
    code_root = ROOT
    receipt_dir = None
    pr_number = None
    pr_author = None
    base_sha = None
    head_sha = None
    if "--receipt-dir" in rest:
        i = rest.index("--receipt-dir")
        receipt_dir = os.path.abspath(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if "--pr-number" in rest:
        i = rest.index("--pr-number")
        pr_number = int(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if "--pr-author" in rest:
        i = rest.index("--pr-author")
        pr_author = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if "--base-sha" in rest:
        i = rest.index("--base-sha")
        base_sha = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if "--head-sha" in rest:
        i = rest.index("--head-sha")
        head_sha = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if "--code-root" in rest:
        i = rest.index("--code-root")
        code_root = os.path.abspath(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if "--seed" in rest:
        i = rest.index("--seed")
        seed = int(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    files = [a for a in argv if a.endswith(".json")]
    base = next((a for a in rest), "origin/main")
    if base_sha is None:
        try:
            base_sha = subprocess.check_output(
                ["git", "rev-parse", base], cwd=code_root, text=True).strip()
        except Exception:
            pass
    if head_sha is None:
        try:
            head_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=code_root, text=True).strip()
        except Exception:
            pass
    if not files:
        files = changed_codes(base, code_root)
    if files is None:
        return 1
    if not files:
        print("no changed code submissions to gate")
        return 0

    # Random seed by design: a re-run draws a new search, so an over-claim cannot
    # reliably evade one fixed seed. The trade-off is that re-running can change the
    # verdict (a merge can fail later) -- the seed is printed so any run reproduces.
    if seed is None:
        seed = secrets.randbelow(2**31)
    print(f"refutation seed = {seed}  "
          f"(reproduce: python verify/gate_changed.py --seed {seed} <files>)\n")

    SD = _load_syndrome()
    if SD is None:
        print("note: syndrome-decoder cross-check unavailable (ldpc missing); "
              "running RIS only\n")

    refuted = 0
    failed = 0
    records = board_record_slugs(code_root)
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(code_root, f)
        if not os.path.exists(p):                 # deleted/renamed away
            continue
        ferr = file_size_error(p)
        if ferr:
            failed += 1
            print(f"FAIL     {f}: file_size_within_limit: {ferr}")
            continue
        doc = json.load(open(p))
        if "distance" not in doc or "d" not in doc.get("distance", {}):
            continue
        # A code that is a record of its own primary-track cell is checked
        # harder: several independent deep RIS seeds, not one short pass, so an
        # over-claim cannot lean on a single search missing the lighter logical.
        # Trials and wall-clock both scale with code size (see _budget).
        # Dominated codes pay only the standard, size-scaled pass.
        slug = os.path.splitext(os.path.basename(f))[0]
        # Price the diff, not just the code: what changed determines what could
        # newly be over-claimed (see module docstring).
        base_doc = base_doc_for(f, doc, base, code_root)
        if base_doc is None:
            status = changed_codes_status(base, code_root)
            if status is not None and f not in status:
                # The JSON itself is untouched -- this file was mapped in by
                # a circuits/<slug>/ diff. Its base counterpart is simply
                # itself at base, so the code tier classifies as unchanged
                # (and skips) instead of pricing an unchanged claim as a new
                # one. A None status (git failure) stays None: fail closed.
                base_doc = load_base_doc(base, f, code_root)
        cls, why = classify_diff(base_doc, doc)
        run_circuit = circuit_gate_needed(
            base_doc, doc, _circuits_diffed(base, code_root, slug))

        def run_circuit_gate():
            """The circuit-tier search (RFC 0001 step 6); (hits, notes, err)."""
            if not run_circuit:
                return {}, (["circuit claim unchanged from base; already "
                             "gated"] if "circuit" in doc else []), None
            cdir = os.path.join(os.path.dirname(p), "..", "circuits", slug)
            try:
                h, nts = _circuit_refute(doc, cdir, seed + 11)
                return h, nts, None
            except Exception as e:
                return {}, [], f"{type(e).__name__}: {e}"

        if cls == "layout-only":
            # The structural verdict (schema, witnesses, layout honesty) is
            # authoritative here even though verify_all also runs it: the
            # gate's stdout and receipt must not say ok about a file the
            # verifier rejects.
            verdict = validate_candidate(doc, seed=seed, refute=False)
            if not structural_ok(verdict):
                failed += 1
                print(f"FAIL     {f}: structural checks failed "
                      f"(layout-only diff; see verify_all for details)")
            elif slug in records and layout_entered_tighter_class(base_doc, doc):
                # The layout moves the code into a tighter locality class
                # where it claims a cell record it has never defended: the
                # one layout-only shape that must not skip the deep battery.
                cls, why = "layout-record", (
                    "layout enters a tighter locality class and claims a "
                    "cell record; deep battery required before it stands")
            else:
                print(f"ok       {f} (layout-only diff: {why}; refutation "
                      f"deferred to the weekly board sweep)")
            if cls == "layout-only":
                # The CODE claim is unchanged and skips, but a changed
                # circuit claim in the same diff must still be searched: a
                # circuit-block-only edit classifies exactly here.
                ok_struct = structural_ok(verdict)
                circ_hits, circ_notes, circ_failed = ({}, [], None)
                if ok_struct:
                    circ_hits, circ_notes, circ_failed = run_circuit_gate()
                if circ_failed:
                    failed += 1
                    print(f"FAIL     {f} [circuit]: gate could not search the "
                          f"DEM ({circ_failed}); failing closed -- manual "
                          f"review required")
                elif circ_hits:
                    refuted += 1
                    for s, (w, wit, c) in circ_hits.items():
                        print(f"REFUTED  {f} [circuit-{s}]: weight-{w} "
                              f"undetected logical fault set < claimed "
                              f"d_circ {c}\n         witness (dem error "
                              f"indices) = {wit}")
                elif ok_struct and run_circuit:
                    print(f"ok       {f} [circuit]: {'; '.join(circ_notes)}")
                if receipt_dir:
                    # The receipt's headline verdict must reflect structural
                    # soundness of the edit, not the new-candidate gates
                    # (dedup self-matches by construction on an in-place edit).
                    verdict["passed"] = bool(ok_struct and not circ_hits
                                             and not circ_failed)
                    verdict["gates"]["refute"] = {
                        "refuted": bool(circ_hits), "seed": seed,
                        "detail": f"skipped: {why}; distance claim identical "
                                  f"to base and covered by the weekly refute "
                                  f"sweep; dedup self-match is expected for "
                                  f"an in-place edit",
                    }
                    gate = {"refuted": bool(circ_hits), "seed": seed,
                            "seeds": [], "trials": 0, "budget_seconds": 0.0,
                            "deep": False, "fast_trials": 0, "methods": [],
                            "diff_class": cls, "diff_reason": why}
                    if "circuit" in doc:
                        gate["circuit"] = {
                            "searched": run_circuit,
                            "refuted": bool(circ_hits),
                            "failed": circ_failed,
                            "hits": {s: {"found": w, "claimed": c}
                                     for s, (w, _, c) in circ_hits.items()},
                            "notes": circ_notes,
                        }
                    receipt = make_receipt(
                        doc, p, verdict, gate=gate,
                        repo_root=code_root, pr_number=pr_number,
                        pr_author=pr_author, base_sha=base_sha,
                        head_sha=head_sha)
                    write_receipt(receipt, receipt_dir, slug)
                continue
        if cls in ("stamp", "layout-record"):
            deep = True       # the new claim itself is what is being vetted
        elif cls == "tightening":
            deep = False      # strictly-less-wrong claim; weekly sweep has depth
        else:
            deep = slug in records
        trials, budget, nseeds = _budget(int(doc["n"]), deep, fast=GF is not None)
        seeds = [seed, seed + 2, seed + 3][:nseeds]
        # two independent mechanisms; a hit from EITHER (any seed) refutes.
        results = {}
        for si, s in enumerate(seeds):
            results[f"RIS#{si}"] = H.refute_check(doc, seed=s, max_seconds=budget,
                                                  trials=trials)
        if SD is not None:
            results["syndrome-decoder"] = SD.refute_check(doc, seed=seed + 1)
        # Frontier claims additionally face the accelerated deep search when the
        # extension is built (CI builds it; see Makefile `fast`): ~150x the
        # python trial target in the wall-clock freed by dropping 2 of the 3
        # python seeds (see _budget: without the extension the 3-seed battery
        # runs unchanged, so an absent/broken build can never weaken the gate).
        # A fast hit counts only with a python-validated witness (_fast_refute);
        # the remaining python seed is the audited floor and would surface a
        # false-negative extension bug by finding what the fast pass missed.
        ftrials = 0
        if GF is not None and deep:
            ftrials = min(8_000_000, 150 * trials)
            results["RIS-fast"] = _fast_refute(doc, seed + 7, ftrials)
        hits = {m: (dh, wit) for m, (ref, dh, wit, _) in results.items() if ref}
        # Circuit tier (RFC 0001 step 6): entries shipping syndrome circuits
        # additionally face a bounded RIS search on each memory DEM when the
        # circuit claim surface changed (circuit_gate_needed). A validated
        # lighter fault set refutes the d_circ claim the same way a lighter
        # logical refutes d. FAILS CLOSED: unreadable or over-cap artifacts
        # are a gate failure, never a silent pass.
        circ_hits, circ_notes, circ_failed = run_circuit_gate()
        fast_tag = (f" + fast x {ftrials}" if ftrials else "")
        tag = (f"deep, {len(seeds)} RIS seeds x {trials} trials (<={budget:.0f}s each)"
               f"{fast_tag}" if deep else f"standard, {trials} trials (<={budget:.0f}s)")
        tag += f"; diff: {cls}"
        gate = {
            "refuted": bool(hits or circ_hits),
            "seed": seed,
            "seeds": seeds,
            "trials": trials,
            "budget_seconds": budget,
            "deep": deep,
            "fast_trials": ftrials,
            "methods": list(results),
            "diff_class": cls,
            "diff_reason": why,
        }
        if "circuit" in doc:
            gate["circuit"] = {
                "searched": run_circuit,
                "refuted": bool(circ_hits),
                "failed": circ_failed,
                "hits": {s: {"found": w, "claimed": c}
                         for s, (w, _, c) in circ_hits.items()},
                "notes": circ_notes,
            }
        if receipt_dir:
            # The distance search above is authoritative for this run. Reuse the
            # trusted structural/dedup/frontier checks without running refutation a
            # second time just to produce an artifact.
            verdict = validate_candidate(doc, seed=seed, refute=False)
            verdict["gates"]["refute"] = {
                "refuted": bool(hits),
                "seed": seed,
                "detail": "distance gate recorded by gate_changed.py",
            }
            verdict["passed"] = bool(
                verdict.get("passed") and not hits
                and not circ_hits and not circ_failed)
            slug = os.path.splitext(os.path.basename(f))[0]
            receipt = make_receipt(
                doc, p, verdict, gate=gate, repo_root=code_root,
                pr_number=pr_number, pr_author=pr_author,
                base_sha=base_sha, head_sha=head_sha)
            write_receipt(receipt, receipt_dir, slug)
        if hits:
            refuted += 1
            for m, (dh, wit) in hits.items():
                print(f"REFUTED  {f} [{m}]: weight-{dh} logical < claimed distance "
                      f"{doc['distance']['d']}\n         witness = {wit}")
        else:
            print(f"ok       {f} ({tag}): no logical lighter than "
                  f"{doc['distance']['d']}")
        if circ_failed:
            failed += 1
            print(f"FAIL     {f} [circuit]: gate could not search the DEM "
                  f"({circ_failed}); failing closed -- manual review required")
        elif circ_hits:
            if not hits:
                refuted += 1
            for s, (w, wit, c) in circ_hits.items():
                print(f"REFUTED  {f} [circuit-{s}]: weight-{w} undetected "
                      f"logical fault set < claimed d_circ {c}\n"
                      f"         witness (dem error indices) = {wit}")
        elif circ_notes:
            print(f"ok       {f} [circuit]: {'; '.join(circ_notes)}")
    if refuted:
        print(f"\n{refuted} submission(s) refuted: claimed distance is not supported "
              f"by an independent search. See witnesses above.")
    if failed:
        print(f"\n{failed} submission(s) failed preflight checks.")
    return 1 if (refuted or failed) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

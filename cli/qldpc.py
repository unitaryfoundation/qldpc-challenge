"""qldpc submit: one command from parity checks to a verified submission.

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
  uv run python cli/qldpc.py submit mycode.npz --authors @me "Jane Roe" \\
      --construction "bivariate bicycle (x^3+y+y^2, ...)" --model "Opus 4.8"
  ./qldpc submit mycode.npz --authors @me        # via the launcher shim
  ./qldpc submit mycode.npz --authors @me --no-circuit   # code tier only

Input:
  .npz  with H_X and H_Z under keys hx/HX/H_X and hz/HZ/H_Z (dense 0/1 arrays
        or scipy sparse). Optional 'coords' (n x 2) for the 2d-local tracks.
  .json an existing draft carrying a checks block (re-verify / re-score it).
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "verify"))
sys.path.insert(0, os.path.join(_ROOT, "site"))
sys.path.insert(0, os.path.join(_ROOT, "research"))

import gf2  # noqa: E402
import heuristic_distance as hd  # noqa: E402

# Reuse the site's computed-cell + Pareto-frontier helpers so the PR body
# states exactly what the board will show (no drift between the two).
from build import LOCALITY_LABEL, WEIGHT_LABEL, cells, pareto  # noqa: E402
from check_authorship import HANDLE  # noqa: E402
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
    (a draft with a checks block).
    """
    if path.endswith(".json"):
        try:
            with open(path) as f:
                doc = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}: not valid JSON ({e})")
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
                with open(raw) as f:
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


def body_has_scaffolding(body):
    """Report whether the body still carries scaffolding the checker rejects.

    That means: draft footer, HTML comment, unticked box, TODO/FIXME. Used to
    gate --open-pr so a PR never ships a body the CI prose check would fail.
    """
    import re
    return bool(
        re.search(r"edit before requesting review", body, re.I)
        or "<!--" in body
        or re.search(r"^\s*[-*]\s*\[ \]", body, re.M)
        or re.search(r"\b(TODO|FIXME|TBD)\b", body))


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
    conf = {side: doc["distance"][side]["confidence"]
            for side in ("X", "Z") if side in doc["distance"]}
    conf_line = ", ".join(f"{s}: {c}" for s, c in conf.items())
    rel_out = _repo_path(out)

    def box(checked, text):
        return f"- [{'x' if checked else ' '}] {text}"

    lines = [
        "## Code submission",
        "",
        f"- Parameters: [[n, k, d]] = [[{n},{k},{d}]]",
        f"- Tracks: {track} (computed by the verifier from H and the layout)",
        f"- Distance confidence: {conf_line}",
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
    # equivalence box stays unticked by design — judging equivalence to an
    # existing entry needs human eyes, so an unedited draft is deliberately
    # not ready for review (the prose gate enforces exactly that).
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
        box(False, "If this may be equivalent to an existing entry, noted in "
                   "`provenance.notes`"),
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
    with os.fdopen(fd, "w") as f:
        f.write(body + "\n")
    return path


# ----------------------------------------------------------------------------
# frontier comparison (reuses the site's own cell + Pareto logic)
# ----------------------------------------------------------------------------
def _load_board_entries():
    """The board's current entries as the site sees them (verified, earned
    distance). Returns [] if the site builder cannot be imported or the board
    is empty, so the frontier section degrades gracefully to a TODO.
    """
    try:
        from build import load_entries
        return load_entries()
    except Exception as e:
        print(f"  note: could not load the current board for frontier "
              f"comparison ({e}); leaving the frontier section as a TODO")
        return []


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
        idxs = [i for i, e in enumerate(entries) if cell in cells(e)]
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
    for side in ("X", "Z"):
        s = dist.get(side, {})
        witness = "witness found" if s.get("witness") else "no witness"
        per_side.append(f"{side}: <= {s.get('value')} ({s.get('confidence')}, {witness})")
    track_cells = ", ".join(
        f"{LOCALITY_LABEL.get(L, L)} / {WEIGHT_LABEL.get(W, W)}"
        for L, W in cells(entry)
    )
    lines = [
        f"  code         [[{doc['n']},{doc['k']},{dist['d']}]]",
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
    """The oldest schema version that describes the document: 0.3 with a
    search budget, 0.2 with a circuit block, else 0.1."""
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
            with open(os.path.join(tmp, name), "w") as f:
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


def cmd_submit(args):
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
    circuits_dir = os.path.join(os.path.dirname(os.path.abspath(args.out)),
                                "circuits", slug)
    if not args.dry_run and not args.force:
        for p in ([out] if args.no_circuit else [out, circuits_dir]):
            if os.path.exists(p):
                print(f"\n{p} already exists. Use --force to overwrite, or "
                      f"rename.")
                return 1

    circuit_files = None if args.no_circuit else attach_circuit_tier(doc, args)

    if args.dry_run:
        print(f"\n--dry-run: would write {out}" +
              (f" and {circuits_dir}/" if circuit_files else ""))
        if args.json:
            print(json.dumps(doc, indent=1))
        else:
            print(dry_run_summary(doc, report, out))
        return 0
    os.makedirs(args.out, exist_ok=True)
    with open(out, "w") as f:
        json.dump(doc, f, indent=1)
        f.write("\n")
    print(f"  wrote {out}")
    if circuit_files:
        os.makedirs(circuits_dir, exist_ok=True)
        for name, text in circuit_files.items():
            with open(os.path.join(circuits_dir, name), "w") as f:
                f.write(text)
        print(f"  wrote {circuits_dir}/memory_{{x,z}}.{{stim,dem}}")
    else:
        circuits_dir = None

    # the public research note (notes/<slug>.md): how the code was found —
    # search narrative, sweep sizes, confirmation ladder, dead ends. Requested
    # for every submission; rendered on the code's site page and in the
    # research log. See notes/README.md and notes/TEMPLATE.md.
    note_out = None
    if args.note_file:
        with open(args.note_file) as f:
            note_md = f.read()
        if len(note_md.encode()) > 10 * 1024:
            print(f"\n{args.note_file} exceeds the 10 KiB note cap; trim it.")
            return 1
        note_out = os.path.join(_ROOT, "notes", f"{slug}.md")
        os.makedirs(os.path.dirname(note_out), exist_ok=True)
        with open(note_out, "w") as f:
            f.write(note_md)
        print(f"  wrote {note_out}")
    else:
        print("\n  note: no --note-file given. Submissions should ship a "
              "research note\n  (notes/{}.md) — the search story, sweep "
              "sizes, ladder, dead ends.\n  See notes/TEMPLATE.md; the site "
              "renders it beside your code.".format(slug))

    title = pr_title(n, k, d, _descriptor(args))
    body_file = write_pr_body(slug, pr_body(doc, report, args, out, note_out))

    if args.open_pr:
        return open_pr(slug, out, note_out, title, body_file,
                       root=_ROOT, circuits_dir=circuits_dir)
    print("\nnext: open a PR with " +
          ("these files" if note_out or circuits_dir else "this file"))
    print(f"  git checkout -b submit-{slug}")
    print(f"  git add {out}" + (f" {note_out}" if note_out else "") +
          (f" {circuits_dir}" if circuits_dir else ""))
    print(f"  git commit -m {title!r}")
    print(f"  git push -u origin submit-{slug}")
    print(f"  gh pr create --title {title!r} --body-file {body_file}")
    print(f"\nthe PR body was drafted for you from the verified submission:"
          f"\n  {body_file}"
          f"\nit follows .github/pull_request_template.md — read it and fill"
          f"\nin the 'what frontier does this advance?' section before review.")
    print("\nor re-run with --open-pr to do this automatically.")
    return 0


def open_pr(slug, out, note_out=None, title=None, body_file=None, root=None,
            circuits_dir=None):
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
            pre = subprocess.run(
                [sys.executable, os.path.relpath(checker, root),
                 "--root", root, "--body-file", body_file, "--files", *files],
                cwd=root, check=False)
            if pre.returncode != 0:
                print(f"\nprose pre-flight FAILED ({pre.returncode}); no PR "
                      f"was opened. Fix the issues above (the drafted body is "
                      f"at {body_file}) and re-run with --open-pr.")
                return 1
    add = ["git", "add", out] + ([note_out] if note_out else []) + \
        ([circuits_dir] if circuits_dir else [])
    # --title/--body-file rather than --fill: the body is the filled-in
    # pull request template, which the commit message does not carry (#404).
    create = ["gh", "pr", "create", "--title", title]
    create += ["--body-file", body_file] if body_file else ["--fill"]
    cmds = [
        ["git", "checkout", "-b", branch],
        add,
        ["git", "commit", "-m", title],
        ["git", "push", "-u", "origin", branch],
        create,
    ]
    for c in cmds:
        print(f"  $ {' '.join(c)}", flush=True)
        r = subprocess.run(c, cwd=_ROOT)
        if r.returncode != 0:
            print(f"  command failed ({r.returncode}); finish the remaining "
                  f"steps by hand.")
            if body_file:
                print(f"  the drafted PR body is at {body_file}")
            return r.returncode
    print("\nthe PR body was drafted from the verified submission; fill in the"
          "\n'what frontier does this advance?' section before review "
          "(gh pr edit).")
    return 0


def cmd_targets(args):
    """Print per-cell occupancy and frontier, so a newcomer can see what to aim at.

    Reuses the site's own cells() and pareto(), the pair that decides records on
    the published board, so these are the board's numbers rather than a second
    opinion about them.
    """
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
    return 0


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


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
    fnotes = []
    for d, f in added("fieldnotes/"):
        if not f.endswith(".md") or f.endswith("README.md"):
            continue
        title, topics = _fieldnote_meta(os.path.join(_ROOT, f))
        fnotes.append({"date": d, "path": f, "title": title, "topics": topics,
                       "hay": f"{f} {title} {' '.join(topics)}".lower()})

    n_codes, n_fnotes = len(codes), len(fnotes)
    if want:
        codes = [c for c in codes if any(w in c["hay"] for w in want)]
        fnotes = [f for f in fnotes if any(w in f["hay"] for w in want)]
    n_note = sum(1 for c in codes if c["note"])

    lim = None if args.full else max(1, args.limit)
    filt = f" matching {' + '.join(want)}" if want else ""
    print(f"board activity, last {args.days} days{filt}: "
          f"{_plural(len(codes), 'code')} ({n_note} with a research note), "
          f"{_plural(len(fnotes), 'fieldnote')}")
    if want:
        print(f"  (of {_plural(n_codes, 'code')} and "
              f"{_plural(n_fnotes, 'fieldnote')} in the window)")

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

    print("full log: docs research-log page, or ls notes/ fieldnotes/")
    return 0



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
                   help="with --dry-run, print the full submission JSON "
                        "instead of the summary")
    s.add_argument("--open-pr", action="store_true",
                   help="create the branch, commit, push, and open the PR")
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
    r.set_defaults(func=cmd_recent)

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
    g.set_defaults(func=cmd_targets)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

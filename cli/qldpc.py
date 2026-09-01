"""qldpc submit: one command from parity checks to a verified submission.

The friction in contributing used to be "read CONTRIBUTING.md, learn the JSON
schema, hand-write a distance witness, hope CI agrees." This collapses that into
a single command, the way ecdsa.fail does: you bring H_X and H_Z, the tool

  1. computes n, k (= n - rank H_X - rank H_Z) and the max check weight,
  2. searches for the lightest logical on each side (RIS) and records it as a
     self-certifying distance witness,
  3. assembles a schema-valid submission,
  4. runs the full trustless verifier locally (the same gate CI runs),
  5. fills the PR body's "what frontier does this advance?" section by
     comparing against the current board (reusing the site's Pareto logic),
     and
  6. writes codes/<n>-<k>-<d>.json and prints the steps to open the PR
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
import re
import subprocess
import sys
import tempfile

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "verify"))
sys.path.insert(0, os.path.join(_ROOT, "site"))

import gf2                       # noqa: E402
import heuristic_distance as hd  # noqa: E402
from check_authorship import HANDLE  # noqa: E402
from qldpc_verify import verify  # noqa: E402
# Reuse the site's computed-cell + Pareto-frontier helpers so the PR body
# states exactly what the board will show (no drift between the two).
from build import cells, pareto, LOCALITY_LABEL, WEIGHT_LABEL  # noqa: E402


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
        doc["locality"] = {
            "coordinates": [[float(x), float(y)] for x, y in args._coords],
            "layers": int(args.layers),
        }
    return doc


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
    Keeps the body readable when --out points somewhere else entirely."""
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
        "",
    ]
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
    is empty, so the frontier section degrades gracefully to a TODO."""
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
    read these keys, so this is enough to compare against the board."""
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
    unavailable)."""
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


def cmd_submit(args):
    if args.out.endswith(".json"):
        raise SystemExit(
            f"--out expects a directory, not a filename: {args.out!r}\n"
            "The output filename is always <n>-<k>-<d>.json, computed after "
            "verification, so it is not yours to choose. Pass the directory "
            f"it should go in instead, e.g. --out {os.path.dirname(args.out) or '.'}"
        )
    args.authors = validate_authors(args.authors, args.anonymous)
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
                       root=_ROOT)
    print("\nnext: open a PR with this file")
    print(f"  git checkout -b submit-{slug}")
    print(f"  git add {out}" + (f" {note_out}" if note_out else ""))
    print(f"  git commit -m {title!r}")
    print(f"  git push -u origin submit-{slug}")
    print(f"  gh pr create --title {title!r} --body-file {body_file}")
    print(f"\nthe PR body was drafted for you from the verified submission:"
          f"\n  {body_file}"
          f"\nit follows .github/pull_request_template.md — read it and fill"
          f"\nin the 'what frontier does this advance?' section before review.")
    print("\nor re-run with --open-pr to do this automatically.")
    return 0


def open_pr(slug, out, note_out=None, title=None, body_file=None, root=None):
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
    add = ["git", "add", out] + ([note_out] if note_out else [])
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


def cmd_recent(args):
    """What moved on the board recently: codes merged, research notes, and
    fieldnotes, from git history. The 'stay current' step — read this (and
    the linked notes) before spending compute, so a new search starts from
    the community's frontier of knowledge, not just the frontier of scores."""
    since = f"--since={args.days} days ago"

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

    codes = added("codes/")
    notes = {os.path.basename(f)[:-3] for _, f in added("notes/")
             if f.endswith(".md")}
    fnotes = [f for _, f in added("fieldnotes/")
              if f.endswith(".md") and not f.endswith("README.md")]

    print(f"board activity, last {args.days} days:")
    if not codes:
        print("  no new codes")
    for date, f in codes:
        slug = os.path.splitext(os.path.basename(f))[0]
        has_note = (slug in notes
                    or os.path.exists(os.path.join(_ROOT, "notes",
                                                   slug + ".md")))
        tag = "note: notes/%s.md" % slug if has_note else "no research note"
        print(f"  {date}  [[{slug.replace('-', ',')}]]  ({tag})")
    if fnotes:
        print("fieldnotes (negative results / calibration):")
        for f in fnotes:
            print(f"  {f}")
    print("full log: docs research-log page, or ls notes/ fieldnotes/")
    return 0


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
    s.add_argument("--notes", default="",
                   help="short free-text notes recorded on the submission "
                        "(not the research note; see --note-file)")
    s.add_argument("--note-file", default="",
                   help="markdown research note staged as notes/<slug>.md and "
                        "rendered publicly beside the code: the search story "
                        "— hypothesis, sweep sizes, confirmation ladder, dead "
                        "ends (see notes/TEMPLATE.md; 10 KiB cap)")
    s.add_argument("--date", default="",
                   help="submission date (YYYY-MM-DD); defaults to today")
    s.add_argument("--name", default="",
                   help="display name for the construction; defaults to the "
                        "auto-generated [[n,k,d]] name")
    s.add_argument("--family", choices=[
                       "bivariate-bicycle", "generalized-bicycle", "2bga-coset",
                       "hypergraph-product", "lifted-product", "balanced-product",
                       "quantum-tanner", "tile", "topological", "other"],
                   help="construction family tag (a filter, not a ranking; "
                        "track membership is computed from H and the layout)")
    s.add_argument("--coords", default="",
                   help="coordinates file (.npz key coords, or whitespace .txt); "
                        "the verifier derives the 2d-local class from it")
    s.add_argument("--layers", type=int, default=1,
                   help="physical layers for a 2d-local layout "
                        "(1 = single layer, 2 = bilayer); default 1")
    s.add_argument("--trials", type=int, default=20000,
                   help="RIS trials for the distance witness search")
    s.add_argument("--fast-trials", type=int, default=2_000_000,
                   help="gf2_fast trials used to tighten the claim "
                        "(0 disables the accelerator)")
    s.add_argument("--seed", type=int, default=0,
                   help="seed for the RIS distance-witness search "
                        "(default 0; pass a different value to search a "
                        "fresh set of trials)")
    s.add_argument("--out", default=os.path.join(_ROOT, "codes"),
                   help="output DIRECTORY (default: codes/); the filename is "
                        "always <n>-<k>-<d>.json and is not yours to choose")
    s.add_argument("--force", action="store_true",
                   help="overwrite an existing codes/<slug>.json")
    s.add_argument("--dry-run", action="store_true",
                   help="build and verify but do not write the file")
    s.add_argument("--open-pr", action="store_true",
                   help="create the branch, commit, push, and open the PR")
    s.set_defaults(func=cmd_submit)

    r = sub.add_parser("recent", help="what landed recently: codes, research "
                                      "notes, fieldnotes (read before you "
                                      "search)")
    r.add_argument("--days", type=int, default=14,
                   help="look back this many days (default 14)")
    r.set_defaults(func=cmd_recent)

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

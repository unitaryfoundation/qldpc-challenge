r"""Distance-revision harvest: re-gate entries at the deep ladder and emit revision candidates.

Campaign 5 of issue #6198 (issue #6813). A board distance is a witness-backed
upper bound, and the cheapest high-value PR on the board is a same-checks
revision that lowers one: #5996, #5999, #5824, #5825 and the 2026-11-18
batch all went in by the route in CONTRIBUTING.md, "Correcting a distance
already on the board". This script automates the search half of that route
and prepares the filing half.

For every entry it is given (board files, staged candidates, the ``codes/``
files of open PRs, or the entries a fieldnote names) it runs the random
information-set search of ``research/audits/leader_audit.py`` at the
depth-proportional budget of the reachability campaign
(``screening_trials`` from ``research/reachability_campaign.py``, PR #6195:
2000 + 2000 d trials, the deep rung of at least 200k + 20k d at d >= 20,
capped at 2M) on fresh seeds. A validated logical lighter than a side's claim
is a tightening, the event the gate's ``distance_not_refuted`` check would
report at this budget, and the entry is emitted as a revision candidate:

* ``<out>/revisions/<new-slug>.json``: the entry with the tightened side(s)
  lowered, the witness stored with its ``witness_provenance`` (``found_by``
  the harvester's handle, the budget, the tool, the seed), ``d`` the minimum
  over the sides, the name's leading ``[[n,k,d]]`` updated, one sentence
  appended to ``provenance.notes``, and nothing else changed, which is
  exactly the edit ``verify/check_authorship.py`` lets a non-author make;
* ``<out>/revisions/<new-slug>.body.md``: the PR body in the shape of the
  merged revisions, and ``<new-slug>.revision.json``: the record (source,
  sides, trials, seeds, title, the note header).

``--apply <checkout>`` then performs the filing steps of
``research/audits/README.md``, "Filing a distance revision", in that checkout:
moves ``codes/<old>.json`` to the new slug with the revised content, and moves
the note with the revision record on top and the previous note in full under
``## Original note, with the file paths updated`` (the fold
``verify/check_prose.py`` requires, issue #3388). It writes files and never
runs git or gh; the branch, commit, and PR stay explicit. A candidate that
came from an open PR is emitted but never applied: the correction belongs on
that PR.

The accelerator reports the lightest logical over both sides, so a side
whose claim is loose while the other side is lighter does not surface through
it; ``--side-trials N`` adds a pure-NumPy pass of N trials on each side the
joint search did not report (``surrogate.lightest_logical``), slow at large
n and off by default. A side that comes down without moving ``d`` is a
``tightened`` entry; a lower ``d`` is ``refuted``. An entry the search does
not tighten is recorded as ``holds`` (the search reached the claim) or
``inconclusive`` (it did not), the verdict words of ``leader_audit.py``.
Neither is corroboration, and no survival stamp is written, since a stamp
makes ``verify/gate_changed.py`` run the deep battery on the edit. Every
entry's row goes to ``<out>/harvest.jsonl``. With ``--state FILE`` the budget
spent on each entry (keyed by its checks and its claims) is kept across runs,
so a periodic run re-opens an entry only when its claim changed or the
planned budget is larger; ``--rerun`` ignores it.

Usage::

    uv run --extra research python research/revision_harvest.py --handle you \\
        codes/684-*.json --out research/candidates/<run>/harvest
    uv run --extra research python research/revision_harvest.py --handle you \\
        --from-note fieldnotes/2026-11-17-submission-sweep.md --open-prs \\
        --state research/candidates/harvest-state.json --max-minutes 240
    uv run --extra research python research/revision_harvest.py --handle you \\
        codes/514-66-58.json --apply .      # then review, commit, and open the PR

Nothing here touches ``verify/`` or changes a verdict: a candidate this
script emits is filed through the gate like every other correction.
"""
import argparse
import base64
import copy
import datetime
import glob
import hashlib
import json
import math
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, os.path.join(_HERE, "kit"), os.path.join(_HERE, "audits"), os.path.join(_ROOT, "verify")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import leader_audit as la  # noqa: E402
import surrogate  # noqa: E402
from reachability_campaign import screening_trials  # noqa: E402

SCHEMA = "qldpc-revision-harvest/1"
PARAMS = re.compile(r"\[\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]\]")
CODE_MENTION = re.compile(r"codes/([0-9]+-[0-9]+-[0-9]+(?:-[a-z0-9]+)?)\.json")
SLUG = re.compile(r"^(\d+)-(\d+)-(\d+)((?:-[a-z0-9]+)?)$")
SUFFIXES = "bcdefghijklmnopqrstuvwxyz"
VERDICTS = ("refuted", "tightened", "holds", "inconclusive")


# --- input selection ---------------------------------------------------------
def paths_from_text(text, codes_dir):
    """Return the codes/ files a note names: ``codes/<slug>.json`` mentions and ``[[n,k,d]]`` tokens.

    A parameter token resolves to every ``codes/<n>-<k>-<d>*.json`` in
    ``codes_dir`` (the ``-b`` siblings included), so a sweep fieldnote that lists
    its entries by parameters is an input list. Paths that do not exist are
    dropped; the order is the text's, each path once.
    """
    out = []
    for m in CODE_MENTION.finditer(text):
        p = os.path.join(codes_dir, m.group(1) + ".json")
        if os.path.exists(p) and p not in out:
            out.append(p)
    for m in PARAMS.finditer(text):
        n, k, d = m.groups()
        exact = os.path.join(codes_dir, f"{n}-{k}-{d}.json")
        siblings = sorted(glob.glob(os.path.join(codes_dir, f"{n}-{k}-{d}-*.json")))
        for p in ([exact] if os.path.exists(exact) else []) + siblings:
            if p not in out:
                out.append(p)
    return out


def _gh_json(args):
    out = subprocess.check_output(["gh"] + list(args), text=True, stderr=subprocess.STDOUT)
    return json.loads(out)


def fetch_open_pr_codes(out_dir, *, limit=200, gh=_gh_json):
    """Save the ``codes/*.json`` files of every open PR under ``out_dir/pr-<N>/`` and return [(path, N)].

    One ``gh pr list`` call and one ``gh api --method GET`` call per file (a
    ``--field`` without the method would make the call a POST, which the
    contents endpoint answers with a 404). A PR or file that cannot be read is
    reported and skipped; the harvest never fails on a PR it cannot see.
    """
    try:
        prs = gh(["pr", "list", "--state", "open", "--limit", str(limit),
                  "--json", "number,headRefName,headRepository,headRepositoryOwner,files"])
    except (subprocess.CalledProcessError, OSError, json.JSONDecodeError) as e:
        print(f"open PRs: could not list them ({e}); none harvested", flush=True)
        return []
    found = []
    for pr in prs:
        owner = (pr.get("headRepositoryOwner") or {}).get("login")
        repo = (pr.get("headRepository") or {}).get("name")
        branch, number = pr.get("headRefName"), pr.get("number")
        if not (owner and repo and branch and number):
            continue
        for f in pr.get("files") or []:
            path = f.get("path", "")
            if not (path.startswith("codes/") and path.endswith(".json")):
                continue
            try:
                res = gh(["api", "--method", "GET", f"repos/{owner}/{repo}/contents/{path}",
                          "--field", f"ref={branch}"])
                doc = json.loads(base64.b64decode(res.get("content", ""), validate=False).decode("utf-8"))
            except Exception as e:  # noqa: BLE001 - one unreadable file must not end the harvest
                print(f"open PR #{number}: could not read {path} ({str(e)[:80]}); skipped", flush=True)
                continue
            dest_dir = os.path.join(out_dir, f"pr-{number}")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(path))
            with open(dest, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=1)
                fh.write("\n")
            found.append((dest, int(number)))
    return found


def select_shard(items, spec):
    """``I/K``: every K-th item starting at I, in the given order."""
    if not spec:
        return list(items)
    i, k = (int(x) for x in spec.split("/"))
    if not (k >= 1 and 0 <= i < k):
        raise SystemExit(f"--shard {spec}: need 0 <= I < K")
    return [x for j, x in enumerate(items) if j % k == i]


def _n_of(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return int(json.load(fh).get("n", 0))
    except Exception:  # noqa: BLE001 - an unreadable file sorts last and is reported when opened
        return -1


# --- the ladder ---------------------------------------------------------------
def ladder_trials(d_claim, *, scale=1.0, min_trials=1, max_trials=None):
    """Return the depth-proportional budget for a claim of ``d_claim``, scaled and clamped."""
    t = int(math.ceil(screening_trials(d_claim) * float(scale)))
    t = max(int(min_trials), t)
    if max_trials is not None:
        t = min(int(max_trials), t)
    return t


def backend_name():
    return "gf2_fast" if surrogate._fast is not None else "numpy"


def claims_of(doc):
    """Per-side claimed values of a CSS entry, ``{"X": dX, "Z": dZ}``."""
    dist = doc.get("distance") or {}
    return {s: int(dist[s]["value"]) for s in ("X", "Z") if isinstance(dist.get(s), dict) and "value" in dist[s]}


def search_entry(doc, *, trials, seeds, threads=8, pair_depth=10, side_trials=0, log=print):
    """Run the ladder on one CSS entry. Returns the per-side best below the claim and the joint best.

    ``{"best": {side: {"weight", "support", "seed", "trials_at", "backend"}}, "joint": weight, "seconds"}``;
    ``best`` holds only sides whose claim came down, with ``trials_at`` the
    budget spent when the witness was found (cumulative over the joint seeds,
    or the per-side pass's own count). Every witness is re-validated against
    the raw matrices before it counts. With ``side_trials`` > 0 each side the
    joint search did not report gets one NumPy pass of that many trials on the
    first seed.
    """
    n = int(doc["n"])
    HX = la._rows_to_dense(doc["checks"]["X"], n)
    HZ = la._rows_to_dense(doc["checks"]["Z"], n)
    claims = claims_of(doc)
    prepared = surrogate.prepare_distance_search(HX, HZ)
    best, joint, t0 = {}, n + 1, time.time()
    for i, seed in enumerate(seeds):
        weight, side, support, dt = la.ris(HX, HZ, trials, seed, threads, pair_depth, prepared=prepared)
        ok, why = la.validate_witness(n, HX, HZ, side, weight, support)
        if side and not ok:
            log(f"    seed={seed}: DISCARDED d<={weight} on {side}: {why}")
            continue
        if side:
            log(f"    seed={seed}: lightest {side} logical {weight} [{dt:.0f}s]")
            joint = min(joint, int(weight))
            if side in claims and int(weight) < claims[side] and int(weight) < best.get(side, {}).get("weight", n + 1):
                best[side] = {"weight": int(weight), "support": sorted(int(q) for q in support),
                              "seed": int(seed), "trials_at": int(trials) * (i + 1), "backend": backend_name()}
        else:
            log(f"    seed={seed}: no logical found [{dt:.0f}s]")
    if side_trials and seeds:
        for side, (hself, hopp) in (("X", (HX, HZ)), ("Z", (HZ, HX))):
            if side in best or side not in claims:
                continue
            t1 = time.time()
            weight, support = surrogate.lightest_logical(hself, hopp, int(side_trials), int(seeds[0]),
                                                         pair_depth=pair_depth)
            if not support or weight > n:
                log(f"    {side} side, {side_trials} NumPy trials: no logical found [{time.time() - t1:.0f}s]")
                continue
            ok, why = la.validate_witness(n, HX, HZ, side, weight, support)
            if not ok:
                log(f"    {side} side: DISCARDED d<={weight}: {why}")
                continue
            log(f"    {side} side, {side_trials} NumPy trials: lightest {weight} [{time.time() - t1:.0f}s]")
            joint = min(joint, int(weight))
            if int(weight) < claims[side]:
                best[side] = {"weight": int(weight), "support": sorted(int(q) for q in support),
                              "seed": int(seeds[0]), "trials_at": int(side_trials), "backend": "numpy per side"}
    return {"best": best, "joint": joint, "seconds": time.time() - t0}


def verdict(joint, d_claim):
    return la._verdict(joint, d_claim)


# --- the revision document ---------------------------------------------------
def rename_params(name, n, k, d_new):
    """Rewrite the first ``[[n,k,d]]`` of ``name`` to the new d; a name without one is returned as is."""
    def sub(m):
        if int(m.group(1)) == int(n) and int(m.group(2)) == int(k):
            return f"[[{n},{k},{d_new}]]"
        return m.group(0)
    return PARAMS.sub(sub, name or "", count=1)


def revise_doc(doc, best, *, handle, date, trials, pair_depth, backend):
    """Return the entry with the tightened sides lowered, as check_authorship's refutation binding admits.

    Only ``distance``, ``name``, ``schema_version`` (raised to 0.2 when the
    block needs it), and an appended ``provenance.notes`` sentence change.
    """
    new = copy.deepcopy(doc)
    n, k = int(doc["n"]), int(doc["k"])
    parts = []
    for side in ("X", "Z"):
        if side not in best:
            continue
        b = best[side]
        side_backend = b.get("backend", backend)
        tool = f"research/revision_harvest.py RIS {side_backend} pair depth {pair_depth}"[:80]
        old = int(new["distance"][side]["value"])
        new["distance"][side] = {
            "value": b["weight"],
            "confidence": "upper_bound",
            "witness": list(b["support"]),
            "witness_provenance": {
                "found_by": [f"@{handle.lstrip('@')}"],
                "date": date,
                "found_at_samples": int(b["trials_at"]),
                "tool": tool,
                "seeds": [int(b["seed"])],
            },
        }
        parts.append(f"{side} side {old} -> {b['weight']} (random information-set search, "
                     f"research/revision_harvest.py, backend {side_backend}, pair depth {pair_depth}, "
                     f"{b['trials_at']:,} trials, seed {b['seed']})")
    sides = [int(new["distance"][s]["value"]) for s in ("X", "Z") if s in new["distance"]]
    new["distance"]["d"] = min(sides)
    new["name"] = rename_params(new.get("name"), n, k, new["distance"]["d"])
    if str(new.get("schema_version", "0.1")) < "0.2":
        new["schema_version"] = "0.2"
    prov = new.setdefault("provenance", {})
    old_notes = prov.get("notes", "") or ""
    sentence = f"Distance revision {date} (witnesses by @{handle.lstrip('@')}): " + "; ".join(parts) + "."
    prov["notes"] = (old_notes + (" " if old_notes and not old_notes.endswith(" ") else "") + sentence
                     if old_notes else sentence)
    return new


def slug_of(path):
    return os.path.splitext(os.path.basename(path))[0]


def revision_slug(codes_dir, old_slug, n, k, d_new):
    """Return the revised entry's slug: ``<n>-<k>-<d_new>`` with the old suffix, else the next free letter."""
    m = SLUG.match(old_slug)
    suffix = m.group(4) if m else ""
    candidates = [f"{n}-{k}-{d_new}{suffix}"] + [f"{n}-{k}-{d_new}-{c}" for c in SUFFIXES]
    for cand in candidates:
        if cand == old_slug:
            continue
        if not os.path.exists(os.path.join(codes_dir, cand + ".json")):
            return cand
    raise RuntimeError(f"no free slug for [[{n},{k},{d_new}]] in {codes_dir}")


def canonical(doc):
    """Serialize a board file the one way verify/check_codes_format.py accepts."""
    return json.dumps(doc, indent=1) + "\n"


def _eff(n, k, d):
    return k * d * d / n


def pr_text(old_slug, new_slug, old_doc, new_doc, best, *, backend, pair_depth, pr=None):
    """Return the PR title, body, and note header for a revision, in the shape of the merged corrections."""
    n, k = int(old_doc["n"]), int(old_doc["k"])
    d_old, d_new = int(old_doc["distance"]["d"]), int(new_doc["distance"]["d"])
    sides_text = ", ".join(f"{s} side {int(old_doc['distance'][s]['value'])} -> {best[s]['weight']}"
                           for s in ("X", "Z") if s in best)
    if d_new < d_old:
        change = f"[[{n},{k},{d_old}]] -> [[{n},{k},{d_new}]]"
        title = f"Distance revision: {change}"
        headline = f"{change}; kd^2/n {_eff(n, k, d_old):.2f} -> {_eff(n, k, d_new):.2f}."
        supersedes = (f"[[{n},{k},{d_new}]] supersedes the board's [[{n},{k},{d_old}]] entry. The code, its checks, "
                      f"and its original provenance are unchanged; only the distance claim is corrected. The headline "
                      f"kd^2/n falls from {_eff(n, k, d_old):.2f} to {_eff(n, k, d_new):.2f}.")
    else:
        change = f"[[{n},{k},{d_old}]], {sides_text}"
        title = f"Distance revision: {change}"
        headline = (f"d stays {d_old} ({sides_text}); kd^2/n unchanged at {_eff(n, k, d_old):.2f}, the looser side's "
                    "claim is corrected.")
        supersedes = (f"The entry keeps d = {d_old}; {sides_text}. The code, its checks, and its original provenance "
                      "are unchanged; only the looser side's claim is corrected.")
    lines = []
    for side in ("X", "Z"):
        if side in best:
            b = best[side]
            lines.append(f"- {side} side {int(old_doc['distance'][side]['value'])} -> {b['weight']}: random "
                         f"information-set search (`research/revision_harvest.py`, backend "
                         f"{b.get('backend', backend)}, pair depth {pair_depth}), {b['trials_at']:,} trials, "
                         f"seed {b['seed']}.")
    where = (f"the entry `codes/{old_slug}.json` carried by PR #{pr}" if pr
             else f"the existing entry `codes/{new_slug}.json` (filed as `{old_slug}` before this correction)")
    body = "\n".join([
        f"Correction to {where}, by the route in CONTRIBUTING.md (\"Correcting a distance already on the "
        "board\"): matrices untouched, the tightened side(s) lowered with the witness stored under "
        "`witness_provenance`, name and note heading updated, one sentence appended to `provenance.notes`. "
        "No survival stamp, so the gate prices this as a tightening.",
        "",
        *lines,
        "",
        headline,
        "",
        "Each witness was validated against the entry's check matrices when it was found (zero syndrome "
        "against the opposite side's checks, outside the row space of its own side by rank over GF(2)). "
        + ("" if pr else f"The previous note is kept in full under the revision record in `notes/{new_slug}.md`. ")
        + "The distance remains a witness-backed upper bound.",
        "",
    ])
    header = "\n".join([
        f"# [[{n},{k},{d_new}]]: distance revision"
        + (f" of [[{n},{k},{d_old}]]" if d_new < d_old else f", {sides_text}"),
        f"## Revision {new_doc['distance'][next(iter(best))]['witness_provenance']['date']}: {change}",
        supersedes,
        *lines,
        "",
        "| side | claimed | lightest logical found | trials | seed |",
        "|---|---|---|---|---|",
        *[f"| {s} | {int(old_doc['distance'][s]['value'])} | {best[s]['weight']} | {best[s]['trials_at']:,} | "
          f"{best[s]['seed']} |" for s in ("X", "Z") if s in best],
        "",
        f"Each witness was validated against the check matrices of `codes/{new_slug}.json` when it was found: "
        "zero syndrome against the opposite side's checks, and outside the row space of its own side by rank "
        "over GF(2). A side that did not come down keeps its original witness. The distance remains a "
        "witness-backed upper bound, not an exact claim.",
        "",
    ])
    return title, body, header


# --- filing -----------------------------------------------------------------------
def apply_revision(checkout, old_slug, new_slug, new_doc, header):
    """Perform the filing steps in ``checkout``: move the entry and fold the note. Returns the paths written.

    ``codes/<old>.json`` is replaced by ``codes/<new>.json`` with the revised
    content, and ``notes/<old>.md`` (when it exists) by ``notes/<new>.md``
    with ``header`` on top and the previous note in full under
    ``## Original note, with the file paths updated``, its old-slug paths
    pointed at the new slug. No git command runs; ``git add -A codes notes``
    records the moves.
    """
    codes_dir, notes_dir = os.path.join(checkout, "codes"), os.path.join(checkout, "notes")
    old_code, new_code = os.path.join(codes_dir, old_slug + ".json"), os.path.join(codes_dir, new_slug + ".json")
    if not os.path.exists(old_code):
        raise FileNotFoundError(f"{old_code} is not in the checkout; a revision applies to a board entry")
    if os.path.exists(new_code):
        raise FileExistsError(f"{new_code} already exists")
    written = []
    with open(new_code, "w", encoding="utf-8") as fh:
        fh.write(canonical(new_doc))
    os.remove(old_code)
    written.append(new_code)
    old_note, new_note = os.path.join(notes_dir, old_slug + ".md"), os.path.join(notes_dir, new_slug + ".md")
    if os.path.exists(old_note):
        with open(old_note, encoding="utf-8") as fh:
            old_text = fh.read()
        front, body = "", old_text
        if old_text.startswith("---\n"):
            end = old_text.find("\n---\n", 4)
            if end != -1:
                front, body = old_text[:end + 5], old_text[end + 5:]
        body = body.replace(f"codes/{old_slug}.json", f"codes/{new_slug}.json")
        body = body.replace(f"notes/{old_slug}.md", f"notes/{new_slug}.md")
        text = front + header + "## Original note, with the file paths updated\n" + body.lstrip("\n")
        if not text.endswith("\n"):
            text += "\n"
        os.makedirs(notes_dir, exist_ok=True)
        with open(new_note, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.remove(old_note)
        written.append(new_note)
        if len(text.encode("utf-8")) > 10240:
            print(f"  note {new_note} is {len(text.encode('utf-8'))} bytes; the site truncates a note over "
                  "10240 bytes on render, so trim the original narrative or move it to a fieldnote", flush=True)
    return written


# --- state across runs ---------------------------------------------------------------
def state_key(doc):
    """Return the key a periodic run files an entry under: its checks and its per-side claims."""
    h = hashlib.sha256(json.dumps(doc.get("checks"), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    claims = claims_of(doc)
    return f"{h[:24]}|{claims.get('X')}|{claims.get('Z')}"


def load_state(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_state(path, state):
    if not path:
        return
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=os.path.basename(path) + ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def _append(path, row):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


# --- one entry ---------------------------------------------------------------------------
def harvest_one(path, *, out_dir, handle, date, seeds, scale, min_trials, max_trials, threads, pair_depth,
                codes_dir, pr=None, apply_to=None, side_trials=0, log=print):
    """Harvest one file. Returns its ``harvest.jsonl`` row."""
    row = {"schema": SCHEMA, "path": os.path.relpath(path, _ROOT) if path.startswith(_ROOT) else path,
           "pr": pr, "slug": slug_of(path), "date": date}
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        row.update(verdict="error", error=f"unreadable: {e}")
        return row
    if doc.get("code_type", "CSS") != "CSS" or "X" not in (doc.get("checks") or {}):
        row.update(verdict="skipped", error="not a CSS entry; the RIS harness measures CSS codes")
        return row
    claims = claims_of(doc)
    if len(claims) != 2:
        row.update(verdict="skipped", error="distance block without both sides")
        return row
    n, k, d_claim = int(doc["n"]), int(doc["k"]), int(doc["distance"]["d"])
    trials = ladder_trials(d_claim, scale=scale, min_trials=min_trials, max_trials=max_trials)
    backend = backend_name()
    row.update(n=n, k=k, claim=d_claim, claims=claims, trials=trials, seeds=list(seeds), pair_depth=pair_depth,
               backend=backend, key=state_key(doc))
    log(f"{row['slug']}: [[{n},{k},{d_claim}]] X {claims['X']} Z {claims['Z']}, {trials:,} trials x "
        f"{len(seeds)} seeds ({backend}, pair depth {pair_depth})")
    try:
        found = search_entry(doc, trials=trials, seeds=seeds, threads=threads, pair_depth=pair_depth,
                             side_trials=side_trials, log=log)
    except Exception as e:  # noqa: BLE001 - a search that errors is reported, never read as all clear
        row.update(verdict="error", error=f"search failed: {e}")
        return row
    best = found["best"]
    kept = [claims[s] for s in claims if s not in best]
    d_after = min([b["weight"] for b in best.values()] + kept) if best else d_claim
    row.update(seconds=round(found["seconds"], 1), joint=found["joint"] if found["joint"] <= n else None,
               verdict=(verdict(found["joint"], d_claim) if not best
                        else ("refuted" if d_after < d_claim else "tightened")),
               sides={s: {"claim": claims[s], "found": b["weight"], "seed": b["seed"], "trials_at": b["trials_at"]}
                      for s, b in best.items()})
    if not best:
        log(f"  {row['verdict']}: nothing lighter than the claim (lightest seen {row['joint']})")
        return row
    new_doc = revise_doc(doc, best, handle=handle, date=date, trials=trials, pair_depth=pair_depth, backend=backend)
    old_slug = slug_of(path)
    new_slug = revision_slug(codes_dir, old_slug, n, k, new_doc["distance"]["d"])
    title, body, header = pr_text(old_slug, new_slug, doc, new_doc, best, backend=backend, pair_depth=pair_depth,
                                  pr=pr)
    rev_dir = os.path.join(out_dir, "revisions")
    os.makedirs(rev_dir, exist_ok=True)
    stem = os.path.join(rev_dir, new_slug if pr is None else f"pr-{pr}-{new_slug}")
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        fh.write(canonical(new_doc))
    with open(stem + ".body.md", "w", encoding="utf-8") as fh:
        fh.write(body)
    record = {"schema": SCHEMA, "source": row["path"], "pr": pr, "old_slug": old_slug, "new_slug": new_slug,
              "n": n, "k": k, "d_old": d_claim, "d_new": new_doc["distance"]["d"], "sides": row["sides"],
              "trials": trials, "seeds": list(seeds), "pair_depth": pair_depth, "backend": backend,
              "title": title, "note_header": header, "candidate": stem + ".json", "body": stem + ".body.md"}
    with open(stem + ".revision.json", "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=1, sort_keys=True)
        fh.write("\n")
    row.update(d_new=new_doc["distance"]["d"], new_slug=new_slug, revision=stem + ".json", title=title)
    log(f"  {row['verdict'].upper()}: {title} -> {stem}.json")
    if apply_to and pr is None:
        try:
            written = apply_revision(apply_to, old_slug, new_slug, new_doc, header)
            row["applied"] = [os.path.relpath(w, apply_to) for w in written]
            log("  applied: " + ", ".join(row["applied"]))
        except (OSError, FileNotFoundError, FileExistsError) as e:
            row["apply_error"] = str(e)
            log(f"  NOT APPLIED: {e}")
    elif apply_to and pr is not None:
        row["apply_error"] = f"entry comes from open PR #{pr}; file the correction on that PR"
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", help="entry files or globs (codes/*.json, staged candidates)")
    ap.add_argument("--list", action="append", default=[], metavar="FILE",
                    help="a file with one entry path per line (# comments allowed)")
    ap.add_argument("--from-note", action="append", default=[], metavar="FILE",
                    help="harvest the codes/ entries a note or fieldnote names ([[n,k,d]] or codes/ paths)")
    ap.add_argument("--open-prs", action="store_true", help="also harvest the codes/ files of open PRs (via gh)")
    ap.add_argument("--open-pr-limit", type=int, default=200)
    ap.add_argument("--handle", default=os.environ.get("QLDPC_HANDLE"),
                    help="your GitHub handle, written to witness_provenance.found_by (or $QLDPC_HANDLE)")
    ap.add_argument("--out", default=None, help="output directory (default: research/candidates/<run>/harvest)")
    ap.add_argument("--seeds", type=int, nargs="+", default=None, help="RIS seeds (default: two fresh random ones)")
    ap.add_argument("--trials-scale", type=float, default=1.0, help="multiply the ladder budget")
    ap.add_argument("--min-trials", type=int, default=1)
    ap.add_argument("--max-trials", type=int, default=None)
    ap.add_argument("--threads", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--pair-depth", type=int, default=10,
                    help="pair depth of the search; match the depth the claim's own ladder used")
    ap.add_argument("--side-trials", type=int, default=0,
                    help="NumPy trials per side the joint search did not report (slow at large n; default off)")
    ap.add_argument("--order", choices=("n-desc", "n-asc"), default="n-desc")
    ap.add_argument("--shard", default=None, help="I/K: every K-th entry of the order starting at I")
    ap.add_argument("--max-minutes", type=float, default=None, help="open no new entry after this wall clock")
    ap.add_argument("--state", default=None, help="JSON ledger of budgets spent per entry, kept across runs")
    ap.add_argument("--rerun", action="store_true", help="ignore --state and open every entry")
    ap.add_argument("--apply", default=None, metavar="CHECKOUT",
                    help="perform the filing steps in this checkout for board entries that came down")
    ap.add_argument("--codes-dir", default=os.path.join(_ROOT, "codes"), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if not args.handle:
        ap.error("--handle (or $QLDPC_HANDLE) is required: it is written to witness_provenance.found_by")
    if args.out is None:
        from coordination import staging_dir
        args.out = os.path.join(staging_dir(), "harvest")
    os.makedirs(args.out, exist_ok=True)
    date = datetime.date.today().isoformat()
    seeds = args.seeds or [secrets.randbelow(2**31) for _ in range(2)]

    paths, pr_of = [], {}
    for pat in args.paths:
        hits = sorted(glob.glob(pat)) or ([pat] if os.path.exists(pat) else [])
        if not hits:
            print(f"no file matches {pat}", flush=True)
        paths.extend(hits)
    for lst in args.list:
        with open(lst, encoding="utf-8") as fh:
            paths.extend(line.strip() for line in fh if line.strip() and not line.startswith("#"))
    for note in args.from_note:
        with open(note, encoding="utf-8") as fh:
            paths.extend(paths_from_text(fh.read(), args.codes_dir))
    if args.open_prs:
        for p, number in fetch_open_pr_codes(os.path.join(args.out, "open-prs"), limit=args.open_pr_limit):
            paths.append(p)
            pr_of[p] = number
        print(f"open PRs: {len(pr_of)} codes/ files fetched", flush=True)
    seen, ordered = set(), []
    for p in paths:
        ap_ = os.path.abspath(p)
        if ap_ not in seen:
            seen.add(ap_)
            ordered.append(p)
    ordered.sort(key=_n_of, reverse=(args.order == "n-desc"))
    ordered = select_shard(ordered, args.shard)
    print(f"{len(ordered)} entries, seeds {seeds}, backend {backend_name()}, out {args.out}", flush=True)

    state = {} if args.rerun else load_state(args.state)
    ledger = os.path.join(args.out, "harvest.jsonl")
    counts = dict.fromkeys(VERDICTS + ("skipped", "error", "unopened"), 0)
    revisions, t0 = [], time.time()
    for i, path in enumerate(ordered):
        if args.max_minutes is not None and (time.time() - t0) / 60.0 >= args.max_minutes:
            counts["unopened"] = len(ordered) - i
            print(f"budget: {counts['unopened']} entries left unopened at {args.max_minutes:g} min", flush=True)
            break
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            key = state_key(doc)
            planned = ladder_trials(int(doc["distance"]["d"]), scale=args.trials_scale,
                                    min_trials=args.min_trials, max_trials=args.max_trials)
        except Exception:  # noqa: BLE001 - harvest_one reports the unreadable file
            key, planned = None, None
        prior = state.get(key) if key else None
        spent = int(prior.get("trials", 0)) * len(prior.get("seeds", [])) if prior else 0
        if prior and not args.rerun and spent >= planned * len(seeds):
            print(f"{slug_of(path)}: skipped, {prior['trials']:,} trials x {len(prior.get('seeds', []))} seeds "
                  f"already spent on {prior.get('date')} ({prior.get('verdict')})", flush=True)
            continue
        row = harvest_one(path, out_dir=args.out, handle=args.handle, date=date, seeds=seeds,
                          scale=args.trials_scale, min_trials=args.min_trials, max_trials=args.max_trials,
                          threads=args.threads, pair_depth=args.pair_depth, codes_dir=args.codes_dir,
                          pr=pr_of.get(path), apply_to=args.apply, side_trials=args.side_trials)
        _append(ledger, row)
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
        if row.get("revision"):
            revisions.append(row["revision"])
        if row.get("key") and row["verdict"] in VERDICTS:
            state[row["key"]] = {"slug": row["slug"], "trials": row["trials"], "seeds": row["seeds"],
                                 "verdict": row["verdict"], "date": date, "pair_depth": row["pair_depth"]}
            save_state(args.state, state)
    print(f"harvest: {counts['refuted']} refuted, {counts['tightened']} tightened on one side, {counts['holds']} "
          f"hold, {counts['inconclusive']} inconclusive, {counts['skipped']} skipped, {counts['error']} errors, "
          f"{counts['unopened']} unopened; ledger {ledger}", flush=True)
    for r in revisions:
        print(f"  revision candidate: {r}", flush=True)
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())

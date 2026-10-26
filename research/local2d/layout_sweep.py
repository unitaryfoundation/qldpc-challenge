#!/usr/bin/env python3
"""Give the board's layoutless CSS entries a 2D-local layout, cheapest tool first (issue #4148).

An entry with no layout computes as ``unrestricted`` and never improves on
its own. This sweeps the CSS entries that have none, smallest n first,
through the layout tools in this directory in order of cost:

1. ``torus_grid.scan``, the exact screen: a two-block code on Z_l x Z_m with
   the bb.py index convention has a canonical grid layout, and the divisor
   scan reads it off in under a second. Nothing is searched, so a hit is free.
2. ``fold_layout.anneal`` on an integer grid: one layer against the 4.0 cap,
   then two layers against the 7.0 cap. The best two-layer embedding seeds
   the next stage.
3. ``hinge_anneal.run_job``, the hinge-cost annealer (#2156), over its seeds
   and lattice steps, stopping at the first feasible layout.
4. ``tri_hinge_anneal``, one long chain on a triangular lattice, the search
   that produced the layout of codes/510-16-26.json.

Each entry gets --entry-seconds of wall clock, checked between stages and
jobs, and the run stops opening entries at --job-seconds, or once
--max-layouts of them are accepted (the workflow sets it so one PR fits the
verify job). A layout is accepted only when verify/qldpc_verify.py, run on the entry with the layout
attached, returns ok with a 2D-local class: the verifier, not the search, is
the authority on occupancy, spacing, and radius. The accepted layout is kept
under <out-dir>/layouts/<slug>.json, and the entry with it attached under
<out-dir>/codes/ for reading; ``stage`` attaches each layout to the current
codes/ file, re-verifies it, and writes it in the board's canonical format,
as exactly the change check_authorship.py's layout binding admits: a first
``locality`` block credited in contributed_by, an appended provenance note,
and the schema_version bump that contributed_by needs. The layouts-weekly
workflow opens the PR.

Every entry opened is one line of sweep_attempts.jsonl, accepted or not, so a
miss at this budget is not retried at the same budget next week.

    uv run python research/local2d/layout_sweep.py run --job-seconds 14400 --credit @vprusso
    uv run python research/local2d/layout_sweep.py stage --out-dir research/out/layout_sweep
    uv run python research/local2d/layout_sweep.py pr-body --out-dir research/out/layout_sweep --out body.md
"""
import argparse
import contextlib
import copy
import datetime
import glob
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "verify"))
import fold_layout as fl  # noqa: E402
import hinge_anneal as ha  # noqa: E402
import torus_grid as tg  # noqa: E402
import tri_hinge_anneal as th  # noqa: E402

CODES = os.path.join(ROOT, "codes")
ATTEMPTS = os.path.join(HERE, "sweep_attempts.jsonl")
OUT_DIR = os.path.join(ROOT, "research", "out", "layout_sweep")
SINGLE_CAP, BILAYER_CAP = tg.SINGLE_CAP, tg.BILAYER_CAP
STAGES = ("screen", "fold", "hinge", "tri")
TWO_D = ("local-2d-single", "local-2d-bilayer")
TOOL = "research/local2d/layout_sweep.py"


def utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def git_head():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_url():
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not run_id:
        return None
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{run_id}"


def load_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    rows.append(json.loads(line))
    except OSError:
        pass
    return rows


def append_jsonl(path, row):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def canonical(doc):
    """Return the board's one format for codes/*.json (verify/check_codes_format.py)."""
    return json.dumps(doc, indent=1) + "\n"


def layoutless(codes_dir=CODES):
    """Return [(slug, doc)] for every CSS entry with no layout, smallest n first."""
    out = []
    for path in glob.glob(os.path.join(codes_dir, "*.json")):
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("code_type") != "CSS" or doc.get("locality"):
            continue
        out.append((os.path.splitext(os.path.basename(path))[0], doc))
    out.sort(key=lambda sd: (sd[1]["n"], sd[0]))
    return out


def select(entries, *, last, entry_seconds, slugs=None, retry=False):
    """Return the entries to open and a count of the ones passed over.

    An entry a previous run accepted is left alone until its layout lands;
    an entry a previous run missed at this per-entry budget or a longer one
    is reopened only with ``retry``. Naming ``slugs`` restricts the sweep to
    them and lifts both skips.
    """
    if slugs:
        want = set(slugs)
        entries = [sd for sd in entries if sd[0] in want]
    chosen, skipped = [], Counter()
    for slug, doc in entries:
        prev = last.get(slug) if not slugs else None
        if prev and prev.get("outcome") == "accepted":
            skipped["awaiting_pr"] += 1
            continue
        if (prev and not retry and prev.get("outcome") == "miss"
                and (prev.get("entry_seconds") or 0) >= entry_seconds):
            skipped["missed_at_budget"] += 1
            continue
        chosen.append((slug, doc))
    return chosen, skipped


def checks_of(doc):
    return [list(map(int, r)) for r in doc["checks"]["X"]] + [list(map(int, r)) for r in doc["checks"]["Z"]]


def honesty(coords):
    """Return (max qubits per site, min spacing between distinct sites), the verifier's two checks."""
    mult = Counter(tuple(p) for p in coords)
    sites = sorted(mult)
    spacing = min((math.dist(a, b) for i, a in enumerate(sites) for b in sites[i + 1:]), default=float("inf"))
    return max(mult.values()), spacing


def candidate(checks, coords, how, stage):
    """Measure a layout the way the verifier will and return it as a candidate, or None when dishonest."""
    occ, spacing = honesty(coords)
    if occ > 2 or spacing < 1.0 - 1e-9:
        return None
    r = fl.radius(checks, coords)
    cap = SINGLE_CAP if occ == 1 else BILAYER_CAP
    if r > cap + 1e-9:
        return None
    # The claim is rounded up: the verifier requires measured <= claimed, and
    # round(sqrt(17), 4) is below sqrt(17).
    return {"coordinates": [[float(x) for x in p] for p in coords], "layers": occ,
            "radius": math.ceil(r * 1e4) / 1e4, "method": how, "stage": stage}


def screen(doc, checks):
    """Stage 1: the exact torus-grid screen."""
    got = tg.scan(doc, occupancy=2, top=1)
    if not got or not got[0]["within_cap"]:
        return None, (got[0]["radius"] if got else None)
    c = got[0]
    coords = tg.grid(c["l"], c["m"], *c["fold"])
    how = (f"torus_grid.py: the two-block index convention read off as a Z_{c['l']} x Z_{c['m']} grid, "
           f"one qubit of each block per site, no search; radius measured with the verifier's rule ({TOOL})")
    return candidate(checks, coords, how, "screen"), c["radius"]


def _boxes(n, layers):
    need = math.ceil(n / layers)
    side = math.ceil(math.sqrt(need))
    out = []
    for w, h in ((side, side), (side + 1, side), (side + 1, side + 1), (side + 2, side + 1)):
        if w * h * layers >= n and (w, h) not in out:
            out.append((w, h))
    return out


def fold(checks, n, layers, target, deadline, iters, seed=0):
    """Stage 2: fold_layout.anneal over a few boxes; return (candidate or None, best coords, best radius)."""
    best_c, best_r, how = None, float("inf"), None
    for w, h in _boxes(n, layers):
        if time.time() > deadline:
            break
        coords, r = fl.anneal(checks, n, fl.box_sites(w, h), layers=layers, seed=seed + w, iters=iters)
        if r < best_r:
            best_c, best_r = coords, r
            how = (f"fold_layout.anneal on a {w} x {h} integer grid, {layers} per site, seed {seed + w}, "
                   f"{iters} iterations ({TOOL})")
        if r <= target + 1e-9:
            return candidate(checks, coords, how, "fold"), best_c, best_r
    return None, best_c, best_r


def hinge(checks, n, init, deadline, iters, seeds):
    """Stage 3: hinge_anneal.run_job over seeds and lattice steps until one is feasible."""
    best_r = float("inf")
    for seed in range(seeds):
        for h, w, hh in ha.LATTICES:
            if time.time() > deadline:
                return None, best_r
            r, coords, it, _, tag = ha.run_job((seed, h, w, hh, init, iters, checks, n))
            best_r = min(best_r, r)
            if tag == "feasible":
                how = (f"hinge_anneal.run_job: hinge cost at radius {ha.TARGET}, lattice step {h}, seed {seed}, "
                       f"{it} of {iters} iterations from a fold_layout integer-grid start ({TOOL})")
                return candidate(checks, coords, how, "hinge"), best_r
    return None, best_r


def tri(path, checks, iters, seed=1):
    """Stage 4: tri_hinge_anneal's single long chain; its chain cannot be interrupted, so the caller sizes it."""
    out = tempfile.mktemp(prefix="tri-", suffix=".json")
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            th.main([path, "--out", out, "--iters", str(iters), "--seed", str(seed)])
        with open(out, encoding="utf-8") as f:
            got = json.load(f)
    finally:
        if os.path.exists(out):
            os.remove(out)
    how = f"tri_hinge_anneal.py: hex lattice, T 6.95, seed {seed}, {iters} iterations ({TOOL})"
    return candidate(checks, got["coordinates"], how, "tri"), got["radius"]


def attach(doc, layout, *, credit, date):
    """Return the entry with the layout attached, the way the layout binding admits."""
    new = copy.deepcopy(doc)
    layers = layout["layers"]
    new["locality"] = {
        "coordinates": [list(p) for p in layout["coordinates"]],
        "layers": layers,
        "interaction_radius": layout["radius"],
        "contributed_by": {"by": [credit], "date": date, "method": layout["method"][:400]},
    }
    try:
        version = tuple(int(x) for x in str(new.get("schema_version", "0.1")).split("."))
    except ValueError:
        version = (0, 1)
    if version < (0, 2):
        new["schema_version"] = "0.2"
    prov = new.setdefault("provenance", {})
    kind = "single-layer" if layers == 1 else "bilayer"
    note = (f"Layout added {date} by {credit}: {kind} coordinates with interaction radius "
            f"{layout['radius']} ({TOOL}, {layout['stage']} stage).")
    prov["notes"] = (prov["notes"] + " " + note) if prov.get("notes") else note
    return new


def verify_layout(doc):
    """Return (ok, locality class, failed check names) from the verifier."""
    import qldpc_verify as V
    with contextlib.redirect_stdout(io.StringIO()):
        rep = V.verify(doc, refute=False)
    cls = rep.get("computed", {}).get("locality_class", "unrestricted")
    failed = [c.get("name") or c.get("check") for c in rep.get("checks", []) if not c.get("ok")]
    return bool(rep.get("ok")), cls, failed


def attempt(slug, doc, path, *, stages, entry_seconds, fold_iters, hinge_iters, hinge_seeds, tri_iters,
            tri_rate=8000.0):
    """Run the stages on one entry; return a result dict with the accepted layout when there is one."""
    t0 = time.time()
    deadline = t0 + entry_seconds
    checks, n = checks_of(doc), doc["n"]
    best_r, found, init = None, None, None

    def better(r):
        nonlocal best_r
        if r is not None and (best_r is None or r < best_r):
            best_r = r

    if "screen" in stages:
        found, r = screen(doc, checks)
        better(r)
    if found is None and "fold" in stages and time.time() < deadline:
        found, _, r = fold(checks, n, 1, SINGLE_CAP, deadline, fold_iters)
        better(r)
        if found is None:
            found, init, r = fold(checks, n, 2, BILAYER_CAP, deadline, fold_iters)
            better(r)
    if found is None and "hinge" in stages and time.time() < deadline:
        if init is None:
            init = ha.integer_init(checks, n, iters=min(fold_iters, 200_000))
        found, r = hinge(checks, n, init, deadline, hinge_iters, hinge_seeds)
        better(r)
    if found is None and "tri" in stages and deadline - time.time() >= tri_iters / tri_rate:
        found, r = tri(path, checks, tri_iters)
        better(r)
    return {"layout": found, "best_radius": round(best_r, 4) if best_r is not None else None,
            "secs": round(time.time() - t0, 1)}


def run_sweep(*, out_dir, attempts_path, credit, job_seconds, entry_seconds, stages=STAGES, codes_dir=CODES,
              slugs=None, retry=False, max_entries=0, max_layouts=0, fold_iters=100_000, hinge_iters=150_000,
              hinge_seeds=4, tri_iters=2_000_000):
    """Open layoutless entries smallest first until the budget is spent; keep what the verifier accepts.

    ``max_layouts`` stops the run once that many layouts are accepted, so the PR
    the workflow opens stays inside the verify job's window: the gate runs its
    deep battery on every entry whose first layout makes it a locality record.
    """
    date, head, url = utc_today(), git_head(), run_url()
    last = {r["slug"]: r for r in load_jsonl(attempts_path)}
    chosen, skipped = select(layoutless(codes_dir), last=last, entry_seconds=entry_seconds, slugs=slugs,
                             retry=retry)
    if max_entries:
        chosen = chosen[:max_entries]
    manifest = {"date": date, "head": head, "run": url, "credit": credit, "job_seconds": job_seconds,
                "entry_seconds": entry_seconds, "stages": list(stages), "selected": len(chosen),
                "skipped": dict(skipped), "results": [], "staged": [], "stopped_by_budget": False,
                "stopped_by_cap": False, "left": 0}
    os.makedirs(os.path.join(out_dir, "layouts"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "codes"), exist_ok=True)
    t_start = time.time()
    for i, (slug, doc) in enumerate(chosen):
        if time.time() - t_start > job_seconds:
            manifest["stopped_by_budget"], manifest["left"] = True, len(chosen) - i
            break
        if max_layouts and len(manifest["staged"]) >= max_layouts:
            manifest["stopped_by_cap"], manifest["left"] = True, len(chosen) - i
            break
        path = os.path.join(codes_dir, slug + ".json")
        got = attempt(slug, doc, path, stages=stages, entry_seconds=entry_seconds, fold_iters=fold_iters,
                      hinge_iters=hinge_iters, hinge_seeds=hinge_seeds, tri_iters=tri_iters)
        row = {"date": date, "head": head, "run": url, "slug": slug, "n": doc["n"], "k": doc["k"],
               "d": doc["distance"]["d"], "family": doc.get("family"), "entry_seconds": entry_seconds,
               "secs": got["secs"], "best_radius": got["best_radius"], "outcome": "miss", "stage": None,
               "layers": None, "class": None}
        layout = got["layout"]
        if layout is not None:
            new = attach(doc, layout, credit=credit, date=date)
            ok, cls, failed = verify_layout(new)
            row.update(stage=layout["stage"], layers=layout["layers"], radius=layout["radius"], **{"class": cls})
            if ok and cls in TWO_D:
                row["outcome"] = "accepted"
                layout = dict(layout, credit=credit, date=date, slug=slug)
                with open(os.path.join(out_dir, "layouts", slug + ".json"), "w", encoding="utf-8") as f:
                    json.dump(layout, f, indent=1, sort_keys=True)
                with open(os.path.join(out_dir, "codes", slug + ".json"), "w", encoding="utf-8", newline="\n") as f:
                    f.write(canonical(new))
                manifest["staged"].append(slug)
            else:
                row["note"] = "the verifier refused the layout: " + (", ".join(failed) or cls)
        append_jsonl(attempts_path, row)
        manifest["results"].append(row)
        print(f"{slug}: {row['outcome']}" + (f" ({row['stage']}, {row['layers']} layers, radius {row.get('radius')}, "
                                              f"{row['class']})" if row["outcome"] == "accepted" else
                                              f" (best radius {row['best_radius']})") + f" in {row['secs']} s",
              flush=True)
    manifest["opened"] = len(manifest["results"])
    manifest["seconds"] = round(time.time() - t_start, 1)
    manifest["outcomes"] = dict(Counter(r["outcome"] for r in manifest["results"]))
    manifest["by_stage"] = dict(Counter(r["stage"] for r in manifest["results"] if r["outcome"] == "accepted"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "run.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary_markdown(manifest))
    with open(os.path.join(out_dir, "counts.txt"), "w", encoding="utf-8") as f:
        f.write(counts_line(manifest) + "\n")
    return manifest


def counts_line(m):
    """Return the one-line tally the workflow puts in its commit message."""
    o = m.get("outcomes", {})
    return f"{m.get('opened', 0)} opened, accepted {o.get('accepted', 0)}, miss {o.get('miss', 0)}"


def _counts(d):
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))


def summary_markdown(m):
    o = m.get("outcomes", {})
    lines = [f"## layout sweep of {m['date']}", "",
             f"main at {(m.get('head') or '?')[:12]}, {m['entry_seconds']} s per entry, job budget "
             f"{m['job_seconds']} s, stages {', '.join(m['stages'])}. Opened {m.get('opened', 0)} of "
             f"{m['selected']} selected entries in {m.get('seconds', 0)} s"
             + (f"; stopped by the budget with {m['left']} left for the next run." if m.get("stopped_by_budget")
                else f"; stopped at the layout cap with {m['left']} left for the next run."
                if m.get("stopped_by_cap") else "."), "",
             f"accepted {o.get('accepted', 0)} (" + (_counts(m.get("by_stage", {})) or "none")
             + f"), miss {o.get('miss', 0)}; skipped " + (_counts(m["skipped"]) or "none"), ""]
    acc = [r for r in m["results"] if r["outcome"] == "accepted"]
    if acc:
        lines += ["| entry | family | layers | radius | class | stage | s |", "|---|---|---|---|---|---|---|"]
        for r in acc:
            lines.append(f"| {r['slug']} | {r.get('family') or ''} | {r['layers']} | {r['radius']} | {r['class']} | "
                         f"{r['stage']} | {r['secs']} |")
        lines.append("")
    refused = [r for r in m["results"] if r.get("note")]
    if refused:
        lines.append("refused by the verifier: " + ", ".join(f"{r['slug']} ({r['note']})" for r in refused))
        lines.append("")
    return "\n".join(lines)


def stage(out_dir, *, codes_dir=CODES, credit=None):
    """Attach each staged layout to the current codes/ file, re-verify, and write it canonically.

    An entry that gained a layout since the run, or whose checks or distance
    changed, is left alone and reported. Returns (staged, skipped) slug lists.
    """
    src = os.path.join(out_dir, "layouts")
    staged, skipped = [], []
    for name in sorted(os.listdir(src)) if os.path.isdir(src) else []:
        if not name.endswith(".json"):
            continue
        slug = name[:-5]
        with open(os.path.join(src, name), encoding="utf-8") as f:
            layout = json.load(f)
        path = os.path.join(codes_dir, slug + ".json")
        if not os.path.exists(path):
            skipped.append((slug, "no longer on the board"))
            continue
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("locality"):
            skipped.append((slug, "already has a layout"))
            continue
        new = attach(doc, layout, credit=credit or layout["credit"], date=layout["date"])
        ok, cls, failed = verify_layout(new)
        if not ok or cls not in TWO_D:
            skipped.append((slug, "the verifier refused it now: " + (", ".join(failed) or cls)))
            continue
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(canonical(new))
        staged.append(slug)
    return staged, skipped


def pr_text(m, staged=None):
    """Return (title, body) of the layouts PR for a run manifest."""
    rows = [r for r in m["results"] if r["outcome"] == "accepted" and (staged is None or r["slug"] in staged)]
    n = len(rows)
    noun = "entry" if n == 1 else "entries"
    title = f"Add first 2D-local layouts for {n} {noun} from the weekly layout sweep of {m['date']}"
    run = f" ([run]({m['run']}))" if m.get("run") else ""
    by_stage = Counter(r["stage"] for r in rows)
    classes = Counter(r["class"] for r in rows)
    body = [
        f"Adds a first locality block to {n} board {noun} that had none, found by the weekly layout sweep of "
        f"{m['date']}{run} (research/local2d/layout_sweep.py, issue #4148). Only locality is added, with the "
        "schema_version bump to 0.2 that contributed_by needs and an appended provenance note. The codes, their "
        "distances, and provenance.authors are untouched. Layout credit goes in locality.contributed_by, the "
        f"binding verify/check_authorship.py uses for a first layout, and is {m['credit']}, the handle the "
        "workflow is configured to open the PR under. It widens no edit rights over the entries.",
        "",
        "Each entry competed only in the unrestricted cells. " + ", ".join(
            f"{v} {'enter' if v != 1 else 'enters'} {k}" for k, v in sorted(classes.items())) + ".",
        "",
        "| entry | family | layers | radius | class | stage |", "|---|---|---|---|---|---|"]
    for r in rows:
        body.append(f"| {r['slug']} | {r.get('family') or ''} | {r['layers']} | {r['radius']} | {r['class']} | "
                    f"{r['stage']} |")
    body += ["",
             "How the layouts were found, cheapest tool first, and the stage column says which one placed each "
             f"entry: {by_stage.get('screen', 0)} by research/local2d/torus_grid.py, the exact screen that reads "
             "a two-block code's grid off its index convention and searches nothing; "
             f"{by_stage.get('fold', 0)} by research/local2d/fold_layout.py, simulated annealing over "
             f"integer-grid sites; {by_stage.get('hinge', 0)} by research/local2d/hinge_anneal.py, the hinge-cost "
             f"annealer of #2156 started from a fold_layout embedding; {by_stage.get('tri', 0)} by "
             "research/local2d/tri_hinge_anneal.py, one long chain on a triangular lattice. The exact seeds and "
             "iteration counts are in each entry's contributed_by.method.",
             "",
             "How they were checked: every entry was re-run through verify/qldpc_verify.py with the layout "
             "attached, which recomputes the interaction radius from the coordinates and the two honesty "
             "conditions (at most layers qubits per site, distinct sites at least one unit apart), and was "
             "accepted only on ok with the class shown above. The workflow also ran "
             "verify/check_codes_format.py, verify/check_authorship.py for the credited handle, and "
             "verify/check_submission_scope.py on this branch before opening the PR. The entries the sweep "
             "opened and could not place are in research/local2d/sweep_attempts.jsonl on main.",
             "",
             "Opened by the layouts-weekly workflow. A pull request opened with the Actions token gets no "
             "pull_request runs, and verify.yml binds a first layout to the PR author, so the gate passes only "
             "on a PR opened by the credited handle. The workflow's run summary has the output of the checks it "
             "ran on this branch."]
    return title, "\n".join(body) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="sweep the layoutless entries")
    r.add_argument("--out-dir", default=OUT_DIR)
    r.add_argument("--attempts", default=ATTEMPTS)
    r.add_argument("--credit", required=True, help="@handle credited in locality.contributed_by")
    r.add_argument("--job-seconds", type=float, default=4 * 3600)
    r.add_argument("--entry-seconds", type=float, default=600)
    r.add_argument("--stages", nargs="+", default=list(STAGES), choices=STAGES)
    r.add_argument("--slugs", nargs="*", default=None)
    r.add_argument("--retry", action="store_true", help="reopen entries missed at this budget")
    r.add_argument("--max-entries", type=int, default=0, help="open at most this many entries")
    r.add_argument("--max-layouts", type=int, default=0,
                   help="stop once this many layouts are accepted (one PR's worth for the verify job)")
    r.add_argument("--fold-iters", type=int, default=100_000)
    r.add_argument("--hinge-iters", type=int, default=150_000)
    r.add_argument("--hinge-seeds", type=int, default=4)
    r.add_argument("--tri-iters", type=int, default=2_000_000)
    s = sub.add_parser("stage", help="attach the staged layouts to codes/")
    s.add_argument("--out-dir", default=OUT_DIR)
    s.add_argument("--credit", default=None, help="override the credited handle")
    p = sub.add_parser("pr-body", help="write the PR body; prints its title")
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        if not a.credit.startswith("@"):
            ap.error("--credit is an @handle")
        m = run_sweep(out_dir=a.out_dir, attempts_path=a.attempts, credit=a.credit, job_seconds=a.job_seconds,
                      entry_seconds=a.entry_seconds, stages=tuple(a.stages), slugs=a.slugs, retry=a.retry,
                      max_entries=a.max_entries, max_layouts=a.max_layouts, fold_iters=a.fold_iters,
                      hinge_iters=a.hinge_iters, hinge_seeds=a.hinge_seeds, tri_iters=a.tri_iters)
        o = m["outcomes"]
        print(f"opened {m['opened']} of {m['selected']}: accepted {o.get('accepted', 0)} (staged under "
              f"{os.path.relpath(a.out_dir, ROOT)}), miss {o.get('miss', 0)}, left {m['left']}")
        return 0
    if a.cmd == "stage":
        staged, skipped = stage(a.out_dir, credit=a.credit)
        print("staged: " + (" ".join(staged) or "nothing"))
        for slug, why in skipped:
            print(f"left alone: {slug}: {why}")
        return 0
    with open(os.path.join(a.out_dir, "run.json"), encoding="utf-8") as f:
        m = json.load(f)
    staged = sorted(os.path.splitext(n)[0] for n in os.listdir(os.path.join(a.out_dir, "layouts"))
                    if n.endswith(".json"))
    title, body = pr_text(m, staged=staged)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(body)
    print(title)
    return 0


if __name__ == "__main__":
    sys.exit(main())

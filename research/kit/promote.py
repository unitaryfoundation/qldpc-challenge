r"""promote -- assemble the submission bundle for a candidate the gate has passed.

The gate is fast and the search is the interesting part, but the stretch between
``validate_candidate.py`` returning ``passed: true`` and an open PR is neither:
it is a fixed list of mechanical steps (copy the validated document into
``codes/``, retype the ladder into ``notes/<slug>.md``, fill the PR body's
checklist and frontier section, write the ``repro/<slug>.json`` manifest from
the recipe the candidate was staged with, run the prose check) that has been
rewritten as throwaway shell once per campaign. Issue #2328 measures what that costs and
where it fails: glue that scrapes the CLI's human-oriented output, fails to
parse it, and fails silently.

This module is the same tail with a machine-readable contract. It takes a
validated candidate plus an *evidence record* holding the ladder, the sweep
counts, and the dead ends the campaign already produced, and returns one JSON
report:

    {"schema": "qldpc-promote/1", "ok": true, "slug": "...", "title": "...",
     "branch": "...", "files": {...}, "body_file": "...", "gates": {...},
     "blocked_by": [...], "needs_human": [...], "commands": [...]}

``ok`` is the verdict. Nothing has to be read out of printed prose, so a
batch driver is a loop over ``promote_all`` and a check of one boolean.

What it does NOT do, on purpose:

* **It never weakens a gate.** ``verify/`` is read, never written. Every bundle
  runs the trusted gate (``validate_candidate``, full refutation on a fresh
  seed) on the FINAL document, and then ``verify/check_prose.py`` on the body
  and the files, in that order. A failure is a blocker, and the checker's own
  output is carried into the report verbatim.
* **It never re-searches for a witness.** The candidate arrives validated and
  its witnesses are already checked by the verifier; searching again is the
  45 minutes issue #2328 measures. Because skipping that search also removes
  the deep pass ``qldpc submit`` would have run, the bundle is refused unless
  the evidence record shows the ladder already spent at least
  ``DEFAULT_MIN_DEEP_TRIALS`` trials per side on a fresh seed and settled
  there: the depth is required, not the repetition. A ladder rung reading
  BELOW the claimed distance is a blocker, not a rounding difference.
* **It never runs git or gh.** Publication authorization is a human's, per
  ``AGENTS.md``; the report carries the exact command sequence and
  ``--script`` writes it out, so no campaign has to invent one again.
* **It does not generate the circuit tier.** ``./qldpc submit`` does that, and
  a candidate that should carry circuits is reported as needing one rather
  than quietly shipped without.

Usage::

    uv run --frozen python research/kit/promote.py plan.json [plan2.json ...] \
        --authors @handle --json bundles.json --script open-prs.sh

A *plan* is ``{"candidate": "<path to the validated JSON>", "evidence": {...}}``
or a list of those. ``EVIDENCE_REQUIRED`` names the fields the note cannot be
written without; they are the research judgment the tool has no way to derive.
"""
import argparse
import copy
import datetime
import json
import os
import shlex
import subprocess
import sys
import textwrap
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _rel in ("verify", "site", "cli", os.path.join("research", "kit")):
    _p = os.path.join(_ROOT, _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import escalation  # noqa: E402
import qldpc as cli  # noqa: E402
import qldpc_verify  # noqa: E402
import validate_candidate as gate  # noqa: E402
from submit import read_recipe, recipe_from_spec, write_repro_manifest  # noqa: E402

REPORT_SCHEMA = "qldpc-promote/1"

# cli/qldpc.py's --fast-trials default is 2,000,000 accelerator trials shared
# across the two sides, on top of 20,000 RIS trials per side. Reusing the
# validated witness skips that pass, so the ladder has to have already paid for
# it: half the shared budget is the matching per-side depth.
SUBMIT_FAST_TRIALS = 2_000_000
DEFAULT_MIN_DEEP_TRIALS = SUBMIT_FAST_TRIALS // 2

# notes/<slug>.md is capped by cli/qldpc.py at the same size.
NOTE_CAP_BYTES = 10 * 1024

# The evidence a note cannot be written without. Each is research judgment or a
# measurement only the campaign has; nothing here is derivable from the
# document, which is exactly why these stay inputs.
EVIDENCE_REQUIRED = ("headline", "direction", "searched", "ladder", "frontier",
                     "reproduction")

EVIDENCE_KEYS = EVIDENCE_REQUIRED + (
    "ladder_note", "dead_ends", "tools", "peer_audit", "construction",
    "references", "equivalence", "budget")

# provenance.construction as cli/qldpc.py defaults it: present, and says nothing.
_CLI_DEFAULT_CONSTRUCTION = "contributed via qldpc submit"


class PromoteError(ValueError):
    """An input this module will not build a bundle from."""


# ----------------------------------------------------------------------------
# inputs
# ----------------------------------------------------------------------------
def load_plan(path):
    """Read a plan file and return its list of ``(candidate_doc, evidence, recipe)``.

    ``recipe`` is the plan's own ``recipe`` key when it has one, else the spec
    ``submit.save_submission`` kept beside a candidate given by path
    (``<stem>.recipe.json``), else None; it becomes ``repro/<slug>.json`` in
    the bundle (issue #2955, item 3).
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    plans = raw if isinstance(raw, list) else [raw]
    out = []
    for i, plan in enumerate(plans):
        if not isinstance(plan, dict) or "candidate" not in plan:
            raise PromoteError(f"{path}[{i}]: a plan needs a 'candidate' key")
        cand = plan["candidate"]
        recipe = plan.get("recipe")
        if isinstance(cand, str):
            cand_path = cand if os.path.isabs(cand) else os.path.join(
                os.path.dirname(os.path.abspath(path)), cand)
            if not os.path.exists(cand_path):
                cand_path = os.path.join(_ROOT, cand)
            with open(cand_path, encoding="utf-8") as f:
                cand = json.load(f)
            if recipe is None:
                recipe = read_recipe(cand_path)
        out.append((cand, plan.get("evidence") or {}, recipe))
    return out


def check_evidence(evidence):
    """Return the list of evidence problems ([] means usable)."""
    problems = []
    unknown = sorted(set(evidence) - set(EVIDENCE_KEYS))
    if unknown:
        problems.append(f"unknown evidence key(s) {unknown}; allowed: "
                        f"{list(EVIDENCE_KEYS)}")
    for key in EVIDENCE_REQUIRED:
        value = evidence.get(key)
        if value is None or (isinstance(value, str) and not value.strip()) \
                or (isinstance(value, list) and not value):
            problems.append(f"evidence.{key} is required and is empty")
    return problems


# ----------------------------------------------------------------------------
# the confirmation ladder
# ----------------------------------------------------------------------------
def ladder_facts(rungs, claimed_d):
    """Summarize a confirmation ladder against the distance the document claims.

    ``rungs`` is the ladder oldest first, in the form ``escalation.norm_rung``
    accepts. ``flat_fresh_rungs_at_best`` counts the trailing fresh-seed rungs
    that agree with the cumulative best bound, the same way
    ``escalation.rung_brief`` does, so the escalation gate and this one read one
    ladder the same way.
    """
    rungs = [escalation.norm_rung(r) for r in rungs]
    if not rungs:
        raise PromoteError("evidence.ladder needs at least one rung")
    best = min(r["d"] for r in rungs)
    fresh = [r for r in rungs if r["fresh"]]
    flat = 0
    for r in reversed(fresh):
        if r["d"] == best:
            flat += 1
        else:
            break
    return {
        "rungs": rungs,
        "cumulative_best_bound": best,
        "claimed_d": int(claimed_d),
        "reads_below_claim": best < int(claimed_d),
        "flat_fresh_rungs_at_best": flat,
        "deepest_fresh_trials": max((r["trials"] for r in fresh), default=0),
        "trials_spent": sum(r["trials"] for r in rungs),
        "fresh_rungs_total": len(fresh),
    }


def ladder_blockers(facts, min_deep_trials):
    """Return the reasons this ladder cannot stand in for the skipped re-search."""
    out = []
    if facts["reads_below_claim"]:
        out.append(
            f"the ladder's best reading is d <= {facts['cumulative_best_bound']} "
            f"but the document claims d = {facts['claimed_d']}: repackage the "
            f"candidate at the reading the ladder actually reached")
    if facts["deepest_fresh_trials"] < min_deep_trials:
        out.append(
            f"deepest fresh-seed rung is {facts['deepest_fresh_trials']:,} "
            f"trials per side, below the {min_deep_trials:,} this module "
            f"requires before it will reuse a witness instead of re-searching; "
            f"run a deeper rung, or package with ./qldpc submit, which searches "
            f"again itself")
    if facts["flat_fresh_rungs_at_best"] < escalation.MIN_FLAT_RUNGS:
        out.append(
            f"only {facts['flat_fresh_rungs_at_best']} fresh-seed rung(s) agree "
            f"at d <= {facts['cumulative_best_bound']}; "
            f"{escalation.MIN_FLAT_RUNGS} are required before the bound counts "
            f"as settled (research/kit/escalation.py)")
    return out


# ----------------------------------------------------------------------------
# the document
# ----------------------------------------------------------------------------
def candidate_slug(doc):
    """Return the board slug ``n-k-d`` for a submission document."""
    return f"{doc['n']}-{doc['k']}-{doc['distance']['d']}"


def build_doc(candidate, evidence, facts, *, authors=None, date=None):
    """Return the document to submit: the validated candidate plus its provenance.

    Nothing about the code changes. What is filled in is the provenance the note
    states anyway (construction, references, the deepest per-side RIS budget, the
    equivalence finding), so the two cannot disagree and neither is retyped.
    """
    doc = copy.deepcopy(candidate)
    prov = dict(doc.get("provenance") or {})
    if authors:
        prov["authors"] = list(authors)
    if not prov.get("authors"):
        raise PromoteError("no authors: pass --authors or set provenance.authors")
    construction = ((evidence.get("construction") or "").strip()
                    or (prov.get("construction") or "").strip())
    if not construction or construction == _CLI_DEFAULT_CONSTRUCTION:
        raise PromoteError(
            "provenance.construction is the schema's own required field and is "
            "empty or still the CLI placeholder; set evidence.construction to "
            "how the code was actually built (family, polynomials, search)")
    prov["construction"] = construction
    if evidence.get("references"):
        prov["references"] = list(evidence["references"])
    tools = evidence.get("tools") or {}
    if tools.get("model"):
        prov["model"] = tools["model"]
    if evidence.get("equivalence"):
        prov["notes"] = evidence["equivalence"]
    prov.setdefault("origin", "submission")
    prov["date"] = date or prov.get("date") or datetime.date.today().isoformat()

    budget = dict(evidence.get("budget") or {})
    budget["ris_trials_per_side"] = facts["deepest_fresh_trials"]
    prov["search_budget"] = budget
    doc["provenance"] = prov
    # search_budget is a schema 0.3 field; an older declared version would make
    # the document invalid against its own schema.
    if str(doc.get("schema_version", "0.1")) < "0.3":
        doc["schema_version"] = "0.3"
    return doc


# ----------------------------------------------------------------------------
# the research note
# ----------------------------------------------------------------------------
NOTE_WIDTH = 78


def _wrap(text, width=NOTE_WIDTH):
    """Hard-wrap prose, leaving fenced code, tables, and indented blocks alone.

    The notes on the board are wrapped; one paragraph on one very long line is
    the same markdown but is not reviewable in a diff.
    """
    out, buf, fenced = [], [], False

    def flush():
        if buf:
            out.extend(textwrap.wrap(" ".join(buf), width=width,
                                     break_long_words=False,
                                     break_on_hyphens=False))
            buf.clear()

    for ln in text.strip().split("\n"):
        if ln.strip().startswith("```"):
            flush()
            fenced = not fenced
            out.append(ln)
        elif (fenced or not ln.strip() or ln.startswith(("|", "    ", "\t"))
                or ln.lstrip().startswith(("- ", "* ", "> ", "#"))):
            flush()
            out.append(ln)
        else:
            buf.append(ln.strip())
    flush()
    return "\n".join(out)


def _bullets(items):
    return "\n".join(
        textwrap.fill(f"- {str(x).strip()}", width=NOTE_WIDTH,
                      subsequent_indent="  ", break_long_words=False,
                      break_on_hyphens=False)
        for x in items)


def _confidence_line(doc):
    dist = doc["distance"]
    sides = [s for s in ("X", "Z", "P") if s in dist]
    claims = []
    for s in sides:
        conf = dist[s].get("confidence", "upper_bound")
        rel = "d =" if conf == "exact" else "d <="
        claims.append(f"{s}: {rel} {dist[s]['value']} ({conf})")
    return ", ".join(claims)


def _tools_paragraph(doc, evidence):
    tools = evidence.get("tools") or {}
    parts = []
    model = tools.get("model") or (doc.get("provenance") or {}).get("model")
    if model:
        parts.append(f"Model: {model}"
                     + (f" ({tools['harness']})" if tools.get("harness") else "")
                     + ".")
    elif tools.get("harness"):
        parts.append(f"Harness: {tools['harness']}.")
    if tools.get("modules"):
        parts.append("Repo tooling: "
                     + ", ".join(f"`{m}`" for m in tools["modules"]) + ".")
    parts.append("The local verdict is `verify/validate_candidate.py`; the "
                 "bundle was assembled by `research/kit/promote.py`.")
    if tools.get("compute"):
        parts.append(f"Compute: {tools['compute']}.")
    return " ".join(parts)


def note_markdown(doc, evidence, facts):
    """Render ``notes/<slug>.md`` in the ``notes/TEMPLATE.md`` section order.

    The ladder table, the distance claim, the model line, and the header's
    ``[[n,k,d]]`` are all read off the document and the evidence record, so the
    three things that used to be retyped per candidate (and that
    ``verify/check_prose.py`` rejects when they drift) cannot drift.
    """
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    lines = [f"# [[{n},{k},{d}]] {evidence['headline'].strip()}", "",
             "## Direction & hypothesis", "",
             _wrap(evidence["direction"]), "",
             "## What was searched", "",
             _wrap(evidence["searched"]), "",
             "## Evidence trail", "",
             _wrap("Confirmation ladder for the submitted code, each rung a "
                   "fresh seed unless marked otherwise, reading the lightest "
                   "logical found:"),
             "",
             "| budget (trials/side) | lightest logical |",
             "| ---: | ---: |"]
    for r in facts["rungs"]:
        label = f" ({r['label']})" if r["label"] else ""
        held = "" if r["fresh"] else " (same seed)"
        lines.append(f"| {r['trials']:,}{label}{held} | {r['d']} |")
    lines += ["",
              _wrap(f"{facts['flat_fresh_rungs_at_best']} fresh-seed rung(s) "
                    f"agree at the best bound, the deepest of them at "
                    f"{facts['deepest_fresh_trials']:,} trials per side. The "
                    f"submitted witness reproduces it: "
                    f"{_confidence_line(doc)}.")]
    if evidence.get("peer_audit"):
        audit = evidence["peer_audit"]
        if isinstance(audit, dict):
            detail = audit.get("decision", "")
            if audit.get("trials"):
                detail += (f" (matched depth: {int(audit['trials']):,} trials, "
                           f"seeds {audit.get('seeds', 'unrecorded')})")
        else:
            detail = str(audit)
        lines += ["", _wrap(f"Matched-depth peer audit "
                            f"(`research/audits/leader_audit.py` pair): "
                            f"{detail.strip()}")]
    if evidence.get("ladder_note"):
        lines += ["", _wrap(evidence["ladder_note"])]
    lines += ["", "## Dead ends", ""]
    lines.append(_bullets(evidence["dead_ends"]) if evidence.get("dead_ends")
                 else "None recorded for this candidate.")
    lines += ["", "## Tools", "", _wrap(_tools_paragraph(doc, evidence)),
              "", "## Reproduction", "", _wrap(evidence["reproduction"]), ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# the pull request body
# ----------------------------------------------------------------------------
def _descriptor_args(doc, evidence):
    return types.SimpleNamespace(
        construction=(doc.get("provenance") or {}).get("construction", "")
        or evidence.get("headline", ""),
        family=doc.get("family"))


def bundle_title(doc, evidence):
    """Return the PR title: ``Add [[n,k,d]] <one-line description>``.

    The description is the evidence record's headline, the same string the note
    header carries, so the title and the note cannot disagree. It falls back to
    ``cli/qldpc.py``'s own descriptor (the construction, then the family tag)
    when there is no headline or it is too long to be a title.
    """
    head = (evidence.get("headline") or "").strip(" ,.")
    if not head or len(head) > 60:
        head = cli._descriptor(_descriptor_args(doc, evidence))
    return cli.pr_title(doc["n"], doc["k"], doc["distance"]["d"], head)


def equivalence_finding(verdict, doc):
    """Return ``(ticked, text_or_reason)`` for the equivalence checklist box.

    ``cli/qldpc.py`` always emits this box unticked, and
    ``verify/check_prose.py`` rejects an unticked box as scaffolding, so a
    freshly drafted body can never pass its own pre-flight (issue #2328, R2).
    The finding is not a matter of taste: the gate's dedup already compared the
    candidate against every board entry by fingerprint and by WL signature. When
    it found nothing, that IS the answer and the box is ticked with the gate as
    its reason. When it found a WL-equivalent peer, judging the equivalence is a
    human's, and the box is only ticked once ``provenance.notes`` records the
    comparison.
    """
    dedup = (verdict.get("gates") or {}).get("dedup") or {}
    exact, wl = dedup.get("exact_duplicate_of"), dedup.get("wl_equivalent_of")
    if exact:
        return False, (f"the gate reports this code is already on the board as "
                       f"{exact}")
    notes = ((doc.get("provenance") or {}).get("notes") or "").strip()
    if wl:
        if notes:
            return True, (f"`verify/validate_candidate.py` flags the same "
                          f"Weisfeiler-Leman signature as board entry {wl}; "
                          f"`provenance.notes` records the comparison")
        return False, (f"the gate flags board entry {wl} as possibly equivalent "
                       f"(same WL signature) and `provenance.notes` says nothing "
                       f"about it; record the comparison there, or withdraw the "
                       f"candidate")
    return True, ("`verify/validate_candidate.py` found no board entry sharing "
                  "this code's fingerprint or Weisfeiler-Leman signature")


def pr_body(doc, report, verdict, evidence, facts, *, code_rel, note_rel,
            repro_rel=None, reproducible=False):
    """Render the PR body from the verified document and the gate's own verdict.

    Same sections as ``.github/pull_request_template.md`` and the same frontier
    prose as ``cli/qldpc.py`` (its ``frontier_summary`` is called directly, so
    the two cannot drift). The differences are the ones issue #2328 asks for:
    every box is decided from evidence rather than left for a human to tick, and
    the search depth behind the distance is stated where a reviewer sees it.
    """
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    comp = report.get("computed", {})
    wmax = comp.get("max_check_weight")
    track = " / ".join(x for x in (comp.get("locality_class"),
                                   comp.get("weight_class")) if x)
    stab = doc.get("code_type") == "stabilizer"
    lines = [
        "## Code submission",
        "",
        f"- Parameters: [[n, k, d]] = [[{n},{k},{d}]]",
        f"- Tracks: {track} (computed by the verifier from H and the layout)"
        + ("; general stabilizer code, ranked on the stabilizer board"
           if stab else ""),
        f"- Distance confidence: {_confidence_line(doc)}"
        + (" (Pauli weight, one side)" if stab else ""),
        f"- Search behind the claim: {facts['deepest_fresh_trials']:,} RIS "
        f"trials per side at the deepest fresh-seed rung, "
        f"{facts['flat_fresh_rungs_at_best']} fresh rung(s) flat there, "
        f"{facts['trials_spent']:,} trials over the whole ladder",
        "",
    ]
    if doc.get("family"):
        lines += [f"Family tag: {doc['family']} (a self-declared filter, never "
                  f"used for ranking).", ""]
    ticked, reason = equivalence_finding(verdict, doc)
    construction = ((doc.get("provenance") or {}).get("construction") or "").strip()
    lines += ["### Checklist",
              "- [x] One JSON file under `codes/`, conforming to "
              "`schema/code.schema.json`",
              "- [x] Distance witness(es) included for each reported side",
              f"- [x] `python verify/qldpc_verify.py {code_rel}` passes locally"]
    if construction:
        lines.append("- [x] Construction and references filled in under "
                     "`provenance`")
    if ticked:
        lines.append("- [x] If this may be equivalent to an existing entry, "
                     f"noted in `provenance.notes`: {reason}")
    lines += ["", "### What frontier does this advance?", "",
              evidence["frontier"].strip()]
    front = cli.frontier_summary(doc, report)
    if front:
        lines += [""] + front
    lines += ["",
              f"Score kd^2/n = {round(k * d * d / n, 3)}, max check weight "
              f"{wmax}, locality class {comp.get('locality_class', 'unknown')}. "
              f"Board-relative, and literature novelty is unverified: the gate "
              f"deduplicates against this board only.",
              ""]
    if construction:
        lines += [f"Construction: {construction}", ""]
    lines += [f"Research note: `{note_rel}`", ""]
    if repro_rel:
        lines += [f"Reproduction manifest: `{repro_rel}`" + (
            f"; `./qldpc reproduce {n}-{k}-{d} --construction` rebuilds the code "
            "from its recipe with `research/kit/rebuild.py` and compares "
            "fingerprints." if reproducible else
            "; its construction stage is declared not reproducible, since the "
            "recorded spec carries no constructor and params for "
            "`research/kit/rebuild.py` to run."), ""]
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# the bundle
# ----------------------------------------------------------------------------
def _git_commands(slug, title, code_rel, note_rel, body_file, base="main", extra=()):
    """Return the branch/commit/push/PR sequence for one bundle.

    Quoted with ``shlex`` because the title carries the construction string,
    which is free text and reaches a shell here. ``extra`` lists further
    files the bundle wrote (the ``repro/`` manifest).
    """
    q = shlex.quote
    return [
        f"git checkout -b submit-{slug} {base}",
        "git add " + " ".join(q(f) for f in (code_rel, note_rel, *extra)),
        f"git commit -m {q(title)}",
        f"verify/prepush_prose_check.sh {q(body_file)}",
        f"git push -u origin submit-{slug}",
        f"gh pr create --title {q(title)} --body-file {q(body_file)}",
        f"git checkout {base}",
    ]


def check_prose_cmd(root, body_file, files, pr_author=None):
    """Return the ``verify/check_prose.py`` command line for a bundle.

    ``--pr-author`` is included whenever the handle is known. CI always passes
    it and the local command in ``AGENTS.md`` does not, so a green local run
    proved nothing about the attribution gate (issue #2328, R2). Building the
    command in one place is what keeps the two the same.
    """
    cmd = [sys.executable, os.path.join(root, "verify", "check_prose.py"),
           "--root", root, "--body-file", body_file, "--files", *files]
    if pr_author:
        cmd += ["--pr-author", pr_author.lstrip("@")]
    return cmd


def _run_check_prose(root, body_file, files, pr_author=None):
    cmd = check_prose_cmd(root, body_file, files, pr_author)
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                          check=False)
    return {"ok": proc.returncode == 0, "returncode": proc.returncode,
            "output": (proc.stdout + proc.stderr).strip(),
            "command": " ".join(cmd[1:])}


def promote(candidate, evidence, *, root=_ROOT, authors=None, date=None,
            min_deep_trials=DEFAULT_MIN_DEEP_TRIALS, pr_author=None,
            body_dir=None, write=True, force=False, seed=None, base="main",
            recipe=None):
    """Build one submission bundle and return its report.

    The order is fixed and is the point: evidence, then the trusted gate on the
    final document, then the files, then ``verify/check_prose.py`` on what was
    written. A blocker stops the bundle and is reported; nothing is skipped to
    get past one.

    ``recipe`` is the screening spec the candidate was staged with
    (``load_plan`` reads it from ``<stem>.recipe.json`` beside the candidate).
    With one, the bundle also carries ``repro/<slug>.json``, written from the
    final document so its ``artifact_sha256`` is the committed file's; a spec
    without a ``{constructor, params}`` recipe gives a manifest whose
    construction stage says ``not_reproducible`` (issue #2955, item 3).
    """
    report = {"schema": REPORT_SCHEMA, "ok": False, "slug": None, "title": None,
              "branch": None, "files": {}, "body_file": None, "gates": {},
              "blocked_by": [], "needs_human": [], "commands": [],
              "ladder": None}
    blocked = report["blocked_by"]

    problems = check_evidence(evidence)
    if problems:
        blocked.extend(problems)
        return report
    if "d" not in ((candidate or {}).get("distance") or {}):
        blocked.append(
            "the candidate carries no distance block, so there is no validated "
            "witness to reuse; package it with "
            "research/kit/submit.make_submission and pass it through "
            "verify/validate_candidate.py first")
        return report
    try:
        facts = ladder_facts(evidence["ladder"], candidate["distance"]["d"])
    except (KeyError, TypeError, ValueError) as e:
        blocked.append(f"evidence.ladder is unusable: {e}")
        return report
    report["ladder"] = dict(facts)
    blocked.extend(ladder_blockers(facts, min_deep_trials))

    try:
        doc = build_doc(candidate, evidence, facts, authors=authors, date=date)
    except PromoteError as e:
        blocked.append(str(e))
        return report
    tools_model = (evidence.get("tools") or {}).get("model")
    prov_model = (candidate.get("provenance") or {}).get("model")
    if tools_model and prov_model and tools_model != prov_model:
        blocked.append(f"evidence.tools.model ({tools_model!r}) and the "
                       f"candidate's provenance.model ({prov_model!r}) "
                       f"disagree; notes/TEMPLATE.md requires them to match")
    if blocked:
        return report

    # 1. the trusted gate, on the document that will be committed.
    verdict = gate.validate_candidate(doc, seed=seed)
    report["gates"]["validate_candidate"] = verdict
    if not verdict.get("passed"):
        blocked.append("verify/validate_candidate.py did not pass this "
                       "document: " + "; ".join(verdict.get("labels") or []))
        return report
    novelty = (verdict.get("gates") or {}).get("novelty") or {}
    if novelty.get("d_only_peers") and not evidence.get("peer_audit"):
        blocked.append(
            "the gate reports a d-only gain over "
            + ", ".join(novelty["d_only_peers"])
            + "; research/AUTORESEARCH.md requires a matched-depth peer audit "
              "before packaging, and evidence.peer_audit records none")
    ticked, reason = equivalence_finding(verdict, doc)
    if not ticked:
        blocked.append(reason)
    if blocked:
        return report

    slug = candidate_slug(doc)
    report["slug"] = slug
    report["branch"] = f"submit-{slug}"
    code_rel = os.path.join("codes", f"{slug}.json")
    note_rel = os.path.join("notes", f"{slug}.md")
    code_path, note_path = os.path.join(root, code_rel), os.path.join(root, note_rel)
    repro_rel = os.path.join("repro", f"{slug}.json") if recipe is not None else None
    written = [(code_path, code_rel), (note_path, note_rel)]
    if repro_rel:
        written.append((os.path.join(root, repro_rel), repro_rel))
    if not force:
        for p, rel in written:
            if os.path.exists(p):
                blocked.append(f"{rel} already exists; pass force=True to "
                               f"overwrite or pick another candidate")
    if blocked:
        return report

    # 2. the files, from the validated document and the evidence record.
    report_verify = qldpc_verify.verify(doc, refute=False)
    note_md = note_markdown(doc, evidence, facts)
    if len(note_md.encode()) > NOTE_CAP_BYTES:
        blocked.append(f"{note_rel} is {len(note_md.encode())} bytes, over the "
                       f"{NOTE_CAP_BYTES}-byte note cap; trim the evidence record")
        return report
    body = pr_body(doc, report_verify, verdict, evidence, facts,
                   code_rel=code_rel, note_rel=note_rel, repro_rel=repro_rel,
                   reproducible=recipe_from_spec(recipe) is not None)
    report["title"] = bundle_title(doc, evidence)
    report["files"] = {"code": code_rel, "note": note_rel}
    if repro_rel:
        report["files"]["repro"] = repro_rel

    body_dir = body_dir or os.path.join(root, "research", "candidates")
    body_file = os.path.join(body_dir, f"pr-body-{slug}.md")
    if write:
        os.makedirs(os.path.dirname(code_path), exist_ok=True)
        os.makedirs(os.path.dirname(note_path), exist_ok=True)
        os.makedirs(body_dir, exist_ok=True)
        with open(code_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(doc, f, indent=1)
            f.write("\n")
        with open(note_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(note_md)
        if repro_rel:
            write_repro_manifest(doc, slug, recipe,
                                 repro_dir=os.path.join(root, "repro"),
                                 artifact_path=code_path)
        with open(body_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        report["body_file"] = body_file
        # 3. the prose gate, on what is actually on disk.
        prose = _run_check_prose(root, body_file,
                                 [rel for _, rel in written],
                                 pr_author=pr_author)
        report["gates"]["check_prose"] = prose
        if not prose["ok"]:
            blocked.append("verify/check_prose.py rejected the bundle; its "
                           "output is in gates.check_prose.output")
    else:
        report["note_markdown"], report["body_markdown"] = note_md, body
        report["gates"]["check_prose"] = {
            "ok": None,
            "skipped": "dry run: nothing was written for the checker to read"}

    report["needs_human"] = needs_human(doc, verdict, body_file if write else None)
    report["commands"] = _git_commands(slug, report["title"], code_rel, note_rel,
                                       body_file, base=base,
                                       extra=[repro_rel] if repro_rel else ())
    report["ok"] = not blocked
    return report


def needs_human(doc, verdict, body_file):
    """List what this bundle still needs a person for, and why."""
    items = [{"item": "literature novelty",
              "why": "the gate deduplicates against this board only and labels "
                     "literature novelty unverified; nothing here checks the "
                     "wider literature"},
             {"item": "the frontier claim in the PR body",
              "why": "it is board-relative and was supplied as evidence, not "
                     "derived; read it against the board before requesting "
                     "review"},
             {"item": "opening the PR",
              "why": "publication authorization is the contributor's per "
                     "AGENTS.md; this module writes files and never runs git "
                     "or gh"}]
    wl = ((verdict.get("gates") or {}).get("dedup") or {}).get("wl_equivalent_of")
    if wl:
        items.append({"item": f"the equivalence comparison against {wl}",
                      "why": "the gate found the same Weisfeiler-Leman "
                             "signature; provenance.notes records a judgment "
                             "that only a person can make"})
    if doc.get("code_type", "CSS") == "CSS" and "circuit" not in doc:
        items.append({"item": "the circuit tier",
                      "why": "this module does not generate memory circuits; "
                             "./qldpc submit does, and d_circ is penalty-only, "
                             "so the entry is submitted without one"})
    if body_file:
        items.append({"item": "the clean-worktree prose gate",
                      "why": f"verify/prepush_prose_check.sh {body_file} runs "
                             f"against committed content and refuses a dirty "
                             f"tree, so it can only run after the commit; it "
                             f"is in commands"})
    return items


def promote_all(plans, **kwargs):
    """Promote each ``(candidate, evidence[, recipe])`` plan and return the reports."""
    out = []
    for plan in plans:
        cand, ev, *rest = plan
        out.append(promote(cand, ev, recipe=rest[0] if rest else None, **kwargs))
    return out


def script_for(reports, *, shell="#!/bin/sh\nset -eu\n"):
    """Render the command sequence for every ready bundle as one runnable script."""
    out = [shell,
           "# Generated by research/kit/promote.py. One code per branch and per",
           "# PR, as verify/check_submission_scope.py requires. Review each body",
           "# before running this.", ""]
    for rep in reports:
        if not rep.get("ok") or not rep.get("body_file"):
            out.append(f"# skipped {rep.get('slug') or 'candidate'}: "
                       + "; ".join(rep.get("blocked_by") or ["not ready"]))
            continue
        out.append(f"# {rep['title']}")
        out.extend(rep["commands"])
        out.append("")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="promote",
        description="assemble submission bundles for validated candidates")
    ap.add_argument("plans", nargs="+", help="plan file(s): {candidate, evidence}")
    ap.add_argument("--root", default=_ROOT)
    ap.add_argument("--authors", nargs="*", default=None,
                    help="override provenance.authors (@handle and/or 'First Last')")
    ap.add_argument("--pr-author", default=None,
                    help="GitHub login the PR will be opened by; passed to "
                         "check_prose.py exactly as CI passes it")
    ap.add_argument("--date", default=None)
    ap.add_argument("--min-deep-trials", type=int, default=DEFAULT_MIN_DEEP_TRIALS)
    ap.add_argument("--seed", type=int, default=None,
                    help="seed for the trusted gate (default: fresh and random)")
    ap.add_argument("--base", default="main")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing codes/<slug>.json or note")
    ap.add_argument("--dry-run", action="store_true",
                    help="render and gate without writing any file")
    ap.add_argument("--json", default=None, metavar="FILE",
                    help="write the reports here as well as to stdout")
    ap.add_argument("--script", default=None, metavar="FILE",
                    help="write the branch/commit/push/PR commands here")
    args = ap.parse_args(argv)

    plans = []
    for path in args.plans:
        plans.extend(load_plan(path))
    reports = promote_all(plans, root=os.path.abspath(args.root),
                          authors=args.authors, date=args.date,
                          min_deep_trials=args.min_deep_trials,
                          pr_author=args.pr_author, write=not args.dry_run,
                          force=args.force, seed=args.seed, base=args.base)
    text = json.dumps(reports, indent=1)
    print(text)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    if args.script:
        with open(args.script, "w", encoding="utf-8", newline="\n") as f:
            f.write(script_for(reports))
        os.chmod(args.script, 0o755)
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())

"""Campaign definitions: bounded, reproducible search tasks (issue #2219).

A campaign is the INPUT to the autoresearch loop, not a replacement for it and
not a submission mechanism. It says what to look for, where to look, how much
may be spent and when to stop, so that two executors handed the same file are
running the same task and their results can be compared. What comes out is a
ledger and a summary; what does or does not reach the board is still decided by
``verify/validate_candidate.py`` and then by a human.

Two invariants this module will not let a caller break, because both have cost
the board real entries before:

* **Constraints filter a search, they never make a claim.** ``constraints``
  narrows where to look. Which track cell a finished code lands in is computed
  by the verifier from ``(H_X, H_Z)`` and the layout. :meth:`Campaign.in_scope`
  is therefore named for what it does, and its result never reaches a document.
* **A survivor is a validated survivor.** :meth:`Ledger.record_candidate`
  refuses anything whose verdict does not carry ``passed: true``, and
  :meth:`Ledger.best_score` reads the objective off the recorded survivors, so
  neither a summary nor a stopping condition can report a find, or a target
  reached, that the gate did not accept.

    from campaign import load_campaign, Ledger
    c = load_campaign("research/campaigns/<id>/campaign.json")
    led = Ledger(c)
    led.start_experiment("lifted-product", seed=7)
    led.spend(cpu_hours=1.5, candidates_screened=250)
    led.record_candidate(doc, verdict)          # only if verdict["passed"]
    led.end_experiment()
    if led.stop_reason():                        # which condition fired
        json.dump(led.summary(), open(out, "w"), indent=2)
"""
import hashlib
import json
import os
import string
import subprocess
import time
from datetime import datetime, timezone

try:
    import jsonschema
except ImportError:                              # pragma: no cover
    jsonschema = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
SCHEMA_PATH = os.path.join(_ROOT, "schema", "campaign.schema.json")
SUMMARY_SCHEMA_PATH = os.path.join(_ROOT, "schema",
                                   "campaign_summary.schema.json")
SUMMARY_VERSION = 1
JOURNAL_VERSION = 1
CONTRACT_VERSION = 1
MANIFEST_VERSION = 1

# What a manifest will carry verbatim from a log. A claim that rests on a
# witness or a trial count needs the lines that produced it, and *.log is
# gitignored, so the excerpt is promoted into the manifest rather than cited
# where no reviewer can open it.
MAX_LOG_EXCERPT = 16384

# The metrics :meth:`Campaign.score` computes from a survivor's (n, k, d), and
# therefore the only ones a target_reached condition can ever fire on.
SCORABLE_METRICS = ("kd2_over_n", "distance", "logical_qubits")


class CampaignError(ValueError):
    """A campaign definition that cannot be run as written."""


def placeholders(template):
    """List the {name} fields in an invocation template, in order."""
    return [f for _, f, _, _ in string.Formatter().parse(template) if f]


def contract_hash(run_contract):
    """Hash a run contract so two runs can be compared in one field.

    The point of the contract is that "these two lanes screened at the same
    depth" is a string comparison on the committed summary rather than a
    reconstruction from two shell histories. Keyed on the template and the
    resolved parameters together, since either one changing changes what ran.
    """
    if not run_contract:
        return None
    blob = json.dumps({"v": CONTRACT_VERSION,
                       "template": run_contract["template"],
                       "parameters": run_contract["parameters"]},
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _git(root, *args):
    """Run one git command under ``root``; None if git or the repo is absent."""
    try:
        out = subprocess.run(("git", "-C", root) + args, capture_output=True,
                             text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):       # pragma: no cover
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def repo_snapshot(root=_ROOT):
    """Identify the code a run executed, precisely enough to get it back.

    ``head`` alone is not that identification. A campaign is usually run from
    a tree with edits in it, which is the normal way a search gets tuned, and
    two runs from the same commit with different edits produce different
    numbers. So the working-tree diff against HEAD is hashed alongside, and
    ``dirty`` says plainly whether there was one. A reviewer who wants the
    exact code checks out ``head`` and asks the runner for the diff; a
    reviewer who only wants to know whether two runs used the same code
    compares the pair.

    Everything is best-effort: a run outside a checkout still gets a manifest,
    with the fields it cannot fill set to None, because a manifest that
    refuses to be written teaches a runner to skip manifests.
    """
    head = _git(root, "rev-parse", "HEAD")
    if head is None:
        return {"head": None, "branch": None, "dirty": None,
                "diff_sha256": None,
                "note": "not a git checkout, or git unavailable"}
    diff = _git(root, "diff", "HEAD") or ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    return {
        "head": head,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(diff),
        "diff_sha256": hashlib.sha256(diff.encode()).hexdigest() if diff
                       else None,
        "untracked_count": len([x for x in untracked.splitlines() if x]),
    }


def read_log_excerpt(path, *, limit=MAX_LOG_EXCERPT):
    """Read a log tail for promotion into a manifest.

    ``*.log`` is gitignored, so a note claiming "5.3M trials" or quoting a
    ladder trace points at a file no reviewer can open. Promoting the lines
    the claim rests on into the committed manifest is the cheap half of
    fixing that: it does not preserve the whole run, it preserves the
    evidence for what was written down.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as e:
        return {"path": path, "error": str(e)}
    body = text[-limit:]
    return {"path": path,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "bytes": len(text.encode()),
            "truncated": len(body) < len(text),
            "excerpt": body}


def _schema(path=SCHEMA_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# The outcomes an experiment row may record, and the ones that say anything
# about whether the screen ranked the member correctly. A duplicate or a
# dominated code is a fact about the board, not about the screen, so it is
# carried on the row and left out of the correlation. held is the refutation
# pass's outcome: the claim survived at the recorded depth.
VERDICTS = ("passed", "refuted", "held", "duplicate", "dominated", "not_run")
RANKING_VERDICTS = {"passed": 1, "held": 1, "refuted": 0}

# How a candidate was arrived at. The kit's samplers are rejection sampling
# with no memory between candidates, so anything driven by search.py is
# novel_generation unless its caller says otherwise.
MODES = ("novel_generation", "cross_pollination", "refinement", "repair",
         "enumeration", "hand_built")


def validate_summary(obj):
    """Validate a campaign summary against schema/campaign_summary.schema.json.

    Separate from :func:`validate_campaign` because the two documents answer
    different questions: the campaign file is what may be spent, the summary
    is what was. A summary that does not validate is a reporting bug and not
    a verdict bug, so this raises rather than warns and nothing downstream
    treats a summary as authoritative either way.
    """
    if jsonschema is None:                       # pragma: no cover
        raise CampaignError("jsonschema is required to validate a summary")
    try:
        jsonschema.Draft202012Validator(
            _schema(SUMMARY_SCHEMA_PATH)).validate(obj)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise CampaignError(f"{where}: {e.message}") from None


def spearman(xs, ys):
    """Spearman rank correlation, ties averaged; None when it is undefined.

    Undefined rather than zero when either side is constant: a screen whose
    readings are all equal, or a lane whose verdicts are all the same, has
    produced no evidence about ordering, and reporting 0.0 there would read
    as "the screen is uninformative" when the truth is "nothing was tested".
    """
    if len(xs) != len(ys) or len(xs) < 2:
        return None

    def ranks(vs):
        order = sorted(range(len(vs)), key=lambda i: vs[i])
        out = [0.0] * len(vs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            shared = (i + j) / 2 + 1
            for t in range(i, j + 1):
                out[order[t]] = shared
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def validate_campaign(obj):
    """Validate a campaign object against the schema; raise CampaignError.

    The schema does the structural work (unknown fields, malformed budgets,
    unknown stopping types, unknown family tags). What is checked here is the
    handful of things JSON Schema cannot say about one field in terms of
    another.
    """
    if jsonschema is None:                       # pragma: no cover
        raise CampaignError("jsonschema is required to validate a campaign")
    try:
        jsonschema.Draft202012Validator(_schema()).validate(obj)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise CampaignError(f"{where}: {e.message}") from None

    c = obj["campaign"]
    for field in ("n", "k"):
        rng = (c.get("constraints") or {}).get(field)
        if rng and rng[0] > rng[1]:
            raise CampaignError(
                f"constraints.{field}: [{rng[0]}, {rng[1]}] is empty; the low "
                "bound is above the high one")
    rc = c.get("run_contract")
    if rc is not None:
        holes = set(placeholders(rc["template"]))
        given = set(rc["parameters"])
        if holes - given:
            raise CampaignError(
                "run_contract: template uses "
                f"{', '.join(sorted(holes - given))} with no value in "
                "parameters, so the recorded invocation is not resolvable")
        if given - holes:
            raise CampaignError(
                "run_contract: parameters declares "
                f"{', '.join(sorted(given - holes))} which the template "
                "never uses, so the recorded depth is not the depth that ran")
    for cond in c["stopping"]:
        if cond["type"] == "candidates_found" and not cond.get("count"):
            raise CampaignError(
                "stopping candidates_found: needs a count, otherwise nothing "
                "says how many survivors is enough")
        if cond["type"] == "no_progress" and not cond.get("experiments"):
            raise CampaignError(
                "stopping no_progress: needs experiments, otherwise nothing "
                "says how long a dry spell has to be")
        if cond["type"] == "target_reached":
            if "target" not in c["objective"]:
                raise CampaignError(
                    "stopping target_reached: objective.target is not set, so "
                    "there is no target to reach")
            metric = c["objective"]["metric"]
            if metric not in SCORABLE_METRICS:
                raise CampaignError(
                    f"stopping target_reached: objective.metric {metric!r} is "
                    "not computed from a survivor's (n, k, d), so the "
                    "condition could never fire; use one of "
                    f"{', '.join(SCORABLE_METRICS)}")
    return obj


def load_campaign(path):
    """Load and validate a campaign definition from disk."""
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except json.JSONDecodeError as e:
        raise CampaignError(f"{path}: not valid JSON ({e})") from None
    camp = Campaign(validate_campaign(obj), path=path)
    home = os.path.dirname(os.path.abspath(path))
    if os.path.basename(os.path.dirname(home)) == "campaigns" \
            and os.path.basename(home) != camp.id:
        raise CampaignError(
            f"{path}: campaign id {camp.id!r} is not the directory name "
            f"{os.path.basename(home)!r}; a copied definition would file its "
            "ledger under the campaign it was copied from")
    return camp


class Campaign:
    """A validated campaign definition."""

    def __init__(self, obj, path=None):
        self.obj = obj
        self.path = path
        self.c = obj["campaign"]

    # -- identity ---------------------------------------------------------
    @property
    def id(self):
        return self.c["id"]

    @property
    def name(self):
        return self.c["name"]

    @property
    def status(self):
        return self.c.get("status", "draft")

    @property
    def run_contract(self):
        """The declared invocation, or None when the campaign does not fix one."""
        return self.c.get("run_contract")

    @property
    def contract_hash(self):
        """Short hash of this campaign's run contract, or None."""
        return contract_hash(self.run_contract)

    def resolved_params(self, **overrides):
        """Merge argv overrides onto the contract, and say which ones deviate.

        Returns ``(params, deviations)``. The contract supplies the values;
        an explicit override is applied, because a campaign file that cannot
        be departed from is a campaign file people stop passing, but it is
        returned separately so the experiment row records the departure. An
        override equal to the contract value is not a deviation.
        """
        base = dict((self.run_contract or {}).get("parameters") or {})
        deviations = {}
        for key, value in overrides.items():
            if value is None:
                continue
            if key in base and base[key] != value:
                deviations[key] = {"contract": base[key], "used": value}
            base[key] = value
        return base, deviations

    @property
    def families(self):
        return list((self.c.get("methods") or {}).get("families") or [])

    @property
    def required_outputs(self):
        return list(self.c.get("required_outputs") or [])

    # -- the search space -------------------------------------------------
    def in_scope(self, *, n=None, k=None, d=None, w=None, locality=None):
        """Report whether a candidate is inside the campaign search space.

        A screening filter, and only that. It answers "is this worth spending
        the next rung on", never "which cell does this belong to": the cell is
        the verifier's to compute, from the matrices and the layout.
        """
        con = self.c.get("constraints") or {}
        if n is not None and con.get("n") and not con["n"][0] <= n <= con["n"][1]:
            return False
        if k is not None and con.get("k") and not con["k"][0] <= k <= con["k"][1]:
            return False
        if d is not None and con.get("min_distance") and d < con["min_distance"]:
            return False
        if w is not None and con.get("max_check_weight") \
                and w > con["max_check_weight"]:
            return False
        if locality is not None and con.get("locality"):
            want, order = con["locality"], ("local-2d-single",
                                            "local-2d-bilayer", "unrestricted")
            if locality not in order:
                raise CampaignError(
                    f"unknown locality class {locality!r}; the schema's "
                    f"classes are {', '.join(order)}")
            # the classes nest: a single-layer code satisfies a bilayer ask
            if order.index(locality) > order.index(want):
                return False
        return True

    def score(self, *, n, k, d, geo=None):
        """Compute the objective metric for a candidate, or None."""
        metric = self.c["objective"]["metric"]
        if metric == "kd2_over_n":
            return k * d * d / n
        if metric == "geometric_efficiency":
            return geo
        if metric == "distance":
            return d
        if metric == "logical_qubits":
            return k
        return None


BUDGET_FIELDS = ("cpu_hours", "gpu_hours", "walltime_hours",
                 "candidates_screened")


class Ledger:
    """The running record of one campaign: what was spent, tried and found.

    It is the committed half of the evidence trail, so it names only things a
    reviewer can open: staged candidates live in the gitignored
    ``research/candidates/`` and are recorded by their parameters and verdict,
    never cited as files.

    Pass ``journal=<path>`` and each experiment is appended to a JSONL file as
    it closes, so a kill costs the current experiment rather than the run.
    :meth:`from_journal` reads one back, and :meth:`merge` folds two ledgers of
    the same campaign into one. That last part is what turns "two executors
    handed the same file" from a human comparison exercise into a campaign
    several sessions can run between them.

    One journal per executor. Two processes appending to the same file would
    interleave partial lines once a record outgrows the atomic write size, and
    separate files merge cleanly anyway.
    """

    def __init__(self, campaign, *, journal=None, manifest=None, params=None):
        self.campaign = campaign
        self.journal = journal
        self.manifest_path = manifest
        # Resolved run parameters: trials, ladder depth, seeds, workers, and
        # whatever else the executor actually invoked with. Recorded as given
        # rather than re-derived, because the point is what ran, not what the
        # campaign file asked for.
        self.params = dict(params or {})
        self.snapshot = repo_snapshot()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.log_excerpts = []
        self.spent = dict.fromkeys(BUDGET_FIELDS, 0)
        self._t0 = time.monotonic()
        self._walltime_base = 0.0
        self.experiments = []
        self.survivors = []
        self.negative_results = []
        self.frontier_advances = 0
        self._current = None
        self._exp_t0 = None
        self._mark = (0, 0)
        self._dry_streak = 0

    # -- experiments ------------------------------------------------------
    def start_experiment(self, family, *, seed=None, note="", mode=None,
                         params=None, **overrides):
        """Begin one run: a family, a budget slice, a seed, and its depth.

        Any further keyword is an argv-style override of the campaign's run
        contract. The resolved parameters and the contract hash are stamped
        on the experiment row, so the depth a lane ran at is readable off
        the committed summary rather than reconstructed from a shell
        history, and an override is recorded as a deviation rather than
        silently applied.
        """
        if family not in self.campaign.families and self.campaign.families:
            raise CampaignError(
                f"family {family!r} is not one of this campaign's families "
                f"({', '.join(self.campaign.families)})")
        if mode is not None and mode not in MODES:
            raise CampaignError(
                f"mode {mode!r} is not one of {', '.join(MODES)}")
        resolved, deviations = self.campaign.resolved_params(**overrides)
        # The construction parameters that identify this family member sit
        # beside the resolved run parameters, because a later session matches
        # on both: "was this member screened" and "at what depth".
        resolved.update(params or {})
        self._current = {"family": family, "seed": seed, "note": note,
                         "spent": dict.fromkeys(BUDGET_FIELDS, 0),
                         "survivors": 0}
        if mode is not None:
            self._current["mode"] = mode
        if self.campaign.run_contract or resolved:
            self._current["params"] = resolved
            self._current["contract_hash"] = self.campaign.contract_hash
        if deviations:
            self._current["contract_deviations"] = deviations
        self._exp_t0 = time.monotonic()
        self._mark = (len(self.survivors), len(self.negative_results))
        return self._current

    def record_screen(self, *, trials, d=None, backend=None, rung=None):
        """Record what the cheap screen read on the open experiment.

        ``d`` is the lightest logical weight the screen found, which is an
        upper bound and never a claim: the gate is the only thing that
        decides. ``trials`` is required because the reading is meaningless
        without the depth it was read at, and ``backend`` because NumPy
        iterations and fast-RIS samples are not comparable budgets
        (AUTORESEARCH.md section 3), so the count alone does not identify
        the depth.
        """
        if self._current is None:
            raise CampaignError("record_screen without start_experiment")
        if int(trials) < 1:
            raise CampaignError("record_screen: trials must be at least 1")
        screened = {"trials": int(trials), "d": None if d is None else int(d)}
        if backend is not None:
            screened["backend"] = backend
        if rung is not None:
            screened["rung"] = int(rung)
        self._current["screened"] = screened
        return screened

    def record_verdict(self, verdict):
        """Record what the gate said about the open experiment's member.

        ``not_run`` is the ordinary case and the one worth recording: it
        says the member was screened and discarded before the gate, which is
        what stops the next session paying for it again.
        """
        if self._current is None:
            raise CampaignError("record_verdict without start_experiment")
        if verdict not in VERDICTS:
            raise CampaignError(
                f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
        self._current["verdict"] = verdict
        return verdict

    def screen_quality(self):
        """Per family, how well the screen's ordering matched the gate's.

        Over the rows that carry both a screened distance and a gate verdict
        that says something about ordering (passed or refuted). Reported with
        the pair count beside it: a correlation over three rows is noise, and
        folding the two into one number would hide that.
        """
        by_family = {}
        for exp in self.experiments:
            d = (exp.get("screened") or {}).get("d")
            rank = RANKING_VERDICTS.get(exp.get("verdict"))
            if d is None or rank is None:
                continue
            by_family.setdefault(exp["family"], ([], []))
            xs, ys = by_family[exp["family"]]
            xs.append(d)
            ys.append(rank)
        out = []
        for family in sorted(by_family):
            xs, ys = by_family[family]
            row = {"family": family, "pairs": len(xs),
                   "spearman": spearman(xs, ys)}
            if row["spearman"] is None:
                row["note"] = ("undefined: the rows carry no spread in the "
                               "screen or in the verdict")
            out.append(row)
        return out

    def end_experiment(self):
        """Close the current run, fold it into the ledger, and journal it.

        The experiment's own wall time is measured here rather than reported,
        for the same reason the campaign's is: it is the only number a merged
        or replayed ledger can add up, and a cap nothing observes is advisory.
        """
        if self._current is None:
            raise CampaignError("end_experiment without start_experiment")
        exp = self._current
        elapsed = (time.monotonic() - self._exp_t0) / 3600
        exp["spent"]["walltime_hours"] = max(exp["spent"]["walltime_hours"],
                                             elapsed)
        self.experiments.append(exp)
        self._dry_streak = 0 if exp["survivors"] else self._dry_streak + 1
        si, ni = self._mark
        self._append_journal(exp, self.survivors[si:],
                             self.negative_results[ni:])
        self._current = None
        self._exp_t0 = None
        # The boundary is where a manifest is worth writing: it is the point
        # at which the numbers a note would quote become final, and a run
        # killed after it still leaves a manifest covering what closed.
        if self.manifest_path:
            write_manifest(self.manifest(), self.manifest_path)
        return exp

    # -- the journal ------------------------------------------------------
    def _append_journal(self, exp, survivors, negatives):
        """Append one experiment and what it produced, then force it to disk."""
        if not self.journal:
            return None
        record = {"record_version": JOURNAL_VERSION,
                  "campaign_id": self.campaign.id,
                  "recorded_at": datetime.now(timezone.utc).isoformat(),
                  "experiment": exp,
                  "survivors": list(survivors),
                  "negative_results": list(negatives)}
        parent = os.path.dirname(os.path.abspath(self.journal))
        os.makedirs(parent, exist_ok=True)
        with open(self.journal, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return self.journal

    @classmethod
    def from_journal(cls, campaign, path):
        """Rebuild a ledger from one journal, or several merged.

        What a journal cannot restore is spend recorded outside any
        experiment, since nothing closes to carry it, and the in-flight
        experiment the kill interrupted. Everything that closed is here.
        """
        paths = [path] if isinstance(path, (str, os.PathLike)) else list(path)
        if not paths:
            raise CampaignError("from_journal: no journal given")
        out = None
        for one in paths:
            led = cls(campaign)
            led._replay(one)
            out = led if out is None else out.merge(led)
        return out

    def _replay(self, path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if i == len(lines) - 1:
                    break                        # the tail a kill truncated
                raise CampaignError(
                    f"{path}: line {i + 1} is not valid JSON, and it is not "
                    "the last line, so this is corruption rather than an "
                    "interrupted write") from None
            if rec.get("campaign_id") != self.campaign.id:
                raise CampaignError(
                    f"{path}: journal is for campaign "
                    f"{rec.get('campaign_id')!r}, not {self.campaign.id!r}")
            exp = rec.get("experiment") or {}
            exp.setdefault("spent", dict.fromkeys(BUDGET_FIELDS, 0))
            self.experiments.append(exp)
            self.survivors.extend(rec.get("survivors") or [])
            self.negative_results.extend(rec.get("negative_results") or [])
        self.spent = {f: sum(e["spent"].get(f, 0) for e in self.experiments)
                      for f in BUDGET_FIELDS}
        self._recount()
        return self

    def merge(self, other):
        """Fold another executor's ledger for the same campaign into a new one.

        Experiments are keyed by ``(family, seed)``: the same family at the
        same seed is the same deterministic work, so it is counted once and
        its budget is not charged twice. An experiment with no seed cannot be
        told apart from another, so both copies are kept; that over-counts the
        budget rather than silently discarding work someone paid for.

        Survivors are unioned on the verifier's fingerprint, so one code found
        by two executors is one survivor rather than two. Wall time is the sum
        of the merged experiments' own measured wall times, because two
        executors that ran in parallel each consumed theirs. Neither input
        ledger is modified.
        """
        if other.campaign.id != self.campaign.id:
            raise CampaignError(
                f"merge: {other.campaign.id!r} is a different campaign from "
                f"{self.campaign.id!r}; their budgets and objectives are not "
                "the same task and adding them up would say nothing")
        out = Ledger(self.campaign)
        seen, dropped = set(), []
        for src in (self, other):
            for exp in src.experiments:
                key = (exp.get("family"), exp.get("seed"))
                if exp.get("seed") is not None and key in seen:
                    dropped.append(exp)
                    continue
                seen.add(key)
                out.experiments.append(exp)
        out.spent = {f: self.spent.get(f, 0) + other.spent.get(f, 0)
                     - sum(d["spent"].get(f, 0) for d in dropped)
                     for f in BUDGET_FIELDS}
        keys = set()
        for src in (self, other):
            for row in src.survivors:
                key = row.get("fingerprint") or (
                    row.get("n"), row.get("k"), row.get("d"),
                    tuple(row.get("cell") or ()))
                if key in keys:
                    continue
                keys.add(key)
                out.survivors.append(row)
        for src in (self, other):
            for neg in src.negative_results:
                if neg not in out.negative_results:
                    out.negative_results.append(neg)
        out._recount()
        return out

    def _recount(self):
        """Recompute the derived counters from the rows now held."""
        self.frontier_advances = sum(1 for r in self.survivors
                                     if r.get("advanced_frontier"))
        self._walltime_base = sum(e.get("spent", {}).get("walltime_hours", 0)
                                  for e in self.experiments)
        streak = 0
        for exp in reversed(self.experiments):
            if exp.get("survivors"):
                break
            streak += 1
        self._dry_streak = streak

    def spend(self, **amounts):
        """Record consumption against the budget."""
        for field, amount in amounts.items():
            if field not in BUDGET_FIELDS:
                raise CampaignError(f"unknown budget field {field!r}")
            if amount < 0:
                raise CampaignError(f"{field}: cannot spend a negative amount")
            self.spent[field] += amount
            if self._current is not None:
                self._current["spent"][field] += amount

    def record_candidate(self, doc, verdict, *, advanced_frontier=None):
        """Record a validated survivor.

        ``verdict`` is what ``validate_candidate`` returned. Anything without
        ``passed: true`` is refused rather than recorded, so no summary can
        report a find the gate did not accept.
        """
        if not (verdict or {}).get("passed"):
            raise CampaignError(
                "record_candidate: the verdict does not say passed: true. A "
                "candidate is not a find until the gate accepts it")
        if self._current is None:
            raise CampaignError(
                "record_candidate without start_experiment: a survivor no "
                "experiment accounts for leaves the ledger contradicting "
                "itself about what the budget bought")
        gates = verdict.get("gates") or {}
        novelty = gates.get("novelty") or {}
        if advanced_frontier is None:
            advanced_frontier = bool(novelty.get("board_advancing"))
        row = {
            "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"],
            # the weight class the verifier computed; the gate does not put a
            # raw max check weight in its verdict
            "weight_class": (verdict.get("candidate") or {}).get("weight_class")
                            or (gates.get("verify") or {}).get("weight_class"),
            "cell": novelty.get("cell"),
            "board_advancing": novelty.get("board_advancing"),
            "fingerprint": (verdict.get("candidate") or {}).get("fingerprint"),
            "advanced_frontier": bool(advanced_frontier),
            "labels": list(verdict.get("labels") or []),
        }
        self.survivors.append(row)
        self._current["survivors"] += 1
        if advanced_frontier:
            self.frontier_advances += 1
        return row

    def record_negative(self, what, detail):
        """Record something that did not work, and why.

        A closed family, a wall, a ladder that collapsed. This is the half of a
        campaign that survives a zero-submission run, and the next searcher
        pays for it twice if it is not written down.
        """
        self.negative_results.append({"what": what, "detail": detail})

    # -- stopping ---------------------------------------------------------
    def consumed(self):
        """Report what has been spent, with wall time read off the clock.

        ``walltime_hours`` is measured rather than reported: a cap nothing
        observes is advisory, and the budget object exists to be enforceable.
        """
        out = dict(self.spent)
        measured = self._walltime_base + (time.monotonic() - self._t0) / 3600
        out["walltime_hours"] = max(out["walltime_hours"], measured)
        return out

    def budget_exhausted(self):
        """Name the first budget field that has been reached, or None."""
        budget, spent = self.campaign.c["budget"], self.consumed()
        for field, cap in budget.items():
            if spent.get(field, 0) >= cap:
                return field
        return None

    def best_score(self):
        """Return the best objective over the validated survivors, or None.

        Read off the recorded survivor rows and nowhere else, so a stopping
        condition on the objective cannot fire on a screening number for a
        candidate the gate went on to refuse.
        """
        scores = [s for s in (self.campaign.score(n=r["n"], k=r["k"], d=r["d"])
                              for r in self.survivors) if s is not None]
        if not scores:
            return None
        up = self.campaign.c["objective"]["direction"] == "maximize"
        return max(scores) if up else min(scores)

    def stop_reason(self):
        """Which stopping condition has fired, as (type, detail), or None."""
        for cond in self.campaign.c["stopping"]:
            kind = cond["type"]
            if kind == "budget_exhausted":
                field = self.budget_exhausted()
                if field:
                    cap = self.campaign.c["budget"][field]
                    spent = self.consumed()[field]
                    return kind, f"{field} reached {spent:g} of {cap:g}"
            elif kind == "frontier_advance" and self.frontier_advances:
                return kind, f"{self.frontier_advances} validated frontier advance(s)"
            elif kind == "candidates_found" and len(self.survivors) >= cond["count"]:
                return kind, f"{len(self.survivors)} validated survivors"
            elif kind == "no_progress" and self._dry_streak >= cond["experiments"]:
                return kind, f"{self._dry_streak} experiments with no survivor"
            elif kind == "target_reached":
                best = self.best_score()
                if best is None:
                    continue
                target = self.campaign.c["objective"]["target"]
                up = self.campaign.c["objective"]["direction"] == "maximize"
                if (best >= target) if up else (best <= target):
                    return kind, f"objective reached {best:g} against {target:g}"
        return None

    # -- provenance -------------------------------------------------------
    def attach_log(self, path, *, why=""):
        """Promote a log, or its tail, into the manifest.

        Call it for the log a written claim rests on, and say in ``why``
        which claim. An excerpt nobody can connect to an assertion is
        weight without evidence.
        """
        rec = read_log_excerpt(path)
        rec["why"] = why
        self.log_excerpts.append(rec)
        return rec

    def manifest(self):
        """Build the citable record of what this run was and what it ran on.

        ``summary.json`` says what a campaign found. This says what produced
        it: the code snapshot, the parameters actually invoked, the seeds,
        the spend, and the gate verdict fingerprints of every survivor. The
        two are separate files because they answer to different readers. A
        reviewer checking a claim needs this one, and it has to be committed
        next to the note for that to be worth anything.

        Verdicts are fingerprinted rather than copied: the full verdict lives
        in the summary's survivor rows, and what the manifest owes is enough
        to detect a survivor whose verdict changed between the run and the
        PR.
        """
        return {
            "manifest_version": MANIFEST_VERSION,
            "campaign_id": self.campaign.id,
            "started_at": self.started_at,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": self.snapshot,
            "params": self.params,
            "seeds": [e.get("seed") for e in self.experiments
                      if e.get("seed") is not None],
            "experiments": len(self.experiments),
            "consumed": {f: round(v, 3) for f, v in self.consumed().items()
                         if v},
            # Dead ends travel with the run, not only with the summary. A
            # stage-only run that is never promoted writes no note, and
            # AUTORESEARCH.md counts collapsed ladders and closed routes as
            # required content, so the manifest has to carry them or they are
            # lost with the staging directory.
            "negative_results": list(self.negative_results),
            "survivor_verdicts": [
                {"n": s.get("n"), "k": s.get("k"), "d": s.get("d"),
                 "fingerprint": _verdict_fingerprint(s)}
                for s in self.survivors],
            "logs": self.log_excerpts,
            "authority": "this manifest records what ran; what a run is "
                         "allowed to claim is still decided by "
                         "verify/validate_candidate.py",
        }

    # -- output -----------------------------------------------------------
    def summary(self, *, status=None, report=None):
        """Build the machine-readable campaign summary.

        Written beside the definition when a campaign ends. Zero survivors is a
        complete, reportable outcome: the ledger and the negative results are
        the finding in that case. ``status`` defaults to what happened, so an
        interrupted run does not file itself as completed.
        """
        fired = self.stop_reason()
        budget = self.campaign.c["budget"]
        spent = self.consumed()
        shown = [f for f in BUDGET_FIELDS if spent[f] and
                 (f != "walltime_hours" or f in budget)]
        if status is None:
            status = "completed" if fired else "paused"
        return {
            "summary_version": SUMMARY_VERSION,
            "campaign_id": self.campaign.id,
            "campaign_name": self.campaign.name,
            "status": status,
            # A summary without these is not reproducible from itself: it
            # reports what was found and leaves what produced it in a shell
            # history. The manifest holds the same two fields, so a summary
            # separated from its manifest still identifies its own run.
            "snapshot": self.snapshot,
            "params": self.params,
            "objective": self.campaign.c["objective"],
            # What the lanes were supposed to run at, beside what each one
            # did. Two summaries carrying the same contract_hash screened at
            # the same depth; that is the comparison AUTORESEARCH.md 5b
            # currently reconstructs after the fact.
            "run_contract": self.campaign.run_contract,
            "contract_hash": self.campaign.contract_hash,
            "stopped_by": {"type": fired[0], "detail": fired[1]} if fired
                          else {"type": None, "detail": "still running"},
            "budget": {"declared": budget,
                       "consumed": {f: round(spent[f], 3) for f in shown},
                       "remaining": {f: round(budget[f] - spent.get(f, 0), 3)
                                     for f in budget}},
            "experiments": self.experiments,
            # How well the cheap screen ordered this campaign's candidates
            # against the gate, per family. Rank correlation, not error: the
            # screen is a ranking instrument, and the only question a later
            # session can act on is whether its ordering can be trusted to
            # spend a ladder budget, or only to discard.
            "screen_quality": self.screen_quality(),
            "survivors": self.survivors,
            "frontier_advances": self.frontier_advances,
            "negative_results": self.negative_results,
            "required_outputs": self.campaign.required_outputs,
            "report": report,
            "authority": "candidates listed here passed "
                         "verify/validate_candidate.py; nothing here is a "
                         "board entry until a human reviews and submits it",
        }


def _verdict_fingerprint(survivor):
    """Hash one survivor's recorded verdict, short and stable."""
    v = survivor.get("verdict")
    if v is None:
        return None
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, default=str).encode()).hexdigest()[:16]


def write_manifest(manifest, path):
    """Write a run manifest, creating its directory."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def write_summary(summary, path, *, validate=True):
    """Write a campaign summary, creating its directory.

    Validated on the way out by default, so a reporting bug surfaces where
    the summary is produced rather than when a later session tries to read
    the registry. ``validate=False`` exists for a deliberately partial
    document under test.
    """
    if validate:
        validate_summary(summary)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return path

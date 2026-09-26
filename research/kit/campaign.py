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
  refuses anything whose verdict does not carry ``passed: true``, so a
  campaign summary cannot report a find the gate did not accept.

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
import json
import os

try:
    import jsonschema
except ImportError:                              # pragma: no cover
    jsonschema = None

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
SCHEMA_PATH = os.path.join(_ROOT, "schema", "campaign.schema.json")
SUMMARY_VERSION = 1


class CampaignError(ValueError):
    """A campaign definition that cannot be run as written."""


def _schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


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
    for cond in c["stopping"]:
        if cond["type"] == "candidates_found" and not cond.get("count"):
            raise CampaignError(
                "stopping candidates_found: needs a count, otherwise nothing "
                "says how many survivors is enough")
        if cond["type"] == "no_progress" and not cond.get("experiments"):
            raise CampaignError(
                "stopping no_progress: needs experiments, otherwise nothing "
                "says how long a dry spell has to be")
        if cond["type"] == "target_reached" and "target" not in c["objective"]:
            raise CampaignError(
                "stopping target_reached: objective.target is not set, so "
                "there is no target to reach")
    return obj


def load_campaign(path):
    """Load and validate a campaign definition from disk."""
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
    except json.JSONDecodeError as e:
        raise CampaignError(f"{path}: not valid JSON ({e})") from None
    return Campaign(validate_campaign(obj), path=path)


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

    Held in memory while a campaign runs and written out at the end. It is the
    committed half of the evidence trail, so it names only things a reviewer
    can open: staged candidates live in the gitignored ``research/candidates/``
    and are recorded by their parameters and verdict, never cited as files.
    """

    def __init__(self, campaign):
        self.campaign = campaign
        self.spent = dict.fromkeys(BUDGET_FIELDS, 0)
        self.experiments = []
        self.survivors = []
        self.negative_results = []
        self.frontier_advances = 0
        self._current = None
        self._dry_streak = 0

    # -- experiments ------------------------------------------------------
    def start_experiment(self, family, *, seed=None, note=""):
        """Begin one run: a family, a budget slice, and a seed."""
        if family not in self.campaign.families and self.campaign.families:
            raise CampaignError(
                f"family {family!r} is not one of this campaign's families "
                f"({', '.join(self.campaign.families)})")
        self._current = {"family": family, "seed": seed, "note": note,
                         "spent": dict.fromkeys(BUDGET_FIELDS, 0),
                         "candidates": 0, "survivors": 0}
        return self._current

    def end_experiment(self):
        """Close the current run and fold it into the ledger."""
        if self._current is None:
            raise CampaignError("end_experiment without start_experiment")
        exp = self._current
        self.experiments.append(exp)
        self._dry_streak = 0 if exp["survivors"] else self._dry_streak + 1
        self._current = None
        return exp

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
        gates = verdict.get("gates") or {}
        novelty = gates.get("novelty") or {}
        if advanced_frontier is None:
            advanced_frontier = bool(novelty.get("board_advancing"))
        row = {
            "n": doc["n"], "k": doc["k"], "d": doc["distance"]["d"],
            "w": (verdict.get("candidate") or {}).get("max_check_weight")
                 or (gates.get("verify") or {}).get("max_check_weight"),
            "cell": novelty.get("cell"),
            "board_advancing": novelty.get("board_advancing"),
            "fingerprint": (verdict.get("candidate") or {}).get("fingerprint"),
            "labels": list(verdict.get("labels") or []),
        }
        self.survivors.append(row)
        if self._current is not None:
            self._current["survivors"] += 1
            self._current["candidates"] += 1
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
    def budget_exhausted(self):
        """Name the first budget field that has been reached, or None."""
        budget = self.campaign.c["budget"]
        for field, cap in budget.items():
            if self.spent.get(field, 0) >= cap:
                return field
        return None

    def stop_reason(self, *, best_score=None):
        """Which stopping condition has fired, as (type, detail), or None."""
        for cond in self.campaign.c["stopping"]:
            kind = cond["type"]
            if kind == "budget_exhausted":
                field = self.budget_exhausted()
                if field:
                    cap = self.campaign.c["budget"][field]
                    return kind, f"{field} reached {self.spent[field]:g} of {cap:g}"
            elif kind == "frontier_advance" and self.frontier_advances:
                return kind, f"{self.frontier_advances} validated frontier advance(s)"
            elif kind == "candidates_found" and len(self.survivors) >= cond["count"]:
                return kind, f"{len(self.survivors)} validated survivors"
            elif kind == "no_progress" and self._dry_streak >= cond["experiments"]:
                return kind, f"{self._dry_streak} experiments with no survivor"
            elif kind == "target_reached" and best_score is not None:
                target = self.campaign.c["objective"]["target"]
                up = self.campaign.c["objective"]["direction"] == "maximize"
                if (best_score >= target) if up else (best_score <= target):
                    return kind, f"objective reached {best_score:g} against {target:g}"
        return None

    # -- output -----------------------------------------------------------
    def summary(self, *, status="completed", best_score=None, report=None):
        """Build the machine-readable campaign summary.

        Written beside the definition when a campaign ends. Zero survivors is a
        complete, reportable outcome: the ledger and the negative results are
        the finding in that case.
        """
        fired = self.stop_reason(best_score=best_score)
        budget = self.campaign.c["budget"]
        return {
            "summary_version": SUMMARY_VERSION,
            "campaign_id": self.campaign.id,
            "campaign_name": self.campaign.name,
            "status": status,
            "objective": self.campaign.c["objective"],
            "stopped_by": {"type": fired[0], "detail": fired[1]} if fired
                          else {"type": None, "detail": "still running"},
            "budget": {"declared": budget,
                       "consumed": {f: self.spent[f] for f in BUDGET_FIELDS
                                    if self.spent[f]},
                       "remaining": {f: budget[f] - self.spent.get(f, 0)
                                     for f in budget}},
            "experiments": self.experiments,
            "survivors": self.survivors,
            "frontier_advances": self.frontier_advances,
            "negative_results": self.negative_results,
            "required_outputs": self.campaign.required_outputs,
            "report": report,
            "authority": "candidates listed here passed "
                         "verify/validate_candidate.py; nothing here is a "
                         "board entry until a human reviews and submits it",
        }


def write_summary(summary, path):
    """Write a campaign summary, creating its directory."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
        f.write("\n")
    return path

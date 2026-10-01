"""Reuse of a completed refutation across runs of the same submission.

`gate_changed.py` exits early when nothing under `codes/` changed, but it
diffs against the base branch, so a PR that adds a code has a non-empty diff
on every push for the life of the PR, and a push that fixes prose pays the
full search again on byte-identical code (issue #2633).

ONLY A REFUTATION IS EVER REUSED, and its witness is re-validated by the
trusted verifier on load. That is not a conservatism, it is what makes the
cache safe at all.

The reason is the threat model. `verify.yml` runs on `pull_request`, so a run
executes the PR's own copy of the workflow, and the submitted tree's
accelerator build runs before any gate fires. A contributor can therefore
execute arbitrary code in their own run and write whatever they like into the
cache directory. A forged "not refuted" record would then let a later,
diff-clean commit skip the search entirely, which is the one outcome the gate
exists to prevent.

A forged refutation cannot do that. The witness is re-checked here against
the candidate before it is believed, so a planted record either validates,
in which case the claimed distance really is overstated and failing the run
is correct, or it does not, in which case it is discarded and the search runs.
The asymmetry is the same one that makes refutation sound in the first place:
a witness is a checkable fact, while "I looked and found nothing" is not.

The consequence is that the measured 293 minutes, which were clean re-runs,
are NOT recovered by this. Recovering them means trusting a clean result
produced by a previous commit of an untrusted branch, and nothing inside a
workflow the submitter controls can establish that. See the PR discussion for
a sketch that uses GitHub's own run history as the attestation instead.

Other conditions, each tested:

* The key covers the pinned validation closure, so any change to how the
  search works retires every entry without anyone maintaining a list.
* The key covers `deep` and whether the accelerator was available, since both
  select which battery ran.
* A reused record carries the seed and head of the run that searched, so the
  printed seed still reproduces the verdict it belongs to.
"""
import hashlib
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, "validator_manifest.json")
ENTRY_VERSION = 1


def closure_digest(manifest_path=None):
    """Digest the pinned validation closure, as one hex string.

    The same artifact `check_validator_integrity.py` enforces, so it moves on
    every re-pin and covers every file the search depends on. Returns
    "no-manifest" when the file is missing or unreadable, which is a separate
    namespace rather than an error.
    """
    path = os.path.abspath(manifest_path or MANIFEST)
    try:
        with open(path, "rb") as f:
            files = json.loads(f.read()).get("files") or {}
    except (OSError, ValueError, AttributeError):
        return "no-manifest"
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode("utf-8"))
        h.update(b"\0" + str(files[name]).encode("utf-8") + b"\0")
    return h.hexdigest()


def key_for(doc_bytes, *, deep, accelerated, manifest_path=None):
    """Return the cache key for these candidate bytes under this closure.

    ``deep`` is in the key because it selects the trial budget, so a standard
    run's record must not answer for a deep one. ``accelerated`` is there for
    the same reason: `_budget` gives a deep claim one Python seed plus the
    150x fast pass when `make fast` succeeded and three Python seeds when it
    did not, and that build is `continue-on-error`, so a flaky build would
    otherwise leave a shallow-battery record for a healthy run to reuse in
    place of the fast pass.

    The candidate's bytes rather than its parsed document: the search reads
    the matrices, and two files differing only in whitespace produce the same
    search but not the same submission, and re-searching is the cheap and
    conservative choice.
    """
    h = hashlib.sha256()
    h.update(closure_digest(manifest_path).encode("utf-8"))
    h.update(b"\0deep\0" if deep else b"\0std\0")
    h.update(b"\0fast\0" if accelerated else b"\0python\0")
    h.update(doc_bytes)
    return h.hexdigest()


def _path(cache_dir, key):
    return os.path.join(cache_dir, key[:2], key[2:] + ".json")


def load(cache_dir, doc_bytes, *, deep, accelerated, manifest_path=None):
    """Return a stored refutation for these bytes, or None.

    None on anything unexpected, and None for a record that is not a
    refutation: a miss costs a search, a wrong hit costs correctness, and a
    clean record is the one a contributor's own run could have forged.
    """
    if not cache_dir:
        return None
    key = key_for(doc_bytes, deep=deep, accelerated=accelerated,
                  manifest_path=manifest_path)
    try:
        with open(_path(cache_dir, key), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if rec.get("entry_version") != ENTRY_VERSION:
        return None
    if not isinstance(rec.get("gate"), dict):
        return None
    if not isinstance(rec.get("hits"), dict):
        return None
    # Only a refutation is reusable, and only with its witnesses. "Not
    # refuted" carries nothing a reader can check, so it is exactly what a
    # planted record would say.
    if not rec["gate"].get("refuted") or not rec["hits"]:
        return None
    return rec


def store(cache_dir, doc_bytes, gate, hits, *, deep, accelerated,
          head_sha=None, manifest_path=None):
    """Store a completed refutation; return its path, or None if refused.

    A clean result is never stored. It would be unverifiable on the way back
    in, and storing it is what would give a contributor's own run a way to
    retire the search for a later commit.
    """
    if not cache_dir:
        return None
    if not gate.get("refuted") or not hits:
        return None
    rec = {
        "entry_version": ENTRY_VERSION,
        "gate": {k: v for k, v in gate.items() if k != "circuit"},
        "hits": {m: [dh, list(wit)] for m, (dh, wit) in hits.items()},
        "head_sha": head_sha,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    key = key_for(doc_bytes, deep=deep, accelerated=accelerated,
                  manifest_path=manifest_path)
    path = _path(cache_dir, key)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        return None
    return path


def restored(rec):
    """Return (gate, hits) from a record, marked as reused.

    The gate dict keeps the seed and head of the run that searched, and gains
    `reused_from` so a reader of the receipt or the log can tell a reused
    verdict from a fresh one without comparing seeds by hand.
    """
    gate = dict(rec["gate"])
    gate["reused_from"] = {"head_sha": rec.get("head_sha"),
                           "stored_at": rec.get("stored_at"),
                           "seed": gate.get("seed")}
    hits = {m: (dh, wit) for m, (dh, wit) in
            ((m, (v[0], v[1])) for m, v in rec["hits"].items())}
    return gate, hits

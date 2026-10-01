"""Reuse of a completed distance search across runs of the same submission.

`gate_changed.py` exits early when nothing under `codes/` changed, but it
diffs against the base branch, so a PR that adds a code has a non-empty diff
on every push for the life of the PR. A push that fixes prose therefore pays
the full search again on byte-identical code. Measured over 100 `verify.yml`
runs in one day: 6 of the 7 PR branches with more than one run re-gated
identical bytes, 293.2 minutes (issue #2633).

What is reused is the search and nothing else. `gates.novelty` is a claim
about `codes/` at a point in time, so a cached verdict would serve a stale
`board_advancing` the moment any submission merges; that is the mistake
#2314 made and #2623 corrected. The search reads the candidate alone, so it
is the part that survives a board that has moved on, and it is where the time
goes.

Three properties hold the reuse down, and each is tested:

* The key covers the pinned validation closure, not just the candidate.
  `verify/gate_changed.py`, `verify/heuristic_distance.py`, `verify/gf2_fast.cpp`
  and `decode/distance.py` are all in `verify/validator_manifest.json`, so any
  change to how the search works retires every entry without anyone having to
  remember a list.
* A refutation is sticky. The search is one-sided: a lighter logical operator
  found once is a witness and keeps, while a later run that misses it has
  shown nothing. So a stored refutation is never replaced by a clean result,
  and `store` refuses to do it.
* A reused record carries the seed and head of the run that produced it, so
  the printed seed still reproduces the verdict it belongs to rather than
  being a seed the current run never used.

The cost is real and is not hidden: a PR that fails prose three times used to
get three independent searches and now gets one. The gate's budget is a fixed
`min(8000, 2500 + 40n)` under a wall-clock cap rather than "as much as we can
afford", so those extra searches were never part of the standard a submission
is held to.
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


def key_for(doc_bytes, *, deep, manifest_path=None):
    """Return the cache key for these candidate bytes under this closure.

    ``deep`` is in the key because it selects the trial budget, so a standard
    run's record must not answer for a deep one. The candidate's bytes rather
    than its parsed document: the search reads the matrices, and two files
    that differ only in whitespace produce the same search but not the same
    submission, and the cheap, conservative choice is to re-search.
    """
    h = hashlib.sha256()
    h.update(closure_digest(manifest_path).encode("utf-8"))
    h.update(b"\0deep\0" if deep else b"\0std\0")
    h.update(doc_bytes)
    return h.hexdigest()


def _path(cache_dir, key):
    return os.path.join(cache_dir, key[:2], key[2:] + ".json")


def load(cache_dir, doc_bytes, *, deep, manifest_path=None):
    """Return a stored record for these bytes, or None.

    None on anything unexpected: a miss costs a search, a wrong hit costs
    correctness.
    """
    if not cache_dir:
        return None
    key = key_for(doc_bytes, deep=deep, manifest_path=manifest_path)
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
    return rec


def store(cache_dir, doc_bytes, gate, hits, *, deep, head_sha=None,
          manifest_path=None):
    """Store a completed search; return its path, or None if refused.

    Refused when a stored refutation would be replaced by a clean result,
    because the stored witness is a fact and the clean result is only the
    absence of one.
    """
    if not cache_dir:
        return None
    prior = load(cache_dir, doc_bytes, deep=deep, manifest_path=manifest_path)
    if prior and prior["gate"].get("refuted") and not gate.get("refuted"):
        return None
    rec = {
        "entry_version": ENTRY_VERSION,
        "gate": {k: v for k, v in gate.items() if k != "circuit"},
        "hits": {m: [dh, list(wit)] for m, (dh, wit) in hits.items()},
        "head_sha": head_sha,
        "stored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    key = key_for(doc_bytes, deep=deep, manifest_path=manifest_path)
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

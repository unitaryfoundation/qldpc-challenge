"""Coordination primitives for concurrent agentic sessions (issue #2314).

Several independent sessions now run campaigns against this repository at the
same time, and the kit was written for one executor. ``save_submission`` takes
a caller-chosen path and overwrites whatever is already there, so two sessions
that find the same parameters silently clobber each other's staged candidate,
and nothing stops both of them from paying separately to confirm an identical
code through the slowest step in the loop.

This module is outside the trust spine and cannot reach into it:

* It never produces a verdict. :func:`validate_cached` calls
  ``verify/validate_candidate.py`` exactly as a session would, and all it adds
  is not paying twice for the one step of that call that does not depend on
  the board.
* The cache holds the refutation and nothing else. ``dedup`` and ``novelty``
  are statements about ``codes/`` at a point in time, so they are recomputed
  on every call, always, and a cache hit still runs the gate. What it skips is
  the random search, which reads only the candidate.
* Every cached entry carries the sha256 of the validator source that produced
  it, and is served only while that still matches: the gate changed, so its
  old answer is an opinion from a previous version of the rules.
* A served refutation can only subtract. ``passed`` is the gate's own value
  for this board ANDed with "not refuted", so reusing an entry can turn a pass
  into a failure and never the other way around.
* The cache lives under the gitignored ``research/candidates/``. Nothing in it
  can be cited as evidence, and deleting it costs compute, never correctness.
* :func:`claim` writes a note that this session is aiming at a board cell, and
  it is not a lock: nothing in ``verify/`` reads it, two sessions may hold one
  cell at once, and the write that displaces an incumbent reports it rather than
  refusing. Claims live under the gitignored ``research/claims/`` and expire, so
  a session that was killed cannot squat on a cell. The holder is
  :func:`session_id` -- the shell that typed, not the process that wrote -- so
  ``--claim`` and ``--release`` from one terminal agree while two do not.

    from coordination import run_id, staging_dir, unique_path, validate_cached
    out = staging_dir()                        # research/candidates/<run_id>/
    path = unique_path(os.path.join(out, "72-12-6.json"), doc)
    save_submission(doc, path)
    verdict, reused = validate_cached(doc)     # gate now, refutation reused
    verdict, kept = gate_and_record(path)      # the same, verdict written beside the candidate
    claim("weight-6/unrestricted", campaign="bb-1155")   # advisory, not enforced

* The verdict is kept beside the candidate. :func:`gate_and_record` writes
  what the gate returned to ``<path>.verdict.json`` (issue #2781); the cache
  above is a cache and that file is the record. A refutation in that record
  is fed back into the cache when the cache has lost it, so a lighter
  logical found on one run of a document is never searched for again on
  the same document (issue #3616).
* A preflight refusal subtracts too. :func:`gate_and_record` and
  ``submit.save_submission`` first run ``prescreen.preflight``, which is
  ``qldpc_verify.verify(doc, refute=False)``, the function the gate calls
  with the search turned off, and refuse the document only on a check the
  gate's verify step would fail it on. A document that passes goes to the
  gate unchanged; one that fails is kept, with the verifier's report, and
  gets no verdict, because the gate was never run on it (issue #3616).
"""
import errno
import hashlib
import json
import os
import re
import socket
import sys
import time
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
CANDIDATES = os.path.join(_ROOT, "research", "candidates")
VALIDATOR_SOURCE = os.path.join(_ROOT, "verify", "validate_candidate.py")
CACHE_DIRNAME = ".verdicts"
RUN_ID_ENV = "QLDPC_RUN_ID"
SESSION_ENV = "QLDPC_SESSION"
ENTRY_VERSION = 2

# Document fields the gate reads only for their schema validity and never by
# value, so two sessions that build the same matrices on different days under
# different handles land on the same cache key. Everything outside this list
# stays in the key, including ``provenance.model`` and ``provenance.novelty``,
# which the verifier does check by value. The rest of the guarantee is in
# :meth:`VerdictCache.entry`, which refuses to serve anything not itself
# schema-valid, so a malformed date cannot borrow a well-formed doc's verdict.
UNKEYED_TOP = ("name",)
UNKEYED_PROVENANCE = ("authors", "construction", "references", "date", "notes")


class CandidateCollision(RuntimeError):
    """A staging write that would have destroyed another session's candidate."""


class PreflightFailure(RuntimeError):
    """A document the gate's verify step would refuse, caught before the gate ran.

    ``result`` is ``prescreen.preflight``'s report; ``kept`` the files that
    were written instead (the document under ``rejected/`` and the report,
    or the report alone beside a staged candidate); ``path`` what the caller
    asked for.
    """

    def __init__(self, result, kept=(), *, path=None, what="not staged"):
        self.result = result
        self.kept = tuple(kept)
        self.path = path
        lines = [f"{path or 'candidate'}: {what}; the gate's verify step "
                 "would refuse this document"]
        for f in result.get("failed") or ():
            lines.append(f"  {f['check']} ({f['kind']}): {f['detail']}")
        lines.append("the code is inadmissible; no edit to the document fixes it"
                     if result.get("code_at_fault") else
                     "the document is wrong and the code may be fine; fix the "
                     "document and save it again")
        if self.kept:
            lines.append("kept: " + ", ".join(self.kept))
        super().__init__("\n".join(lines))


# -- identity and staging -------------------------------------------------

def run_id():
    """Identify this executor: ``$QLDPC_RUN_ID`` if set, else host-pid-time.

    A session that wants two runs to share a staging directory, or a harness
    that wants a readable name in the tree, sets the environment variable. The
    fallback is unique per process on one machine and close enough to unique
    across machines that two sessions do not collide by accident.
    """
    forced = os.environ.get(RUN_ID_ENV)
    if forced and forced.strip():
        return _slug(forced.strip())
    host = _slug(socket.gethostname().split(".")[0] or "host")
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{host}-{os.getpid()}"


def _slug(text):
    keep = [c if (c.isalnum() or c in "-_.") else "-" for c in str(text)]
    return "".join(keep).strip("-") or "run"


def session_id():
    """Identify the session a claim belongs to: a shell, not a process.

    A claim is taken by one ``./qldpc`` process and dropped by the next one a
    human types, so its identity has to survive the process boundary that
    :func:`run_id` deliberately does not cross: two ladders started from one
    shell must not share a staging directory, while two commands from one
    terminal must be the same session or ``release`` finds nothing to release.

    The order of preference says who knows the answer:

    1. ``$QLDPC_SESSION``, exported by the ``./qldpc`` launcher from the shell
       that started it -- the process cannot ask for that shell itself, because
       ``uv run`` forks python rather than replacing itself.
    2. ``$QLDPC_RUN_ID``, so a harness that pins one id for everything pins
       claims and staging together.
    3. The POSIX login session: one terminal, one session, across every
       process it starts. Coarser than a shell (two panes of one login can
       share it), and never wrong in the direction that loses a claim.
    """
    for key in (SESSION_ENV, RUN_ID_ENV):
        forced = os.environ.get(key)
        if forced and forced.strip():
            return _slug(forced.strip())
    host = _slug(socket.gethostname().split(".")[0] or "host")
    try:
        sid = os.getsid(0)
    except (AttributeError, OSError):            # not POSIX: per-process, as run_id
        sid = os.getpid()
    return f"{host}-{sid}"


def staging_dir(rid=None, *, root=None, create=True):
    """Return ``research/candidates/<run_id>/``, this executor's own shelf.

    Namespacing staging output by run is the whole of the collision fix: two
    sessions writing ``<n>-<k>-<d>.json`` into separate directories cannot
    overwrite each other, and the directory name says which session to ask.
    Still gitignored working state, exactly as the flat layout was.
    """
    path = os.path.join(root or CANDIDATES, rid or run_id())
    if create:
        os.makedirs(path, exist_ok=True)
    return path


# -- advisory cell claims -------------------------------------------------
#
# A claim is a note from one session to the next that it is aiming at a cell.
# It is deliberately not a lock. Nothing here is consulted by ``verify/``,
# nothing reads it but the ``qldpc targets`` listing, and two sessions may
# hold the same cell at once without either being stopped: the second write
# wins and records what it displaced, so both can see the collision rather
# than have one of them silently blocked. A mechanism that refused would be
# enforcing something, and the only thing worth enforcing here is the gate.
#
# That is why the directory is gitignored, like staging. The state is
# per-second, so committing it would guarantee a merge conflict on every
# branch that claims anything, and a file that churns is not an audit trail.
# What is worth keeping across sessions is a screening outcome, and that is
# the campaign summary (issue #2726), not a claim that expired an hour ago.

CLAIMS = os.path.join(_ROOT, "research", "claims")
CLAIM_VERSION = 1
DEFAULT_CLAIM_MINUTES = 120
CLAIM_FIELDS = ("cell", "cell_key", "session_id", "run_id", "campaign",
                "note", "claimed_at", "expires_at")


def cell_slug(cell):
    """Return a filesystem-safe name for a ``(locality, weight)`` cell pair.

    The two axis names are joined by ``__`` rather than the ``/`` a reader
    types, because ``/`` would make the claim a path that resolves to nothing
    under ``research/claims/``.
    """
    if isinstance(cell, str):
        parts = [p for p in re.split(r"[/,]+", cell.strip()) if p]
    else:
        parts = [str(p).strip() for p in cell]
    parts = [p for p in parts if p]
    if not parts:
        raise ValueError("a claim needs a cell, e.g. 'weight-6/unrestricted'")
    return "__".join(_slug(p) for p in parts)


def claim_path(cell, *, root=None):
    """Where the claim on ``cell`` lives: ``research/claims/<cell>.json``."""
    return os.path.join(root or CLAIMS, cell_slug(cell) + ".json")


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _parse(stamp):
    try:
        dt = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_claim(cell, *, root=None, now=None):
    """Return the live claim on ``cell``, or ``None``.

    An expired claim reads as absent rather than as a stale fact: a session
    that was killed an hour ago must not squat on a cell by never releasing
    it, so expiry is checked here and not only where it is written.
    """
    path = claim_path(cell, root=root)
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(rec, dict) or rec.get("claim_version") != CLAIM_VERSION:
        return None
    expires = _parse(rec.get("expires_at"))
    if expires is None or expires <= _now(now):
        return None
    return rec


def claim(cell, *, campaign="", note="", minutes=DEFAULT_CLAIM_MINUTES,
          rid=None, root=None, now=None):
    """Record that this session is aiming at ``cell``; return the record.

    Never raises because someone else holds the cell. The displaced claim,
    when there was a live one, comes back under ``displaced`` so the caller
    can print it: the point is that both sessions learn a collision is
    happening, which is what stops a second one from paying for a ladder the
    first is already building.

    The holder is :func:`session_id`, not :func:`run_id`: the process writing
    the note and the process dropping it are different processes of one
    session, and the record says which run wrote it under ``run_id``.
    """
    minutes = int(minutes)
    if minutes < 1:
        raise ValueError("a claim needs a positive lifetime; 0 would make "
                         "it invisible to the session that wrote it")
    here = _now(now)
    mine = rid or session_id()
    # Read the incumbent before writing, so it can be reported back. This is
    # not a check: nothing below refuses, because a claim that could block a
    # session would be enforcing something the gate is the only thing
    # entitled to enforce.
    prior = read_claim(cell, root=root, now=here)
    rec = {
        "claim_version": CLAIM_VERSION,
        "cell": "/".join(cell_slug(cell).split("__")),
        "cell_key": ([p for p in re.split(r"[/,]+", cell) if p]
                     if isinstance(cell, str) else list(cell)),
        "session_id": mine,
        "run_id": run_id(),
        "campaign": campaign,
        "note": note,
        "claimed_at": here.isoformat(),
        "expires_at": (here + timedelta(minutes=minutes)).isoformat(),
    }
    if prior is not None and prior["session_id"] != mine:
        rec["displaced"] = {k: prior[k] for k in CLAIM_FIELDS
                            if k in prior and k != "cell_key"}
    _write_atomic(claim_path(cell, root=root), rec)
    return rec


def release(cell, *, rid=None, root=None, now=None):
    """Drop this session's claim on ``cell``.

    Returns True when a live claim was removed. A claim held by another
    session is left alone: releasing is how a session says it is done, and
    it has no standing to say that about somebody else. The holder is
    :func:`session_id`, so it defaults to this session rather than to this
    process -- a caller that forgets to pass ``rid`` does not get the
    permissive behaviour, and a second ``./qldpc`` process of the same shell
    still finds what the first one wrote. Expiry remains the backstop for a
    session that never got to run this at all.
    """
    path = claim_path(cell, root=root)
    here = _now(now)
    try:
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(rec, dict):
        return False
    expires = _parse(rec.get("expires_at"))
    if expires is None or expires <= here:
        return False
    if rec.get("session_id") != (rid or session_id()):
        return False
    try:
        os.unlink(path)
    except FileNotFoundError:                  # pragma: no cover
        return False
    return True


def live_claims(*, root=None, now=None):
    """Every unexpired claim, newest first.

    A file that cannot be parsed is skipped, not fatal: claims are advisory
    and a listing command must not fall over because one session was killed
    mid-write.
    """
    here = _now(now)
    out = []
    try:
        names = sorted(os.listdir(root or CLAIMS))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(root or CLAIMS, name)
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(rec, dict) or rec.get("claim_version") != CLAIM_VERSION:
            continue
        expires = _parse(rec.get("expires_at"))
        if expires is None or expires <= here:
            continue
        out.append(rec)
    out.sort(key=lambda r: r.get("claimed_at") or "", reverse=True)
    return out


def prune_claims(*, root=None, now=None):
    """Delete claims whose lifetime has run out; return how many went.

    Reading already ignores them, so this is housekeeping rather than
    correctness. It is exposed because a directory that only ever grows is
    how a coordination aid becomes something a later reader has to reason
    about.
    """
    here, gone = _now(now), 0
    base = root or CLAIMS
    try:
        names = os.listdir(base)
    except OSError:
        return 0
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(base, name)
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, ValueError):
            rec = None
        expires = _parse(rec.get("expires_at")) if isinstance(rec, dict) else None
        if expires is not None and expires <= here:
            try:
                os.unlink(path)
                gone += 1
            except OSError:                           # pragma: no cover
                pass
    return gone


# -- content addressing ---------------------------------------------------

def _canonical(doc):
    """Reduce a submission to the part the gate's verdict depends on."""
    keyed = {k: v for k, v in doc.items() if k not in UNKEYED_TOP}
    prov = keyed.get("provenance")
    if isinstance(prov, dict):
        keyed["provenance"] = {k: v for k, v in prov.items()
                               if k not in UNKEYED_PROVENANCE}
    return json.dumps(keyed, sort_keys=True, separators=(",", ":"),
                      default=str)


def content_digest(doc):
    """SHA-256 of a candidate's verdict-relevant content, as hex.

    Two documents with the same digest describe the same code, the same
    claimed distance and the same witnesses, and differ at most in who
    packaged it, when, and what they called it.
    """
    return hashlib.sha256(_canonical(doc).encode("utf-8")).hexdigest()


def unique_path(path, doc=None):
    """Return a path next to ``path`` that no other candidate occupies.

    ``path`` itself when it is free, or when ``doc`` is given and the file
    already there holds the same content (re-running a search must not need a
    new filename). Otherwise the name grows a short content digest, which is
    the suffix convention sessions were already applying by hand, and then a
    counter if even that is taken.
    """
    path = os.fspath(path)
    if not os.path.exists(path):
        return path
    if doc is not None and holds_same_candidate(path, doc):
        return path
    stem, ext = os.path.splitext(path)
    tag = content_digest(doc)[:16] if doc is not None else _file_digest(path)[:16]
    nth = f"{stem}-{tag}{ext}"
    if not os.path.exists(nth) or (doc is not None
                                   and holds_same_candidate(nth, doc)):
        return nth
    i = 2
    while os.path.exists(f"{stem}-{tag}-{i}{ext}"):
        i += 1
    return f"{stem}-{tag}-{i}{ext}"


def _file_digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def holds_same_candidate(path, doc):
    """Report whether the file at ``path`` already holds this same candidate.

    False for a missing, unreadable or malformed file, so a caller deciding
    whether it is safe to overwrite errs toward keeping what is there.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return content_digest(json.load(f)) == content_digest(doc)
    except (OSError, ValueError, AttributeError, TypeError):
        return False


# -- the verifier's structural half, before anything is spent -------------
#
# ``prescreen.preflight`` is ``qldpc_verify.verify(doc, refute=False)`` read
# for its failed checks, so what it refuses is exactly what the gate's
# verify step refuses (issue #3616). Imported lazily, like the gate, so
# importing this module stays cheap.

PREFLIGHT_SUFFIX = ".preflight.json"
REJECTED_DIRNAME = "rejected"


def _preflight(doc):
    if _HERE not in sys.path:
        sys.path.insert(0, _HERE)
    import prescreen
    return prescreen.preflight(doc)


def preflight_path(path):
    """Where the preflight report for the candidate at ``path`` is kept.

    ``<stem>.preflight.json`` beside it, the convention of :func:`verdict_path`,
    and for the same reason: two extensions deep, no ``checks`` field, so a
    ``*.json`` glob for candidates cannot mistake it for one.
    """
    base = path[:-len(".json")] if path.endswith(".json") else path
    return base + PREFLIGHT_SUFFIX


def rejected_path(path):
    """Where a document refused by the preflight is kept: ``<dir>/rejected/<name>``.

    A subdirectory rather than a suffix because a refused document still has
    ``checks`` and would pass for a candidate under a ``*.json`` glob of the
    staging directory; the listing of a run directory shows only what may
    be gated.
    """
    head, name = os.path.split(os.fspath(path))
    return os.path.join(head, REJECTED_DIRNAME, name)


def record_preflight(path, result, doc=None):
    """Write the preflight report for the candidate at ``path`` beside it.

    Returns the report's path. The report is the verifier's own failed
    checks with their detail strings, which the gate's verdict does not
    carry (it keeps check names only), plus the run and time it was taken.
    """
    report = dict(result)
    report["recorded"] = {
        "candidate": os.path.basename(path),
        "content_digest": content_digest(doc) if doc is not None else None,
        "run_id": run_id(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    out = preflight_path(path)
    _write_atomic(out, report)
    return out


def quarantine(path, doc, result):
    """Keep a refused document and its report under ``rejected/`` beside ``path``.

    Returns ``(document_path, report_path)``. The document goes through
    :func:`unique_path`, so two different refused documents of one name
    both survive, and re-saving the same one reuses its file. Nothing is
    lost: a witness in a document that only needs a field fixed is still
    the most expensive thing in the loop.
    """
    kept = unique_path(rejected_path(path), doc)
    _write_atomic(kept, doc)
    return kept, record_preflight(kept, result, doc)


# -- what a cached verdict is allowed to outlive --------------------------

def validator_sha256(path=None):
    """SHA-256 of ``verify/validate_candidate.py``, read and never written.

    The same number the gate stamps into every verdict it issues. A cached
    entry whose stamp no longer matches the validator on disk is discarded
    rather than served: the gate changed, so its old answer is an opinion from
    a previous version of the rules.
    """
    return _file_digest(path or VALIDATOR_SOURCE)


def _refutation(verdict):
    """Return the board-independent half of a verdict, the random search.

    ``gates.refute`` is produced by reading the candidate and nothing else, so
    it is the only part of a verdict that survives a board that has moved on.
    Absent when the candidate failed the structural checks, because the gate
    returns before the search in that case and there is nothing to keep.
    """
    if not isinstance(verdict, dict):
        return None
    ref = (verdict.get("gates") or {}).get("refute")
    return ref if isinstance(ref, dict) and "refuted" in ref else None


def _schema_errors(doc):
    """Return schema violations in ``doc``, or None without jsonschema."""
    try:
        import jsonschema
    except ImportError:                          # pragma: no cover
        return None
    schema_path = os.path.join(_ROOT, "schema", "code.schema.json")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    return list(jsonschema.Draft202012Validator(schema).iter_errors(doc))


class VerdictCache:
    """Reuse of the one gate step that does not depend on the board.

    The first version of this cache keyed on the board as well as the
    candidate, because ``dedup`` and ``novelty`` are claims about ``codes/``
    at a point in time and serving a stale ``board_advancing`` would be
    worse than paying again. That reasoning is right and it is also what
    defeated the cache: on an active board the key went stale faster than
    candidates arrived, and the measured hit count was 7 against 366
    validations (#2314).

    So the layers are separated. ``gates.refute`` reads the candidate and
    nothing else, and on this board costs 8.3 s of the 8.4 s a warm
    validation takes; ``dedup`` and ``novelty`` read the board and cost
    0.11 s once its structural pass is memoized. Only the refutation is
    stored, every call still runs the gate, and the recomputed half is
    always current.

    What it stores is what ``verify/validate_candidate.py`` returned,
    sliced, never anything assembled here. It refuses an entry that does not
    carry the gate's own source stamp, so a hand-written dict cannot be
    planted in it, and it refuses to serve one produced by a validator that
    is no longer the validator on disk.

    Refutation is one-sided, and the entry records it that way. A refutation
    is a witness and keeps: once any attempt has found a lighter logical
    operator, every later read says refuted. "Not refuted" is only the
    absence of one, so the entry also counts the attempts behind it, and
    reusing it is a decision to trust that search rather than re-roll it.
    """

    def __init__(self, root=None):
        self.root = root or os.path.join(CANDIDATES, CACHE_DIRNAME)
        self._validator = None

    # -- the staleness condition -----------------------------------------
    def validator(self):
        """Return the validator source hash, computed once per cache object."""
        if self._validator is None:
            self._validator = validator_sha256()
        return self._validator

    def path_for(self, doc):
        """Where the entry for ``doc`` lives."""
        return os.path.join(self.root, f"{content_digest(doc)}.json")

    # -- read and write ---------------------------------------------------
    def entry(self, doc):
        """Return the stored entry for ``doc``, or None.

        None whenever anything is uncertain: no entry, a torn or unreadable
        one, one from a different validator, or a document that does not
        validate against the schema. The last case is the one that earns the
        key's freedom to ignore who packaged a candidate: the fields it drops
        are read by the gate only for their schema validity, which is
        re-checked here on the document in hand.
        """
        errs = _schema_errors(doc)
        if errs is None or errs:
            return None
        try:
            with open(self.path_for(doc), encoding="utf-8") as f:
                entry = json.load(f)
        except (OSError, ValueError):
            return None
        if entry.get("entry_version") != ENTRY_VERSION:
            return None
        if entry.get("validator_sha256") != self.validator():
            return None
        ref = entry.get("refute")
        return entry if isinstance(ref, dict) and "refuted" in ref else None

    def get(self, doc):
        """Return a reusable ``gates.refute`` block for ``doc``, or None."""
        entry = self.entry(doc)
        return entry["refute"] if entry else None

    def put(self, doc, verdict, *, refuted=True):
        """Store the refutation in ``verdict``; return its path, or None.

        Refused unless the verdict carries the source stamp of the validator
        on disk, which is what makes this a cache of the gate rather than a
        place to put a claim. Also refused for a verdict produced with
        ``refute=False``: that is the half this cache exists for, and a later
        reader would mistake the placeholder block for a real search.

        A stored refutation is never downgraded. ``attempts`` counts the
        searches behind a "not refuted", so a reader can tell one 8-second
        run from twenty.
        """
        if not refuted:
            return None
        ref = _refutation(verdict)
        if ref is None:
            return None
        stamp = (verdict.get("validator") or {}).get("source_sha256")
        if stamp != self.validator():
            return None
        prior = self.entry(doc)
        attempts = (prior or {}).get("attempts", 0) + 1
        if prior and prior["refute"].get("refuted") and not ref.get("refuted"):
            ref = prior["refute"]            # a witness found once stays found
        entry = {
            "entry_version": ENTRY_VERSION,
            "content_digest": content_digest(doc),
            "validator_sha256": self.validator(),
            "attempts": attempts,
            "run_id": run_id(),
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "refute": ref,
        }
        return _write_atomic(self.path_for(doc), entry)


def _write_atomic(path, obj):
    """Write JSON so a concurrent reader sees the old file or the new one.

    Sessions read this directory while other sessions write it, and a reader
    that catches a half-written entry would either crash or, worse, parse a
    truncated verdict.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    try:
        os.replace(tmp, path)
    except OSError:                              # pragma: no cover
        os.unlink(tmp)
        raise
    return path


def _gate():
    """Import the trusted gate, read-only, the way a session would."""
    vdir = os.path.join(_ROOT, "verify")
    if vdir not in sys.path:
        sys.path.insert(0, vdir)
    import validate_candidate
    return validate_candidate.validate_candidate


def _with_refutation(verdict, ref):
    """Return ``verdict`` with its refutation replaced by ``ref``.

    The composition is subtractive by construction. ``verdict`` is the gate's
    own answer for the board as it is right now, computed with the search
    skipped, so its ``passed`` already carries every structural and dedup
    condition; ANDing "not refuted" on top can only clear it. There is no
    path here that turns a refusal into a pass.
    """
    out = dict(verdict)
    gates = dict(out.get("gates") or {})
    if "refute" not in gates:
        return out                           # structural failure: nothing to splice
    gates["refute"] = ref
    out["gates"] = gates
    if ref.get("refuted"):
        label = f"refuted (over-claimed distance): {ref.get('detail')}"
        if label not in (out.get("labels") or []):
            out["labels"] = [label] + list(out.get("labels") or [])
        out["passed"] = False
    else:
        out["passed"] = bool(out.get("passed"))
    return out


def validate_cached(doc, *, cache=None, validator=None, seed=None, refute=True):
    """Run the gate on ``doc``, reusing an existing refutation when one applies.

    Returns ``(verdict, reused)``. The gate runs either way: ``reused`` is
    True when the random distance search was served from the cache and the
    rest of the verdict was recomputed against the board as it is now, so
    ``dedup`` and ``novelty`` are never stale and ``board_advancing`` is
    never older than this call.

    ``validator`` exists so a test can drive this without paying for a real
    confirmation; leaving it unset calls ``verify/validate_candidate.py``.
    """
    cache = VerdictCache() if cache is None else cache
    gate = validator or _gate()
    ref = cache.get(doc) if refute else None
    if ref is not None and ref.get("refuted"):
        # Refused at the door: a cached refutation stays refuted, so there is
        # nothing to re-run (issue #3619). The gate is not invoked.
        verdict = {
            "passed": False,
            "candidate": None,
            "gates": {"refute": ref},
            "labels": [f"refuted (over-claimed distance): "
                       f"{ref.get('detail')}"],
            "validator": {"source_sha256": cache.validator()},
        }
        return verdict, True
    if ref is not None:
        return _with_refutation(gate(doc, seed=seed, refute=False), ref), True
    verdict = gate(doc, seed=seed, refute=refute)
    try:
        cache.put(doc, verdict, refuted=refute)
    except OSError as e:                         # pragma: no cover
        if e.errno not in (errno.EACCES, errno.EROFS, errno.ENOSPC):
            raise
    return verdict, False


VERDICT_SUFFIX = ".verdict.json"


def verdict_path(path):
    """Return where the gate's verdict for the candidate at ``path`` is kept.

    ``<stem>.verdict.json`` beside the candidate, so the two travel together
    and a listing of a staging directory shows which candidates have been
    gated. The suffix is two extensions deep so nothing that globs
    ``*.json`` for candidates can mistake a verdict for one: a verdict has
    no ``checks`` and fails the schema, and the name says what it is first.
    """
    base = path[:-len(".json")] if path.endswith(".json") else path
    return base + VERDICT_SUFFIX


def seed_cache_from_record(cache, doc, record_path):
    """Feed a refutation recorded beside a candidate back into the cache.

    Returns True when the cache took it. Only a refutation is fed back: a
    lighter logical found for this document is a witness and stays true,
    while a clean search in the record may have been a shallow run, which
    the record does not say. The record must be for this document (its
    ``recorded.content_digest`` matches) and ``VerdictCache.put`` still
    refuses it when the validator has changed since.
    """
    if cache.get(doc) is not None:
        return False
    try:
        with open(record_path, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return False
    ref = _refutation(rec)
    if not ref or not ref.get("refuted"):
        return False
    if (rec.get("recorded") or {}).get("content_digest") != content_digest(doc):
        return False
    return cache.put(doc, rec) is not None


def gate_and_record(path, *, seed=None, refute=True, cache=None,
                    validator=None, preflight=True):
    """Run the gate on the candidate at ``path`` and keep the verdict beside it.

    Returns ``(verdict, out_path)``. The verdict is the gate's own, obtained
    through :func:`validate_cached` so a refutation already found for this
    candidate is reused, and it is written in full to :func:`verdict_path`
    with the run id and time stamped on. That file is the artifact
    ``AUTORESEARCH.md`` asks for next to every staged candidate (issue
    #2781): the documented ``python verify/validate_candidate.py <path>``
    prints the verdict and writes nothing, so a verdict that was only ever
    on stdout is gone when the session is, which is the same loss as a
    dropped witness. The cache under ``.verdicts/`` is not that artifact:
    it keeps one slice, by digest, and may be emptied at any time.

    ``verify/`` is untouched. This is a caller that persists what the gate
    returned, not a change to what it returns.

    Two things happen before the gate (issue #3616). With ``preflight``
    (the default) the document is run through ``prescreen.preflight``, the
    verifier's structural half, and a document it fails is not gated:
    the report is written to :func:`preflight_path`, no verdict is written
    because none was produced, and :class:`PreflightFailure` is raised with
    the failed checks in the verifier's words. The gate would have refused
    the document on the same checks, after spending the random search on
    it whenever its witnesses verify. Then a refutation already recorded in
    the verdict file beside the candidate is fed back into the cache when
    the cache has lost it, so the search is not run again for a lighter
    logical that an earlier run already found.
    """
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if preflight:
        result = _preflight(doc)
        if not result["ok"]:
            report = record_preflight(path, result, doc)
            raise PreflightFailure(result, (report,), path=path, what="not gated")
    cache = VerdictCache() if cache is None else cache
    seed_cache_from_record(cache, doc, verdict_path(path))
    verdict, reused = validate_cached(doc, cache=cache, validator=validator,
                                      seed=seed, refute=refute)
    out = verdict_path(path)
    record = dict(verdict)
    record["recorded"] = {
        "candidate": os.path.basename(path),
        "content_digest": content_digest(doc),
        "refutation_reused": bool(reused),
        "run_id": run_id(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_atomic(out, record)
    return verdict, out


def _main(argv):
    """Run the module as a command.

    With no arguments it prints this run's identity. ``gate <path>`` gates a
    staged candidate and writes the verdict beside it, exit 0 iff passed. A
    candidate the gate's verify step would refuse is not gated: the
    verifier's report is printed and written to ``<path>.preflight.json``
    instead of a verdict, exit 1.
    """
    if argv and argv[0] == "gate":
        if len(argv) != 2:
            print("usage: python research/kit/coordination.py gate <candidate.json>")
            return 2
        try:
            verdict, out = gate_and_record(argv[1])
        except PreflightFailure as e:
            print(json.dumps(e.result, indent=2))
            print(e, file=sys.stderr)
            return 1
        print(json.dumps(verdict, indent=2))
        print(f"verdict written to {out}", file=sys.stderr)
        return 0 if verdict.get("passed") else 1
    _cache = VerdictCache()
    print(f"run_id       {run_id()}")
    print(f"staging      {staging_dir(create=False)}")
    print(f"verdicts     {_cache.root}")
    print(f"validator    {_cache.validator()[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))

"""The code-calculus integration contract, in one tested place (issue #7444).

code-calculus (github.com/unitaryfoundation/code-calculus) is the typed
calculus of CSS code transformations whose consumer the reachability and
``cc-*`` campaigns under ``research/`` drive. It is not a dependency of this
repository. Every campaign so far found it through its own environment
variable and ``sys.path`` insertion (``CALCULUS`` in
``research/reachability_campaign.py``, ``CODE_CALCULUS_PATH`` and hard-coded
checkouts in ``research/campaigns/cc-*``) and translated a board entry into a
``CodeState`` by hand. This module is where those conventions are written
down and tested.

The contract:

* Where code-calculus is found. An importable ``machine`` package wins;
  otherwise the checkout named by ``CODE_CALCULUS_PATH`` (or the older
  ``CALCULUS``), otherwise a sibling of this repository named
  ``code-calculus`` or ``code-calculus-dev``. A checkout is a directory that
  holds ``machine/priced_calculus.py``. `locate` says which one was used,
  `load` imports it, and `CalculusUnavailable` names every place searched.
* What an entry maps to. ``CodeState.from_challenge`` takes a CSS document
  with ``n``, ``k``, and ``checks`` ``X`` and ``Z`` supports: the qubits are
  ``0 .. n - 1``, dependent rows are dropped (the first independent rows of
  each sector are kept, in document order), and a declared ``k`` that is not
  the one the ranks give is ``Malformed``. ``machine.ingestion.ingest`` does
  the same after putting the rows in canonical order. Row spaces are
  preserved either way, so the state has the entry's fingerprint
  (`round_trip_fingerprints`). A stabilizer entry (``checks.S``) has no
  ``CodeState``, and `css_document` refuses it.
* What the binding hash is. ``machine.ingestion.checks_sha256`` and
  ``verify/qldpc_verify.checks_sha256`` are the same function on a CSS
  entry, digit for digit. `binding_hash` computes both and refuses a
  disagreement, which is the drift detector between the two repositories.
* What comes back. ``to_challenge_checks`` gives the supports of a state;
  `matrices_from_state` compacts them onto ``0 .. n - 1`` for
  ``kit/submit.make_submission``. Distances are not exported: the consumer's
  ledger carries lower endpoints that are never qLDPC claims
  (``machine/consumer.json``, ``qldpc_adapter.export``), so a child's
  distance is searched by the kit like any other candidate's.
  ``DistanceLedger.from_challenge`` reads an entry's ``distance.X`` and
  ``distance.Z`` witnesses, validates them against the state, and gives
  intervals whose upper endpoints are those values (`ledger_from_entry`).
* Which version. The campaigns were written against the ``0.3`` consumer;
  `version_note` says when a checkout's release is another line.

Run on an entry::

    uv run python research/kit/calculus_bridge.py codes/<slug>.json

prints the location, the version, and the loaded state's summary as JSON.
The smoke test is ``research/test_calculus_bridge.py``; its code-calculus
half is skipped when no checkout is found.
"""

import argparse
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "verify"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import qldpc_verify  # noqa: E402

ENV = "CODE_CALCULUS_PATH"
LEGACY_ENV = "CALCULUS"
SIBLINGS = ("code-calculus", "code-calculus-dev")
MARKER = os.path.join("machine", "priced_calculus.py")
EXPECTED_RELEASE_LINE = (0, 3)
REPOSITORY = "https://github.com/unitaryfoundation/code-calculus"


class CalculusUnavailable(ImportError):
    """code-calculus was not found in any of the places the contract names."""


class ContractDrift(RuntimeError):
    """The two repositories disagree on something the contract says they share."""


@dataclass(frozen=True)
class Location:
    root: "str | None"  # None when `machine` was importable without a path
    source: str  # "importable", "explicit", "env:CODE_CALCULUS_PATH", "env:CALCULUS", or "sibling"


@dataclass
class Calculus:
    """The loaded consumer: its location, its version, and the names the bridge uses."""

    location: Location
    root: str
    version: dict
    CodeState: type
    DistanceLedger: type
    Malformed: type
    NoDerivation: type
    ingest: object
    checks_sha256: object
    modules: dict = field(default_factory=dict)


def is_checkout(path):
    """Return True when ``path`` holds the consumer (``machine/priced_calculus.py``)."""
    return bool(path) and os.path.isfile(os.path.join(path, MARKER))


def candidates(environ=None, parent=None):
    """Return the places `locate` looks after an importable package, in order, as (path, source)."""
    environ = os.environ if environ is None else environ
    parent = os.path.dirname(_ROOT) if parent is None else parent
    out = []
    for var in (ENV, LEGACY_ENV):
        value = (environ.get(var) or "").strip()
        if value:
            out.append((os.path.abspath(os.path.expanduser(value)), f"env:{var}"))
    for name in SIBLINGS:
        out.append((os.path.join(parent, name), "sibling"))
    return out


def _importable():
    try:
        return importlib.util.find_spec("machine.priced_calculus") is not None
    except (ImportError, ValueError):
        return False


def locate(explicit=None, *, environ=None, parent=None):
    """Return the `Location` of code-calculus, or None.

    ``explicit`` is a checkout path given by the caller and is the only place
    looked at when present. Otherwise an importable ``machine`` package wins,
    then the places `candidates` lists, in order.
    """
    if explicit:
        return Location(os.path.abspath(explicit), "explicit") if is_checkout(explicit) else None
    if _importable():
        return Location(None, "importable")
    for path, source in candidates(environ, parent):
        if is_checkout(path):
            return Location(path, source)
    return None


def available(**kwargs):
    """Return True when `load` would succeed."""
    return locate(**kwargs) is not None


def _git_describe(root):
    try:
        out = subprocess.run(
            ["git", "-C", root, "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _changelog_release(root):
    try:
        with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"## \[(\d+\.\d+\.\d+)\]", line)
                if m:
                    return m.group(1)
    except OSError:
        return None
    return None


def version_of(root):
    """Return ``{"release", "git"}`` for a checkout: the top CHANGELOG release and ``git describe``."""
    return {"release": _changelog_release(root), "git": _git_describe(root)}


def version_note(calculus):
    """Return a sentence when the checkout's release is not the consumer line the campaigns use, else None."""
    release = (calculus.version or {}).get("release")
    if not release:
        return "the checkout's release could not be read (no CHANGELOG release line)"
    line = tuple(int(x) for x in release.split(".")[:2])
    if line != EXPECTED_RELEASE_LINE:
        want = ".".join(str(x) for x in EXPECTED_RELEASE_LINE)
        return f"release {release} is not the {want} consumer line the research campaigns were written against"
    return None


_CACHE = {}  # the default load, once per process


def load(explicit=None, *, environ=None, parent=None, refresh=False):
    """Import code-calculus and return a `Calculus`; raise `CalculusUnavailable` when it is not found.

    The default load is cached for the process. ``explicit`` loads are not,
    and ``refresh=True`` repeats the search.
    """
    if "default" in _CACHE and not refresh and explicit is None:
        return _CACHE["default"]
    location = locate(explicit, environ=environ, parent=parent)
    if location is None:
        searched = "\n".join(f"  {source}: {path}" for path, source in candidates(environ, parent))
        raise CalculusUnavailable(
            "code-calculus not found: no importable `machine` package, and none of\n"
            + searched
            + f"\nholds {MARKER}. Clone {REPOSITORY} and set {ENV} to the checkout."
        )
    if location.root and location.root not in sys.path:
        sys.path.insert(0, location.root)
    priced = importlib.import_module("machine.priced_calculus")
    ingestion = importlib.import_module("machine.ingestion")
    intervals = importlib.import_module("machine.intervals")
    root = location.root or os.path.dirname(os.path.dirname(os.path.abspath(priced.__file__)))
    calculus = Calculus(
        location=location,
        root=root,
        version=version_of(root),
        CodeState=priced.CodeState,
        DistanceLedger=priced.DistanceLedger,
        Malformed=priced.Malformed,
        NoDerivation=priced.NoDerivation,
        ingest=ingestion.ingest,
        checks_sha256=ingestion.checks_sha256,
        modules={"priced_calculus": priced, "ingestion": ingestion, "intervals": intervals},
    )
    if explicit is None:
        _CACHE["default"] = calculus
    return calculus


# --- entries -----------------------------------------------------------------


def css_document(doc):
    """Return the CSS presentation ``{"n", "k", "checks": {"X", "Z"}}`` of an entry.

    Raises ValueError for a stabilizer or otherwise non-CSS entry: the
    calculus has no state for one.
    """
    checks = doc.get("checks") or {}
    if doc.get("code_type", "CSS") != "CSS" or "X" not in checks or "Z" not in checks:
        raise ValueError(
            f"{doc.get('name') or 'the entry'} is not a CSS entry (code_type "
            f"{doc.get('code_type', 'CSS')!r}); code-calculus has no CodeState for it"
        )
    return {
        "n": int(doc["n"]),
        "k": int(doc["k"]),
        "checks": {side: [[int(q) for q in row] for row in checks[side]] for side in ("X", "Z")},
    }


def state_from_entry(doc, *, canonical=False, calculus=None):
    """Return the ``CodeState`` of a CSS entry.

    ``canonical=False`` is ``CodeState.from_challenge`` on the entry's rows
    in document order; ``canonical=True`` is ``machine.ingestion.ingest``,
    the rows sorted first, which is the state the Lean bindings name. Both
    keep the first independent rows of each sector and raise the consumer's
    ``Malformed`` when the declared ``k`` is not the one the ranks give.
    """
    calculus = calculus or load()
    presentation = css_document(doc)
    if canonical:
        return calculus.ingest(presentation)
    return calculus.CodeState.from_challenge(presentation)


def ledger_from_entry(state, doc, lower_bounds=None, *, calculus=None):
    """Return the consumer's ``DistanceLedger`` for an entry's witnesses.

    The entry must carry ``distance.X`` and ``distance.Z`` with ``value`` and
    ``witness``; each witness is validated against ``state`` and becomes the
    sector's upper endpoint. ``lower_bounds`` is the consumer's
    ``{"X": {"value", "source"}, ...}`` form; the ledger's lower endpoints
    are never exported as qLDPC claims.
    """
    calculus = calculus or load()
    return calculus.DistanceLedger.from_challenge(state, doc, lower_bounds=lower_bounds)


def checks_from_state(state):
    """Return ``{"n", "k", "checks"}`` with the state's qubits compacted onto ``0 .. n - 1``."""
    relabel = {q: i for i, q in enumerate(state.Q)}
    return {"n": state.n(), "k": state.k(), "checks": state.to_challenge_checks(relabel=relabel)}


def matrices_from_state(state):
    """Return dense ``(HX, HZ)`` for a state, the input ``kit/submit.make_submission`` takes."""
    pres = checks_from_state(state)
    return qldpc_verify._matrix(pres["checks"]["X"], pres["n"]), qldpc_verify._matrix(pres["checks"]["Z"], pres["n"])


def entry_matrices(doc):
    """Return dense ``(HX, HZ)`` of a CSS entry."""
    pres = css_document(doc)
    return qldpc_verify._matrix(pres["checks"]["X"], pres["n"]), qldpc_verify._matrix(pres["checks"]["Z"], pres["n"])


def round_trip_fingerprints(doc, *, canonical=False, calculus=None):
    """Return ``(entry fingerprint, state fingerprint)``; equal when the state kept the entry's row spaces."""
    HX, HZ = entry_matrices(doc)
    state = state_from_entry(doc, canonical=canonical, calculus=calculus)
    SX, SZ = matrices_from_state(state)
    return qldpc_verify.css_fingerprint(HX, HZ), qldpc_verify.css_fingerprint(SX, SZ)


def binding_hash(doc, *, calculus=None):
    """Return the binding hash of a CSS entry, computed by both repositories; raise `ContractDrift` if they differ."""
    calculus = calculus or load()
    ours = qldpc_verify.checks_sha256(doc)
    theirs = calculus.checks_sha256(css_document(doc))
    if ours != theirs:
        raise ContractDrift(
            f"checks_sha256 differs: verify/qldpc_verify.py gives {ours}, code-calculus machine/ingestion.py "
            f"gives {theirs}; a certificate bound by one would not bind under the other"
        )
    return ours


def describe(doc=None, *, calculus=None):
    """Return a JSON-ready record of the location and version and, for an entry, of the loaded state."""
    calculus = calculus or load()
    out = {
        "code_calculus": {
            "root": calculus.root,
            "source": calculus.location.source,
            "version": calculus.version,
            "note": version_note(calculus),
        }
    }
    if doc is None:
        return out
    state = state_from_entry(doc, calculus=calculus)
    entry_fp, state_fp = round_trip_fingerprints(doc, calculus=calculus)
    listed = {side: len(doc["checks"][side]) for side in ("X", "Z")}
    kept = {side: len(state.sector_rows(side)) for side in ("X", "Z")}
    out["entry"] = {
        "name": doc.get("name"),
        "n": state.n(),
        "k": state.k(),
        "w": state.w(),
        "rows_listed": listed,
        "rows_kept": kept,
        "binding_hash": binding_hash(doc, calculus=calculus),
        "row_spaces_preserved": entry_fp == state_fp,
    }
    distance = doc.get("distance") or {}
    if all(isinstance(distance.get(side), dict) and "witness" in distance[side] for side in ("X", "Z")):
        ledger = ledger_from_entry(state, doc, calculus=calculus)
        out["entry"]["ledger"] = {
            "full": ledger.full.as_json(),
            "sector": {side: ledger.sector[side].as_json() for side in ("X", "Z")},
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report where code-calculus is and how an entry loads into it.")
    ap.add_argument("entry", nargs="?", help="codes/<slug>.json to load as a CodeState")
    ap.add_argument("--path", default=None, help="a code-calculus checkout to use instead of the search")
    args = ap.parse_args(argv)
    try:
        calculus = load(args.path, refresh=True)
    except CalculusUnavailable as e:
        print(str(e), file=sys.stderr)
        return 2
    doc = None
    if args.entry:
        with open(args.entry, encoding="utf-8") as f:
            doc = json.load(f)
    try:
        record = describe(doc, calculus=calculus)
    except (ValueError, ContractDrift, calculus.Malformed) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(record, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

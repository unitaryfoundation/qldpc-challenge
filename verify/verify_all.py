"""Verify every submission under codes/ and the verify/fixtures/ test inputs, and flag possible
duplicates by permutation-invariant signature. Used by CI. Exit 0 only if all
pass and no two codes/ entries share a signature.

This runs the cheap structural checks (schema, n/k/CSS/weight, witness validity,
duplicates) on every entry, plus the circuit-tier fast path (circuit_verify:
determinism, noise recipe, code binding, DEM + d_circ witness -- all
deterministic and cheap) on entries declaring one. Distance refutation is NOT
run here -- it is the per-submission job of gate_changed.py (changed files) and
the weekly job of refute_board.py (whole board, random seed).

The structural reports come from qldpc_verify.board_reports, the same pass
validate_candidate, site/build.py, and board_frontier_audit read (issue
#2613). There used to be a second copy of that pass here, a bare verify() per
entry, so the research gate's notion of a duplicate and CI's notion of a pass
could drift without any test noticing. Now one implementation produces the
report and this file only layers the circuit and measured-rate tiers on top
and accumulates the fingerprint and signature collisions. The pass is still
paid in full in CI: board_reports's disk memo is off there, and the
collision detection below is inherently a scan of the submitted tree, which
is the untrusted input. The memo only spares a developer who has already
verified these bytes in another process.

The one expensive thing here is the measured-rate tier: a circuit.ler claim is
re-measured by a sampled replica (ler_verify), ~2 x 120 s per entry at the wall
budget, and on a hosted runner the handful of entries carrying one took ~13 of
the PR job's minutes -- for claims nothing in the PR had touched. With
--ler-base REF the replica runs only for entries whose codes/<slug>.json or
circuits/<slug>/ changed since REF (the same diff principle gate_changed prices
by). PR runs pass the base branch; a push to main passes the previous head of
main, so a merge re-measures what it changed and nothing else (issue #2614:
before that it re-measured every claim on the board, about 21 CPU-hours per
merge). A diff that cannot be computed falls back to re-measuring everything.

Two things make the skip safe, and one is a cost. Safe: an unchanged claim
can only go stale through the verifier stack (a stim bump in uv.lock, a
ler_tools edit), and verify.yml routes any run whose diff touches that stack,
PR or push, to the unflagged full re-measure; check_submission_scope.py keeps
such a change out of a PR that also carries code data. The full re-measure of
every claim also runs weekly on a schedule, so no measured rate on the board
goes more than a week without being re-derived from scratch. Cost: an entry
nobody touches is re-measured weekly rather than on every merge, and a
failing scheduled run reverts nothing on its own; it is a signal to a
maintainer, not a gate.

The circuit tier is cheap per entry and not cheap in total. On the hosted
runner on 2026-11-10 it took 44.5 minutes of a 48-minute run, 718 entries at
about 4 s each, against 3.4 minutes for the structural pass over all 3,160
entries; with a gate that may use 90 minutes, a pull request that added one
code no longer fit the verify job's 130-minute cap. A week before that 223
entries carried a circuit, so a sweep that re-runs every one of them grows
with the board, and no cap outlasts that. Two flags make the tier cost what a
run changed instead. Neither loses a verdict: circuit_verify is deterministic
and reads the entry, its circuits/<slug>/ directory and the verifier, so on
the same bytes under the same verifier it can only repeat itself. A sampled
rate at least gains statistics from a re-run; this gains nothing.

--circuit-base REF is for pull requests. The tier runs only for entries whose
codes/<slug>.json or circuits/<slug>/ changed since REF, the diff --ler-base
uses, and only while the verifier is the one REF was checked with. That
second condition is checked here rather than left to the caller.
CIRCUIT_STACK below lists every module this file can import, the schema, the
accelerator sources, the dependency pins and the workflow that runs all of
it, and if any of them differs from REF the flag is void and every circuit
is checked. So a pull request that edits the verifier is still run against
every entry before it merges, and one that edits a test, the site or
research/ is not made to repeat the base branch's run. verify.yml used to make this call and could only make it
coarsely: it passed the flag on a data-only pull request and withheld it from
every other. Of the 88 others among the last 1,500 commits on main, counted
on 2026-11-11, 79 had left the stack alone and paid for the whole tier.

--circuit-record PATH is for runs on main, which have no base to lean on:
they are the base. The record maps a slug to a digest of the verifier stack
(the CIRCUIT_STACK bytes and the stim, numpy and Python versions), the
entry's bytes, and every file under its circuits/ directory. An entry whose
digest is in the record passed this tier on these bytes under this verifier
and is not re-run; every other entry is run, and recorded if it passes. Only
a pass is stored, so a failure is re-run every time, and a changed entry, a
new entry, or any edit to the stack falls out of the record by construction.
That is stricter than diffing against the previous head of main would be.
verify.yml keeps one pending run per branch, so a burst of merges leaves
heads of main that no run checked, and a diff from the last head never looks
at what those added. The record does not ask which run saw an entry, only
whether one did.

The record is a trusted input, so it is confined to main. verify.yml keeps
it in the Actions cache, restores it only on a push to main, saves it only
from a run on main, and passes this flag on no pull request; GitHub scopes a
cache to the ref that wrote it, so a pull request can neither write the
record main reads nor be answered from one. The weekly scheduled run does
not restore it. It checks every circuit and writes the record afresh, so no
line of it is more than a week from a check made from scratch. A record that
is missing, unreadable, or made under another stack is an empty one: the
failure mode costs time, never coverage. The file is rewritten as the run
goes, so a run that stops early leaves what it had earned on disk.

The structural pass and the collision scan are never skipped: they are the
part of this file that needs the whole board, and they are the cheap part."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
from qldpc_verify import board_reports
from circuit_verify import verify_circuit
from gate_changed import changed_codes as changed_code_paths
from ler_verify import summary_rate, verify_ler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _changed_slugs(base, code_root, fallback):
    """Return the slugs whose codes/<slug>.json or circuits/<slug>/ differ from `base`.

    None when the diff is unavailable, and None means "every entry": the
    failure mode must cost time, never coverage. `fallback` says what the
    caller then does, for the log.
    """
    changed = changed_code_paths(base, code_root)
    if changed is None:
        print(f"note: could not diff vs {base}; {fallback}")
        return None
    return {os.path.splitext(os.path.basename(p))[0] for p in changed}


def ler_slugs_to_measure(base, code_root):
    """Return the entries --ler-base re-measures the ler claim of, or None for all."""
    return _changed_slugs(base, code_root, "re-measuring every ler claim")


def circuit_slugs_to_check(base, code_root):
    """Return the entries --circuit-base re-runs the circuit tier of, or None for all."""
    return _changed_slugs(base, code_root, "checking every circuit tier")


# Every file a circuit verdict can depend on besides the entry and its
# circuits/<slug>/ directory: this module and everything under verify/ it can
# import, the schema qldpc_verify loads, the optional accelerator's sources
# and build recipe, the dependency pins, and verify.yml, which decides the
# environment all of it runs in (the runner image it names moved once and
# took the default Python with it, PR #4288). It is the whole import closure
# rather than circuit_verify's alone on purpose. The narrower list would need
# an argument that nothing else this file imports can change which entries
# are checked, and among the last 1,500 commits on main on 2026-11-11 the
# same 3 pull requests touched either list, so the argument would buy
# nothing.
# verify/test_verify_all.py pins this list to the imports, so a new import
# fails the suite until the list names it. decode/ is absent because only
# the measured-rate tier reads it (LER_STACK in verify.yml).
CIRCUIT_STACK = (
    "verify/build_receipt.py",
    "verify/circuit_tools.py",
    "verify/circuit_verify.py",
    "verify/gate_changed.py",
    "verify/gf2.py",
    "verify/heuristic_distance.py",
    "verify/ler_tools.py",
    "verify/ler_verify.py",
    "verify/qldpc_verify.py",
    "verify/refutation_cache.py",
    "verify/transversal_gates.py",
    "verify/validate_candidate.py",
    "verify/verify_all.py",
    "verify/gf2_fast.cpp",
    "verify/setup_gf2_fast.py",
    "schema/code.schema.json",
    "pyproject.toml",
    "uv.lock",
    "Makefile",
    ".github/workflows/verify.yml",
)
RECORD_VERSION = 1
# How many new passes may sit unwritten: a run that is cut off loses at most
# this many checks, and the file is small enough that rewriting it is free.
RECORD_FLUSH_EVERY = 25


def circuit_stack_changed(base, root=ROOT):
    """Return True unless every CIRCUIT_STACK file of this checkout is `base`'s.

    The diff is taken in the verifier's own checkout, which under verify.yml
    is the base branch's tree for a pull request that changes codes/ and the
    pull request's tree otherwise. A diff that cannot be computed counts as a
    change, so the fallback is the whole tier.
    """
    try:
        rc = subprocess.run(
            ["git", "diff", "--quiet", f"{base}...HEAD", "--", *CIRCUIT_STACK],
            cwd=root, check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL).returncode
    except OSError:
        return True
    return rc != 0


def _file_digest(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").digest()


def circuit_stack_digest(root=ROOT):
    """Digest the verifier a circuit verdict was reached under, as one hex string.

    The bytes of every CIRCUIT_STACK file as they are on disk, which is what
    runs, and the versions of the two libraries and the interpreter the tier
    computes with: uv.lock pins those, and naming them as well means an
    environment that drifted from the lock gets its own records.
    """
    h = hashlib.sha256()
    h.update(f"circuit-record-v{RECORD_VERSION}\0".encode())
    for rel in sorted(CIRCUIT_STACK):
        h.update(rel.encode() + b"\0")
        try:
            h.update(_file_digest(os.path.join(root, rel)))
        except OSError:
            h.update(b"absent")
    for dist in ("stim", "numpy"):
        try:
            version = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            version = "absent"
        h.update(f"{dist}={version}\0".encode())
    h.update(f"python={sys.version_info[0]}.{sys.version_info[1]}\0".encode())
    return h.hexdigest()


def circuit_entry_key(stack, entry_path, circuits_dir):
    """Digest what one circuit verdict was about, or None if it cannot be read.

    The stack digest, the entry file's bytes, and the path and bytes of every
    file under circuits_dir. None means the entry is checked and never
    recorded.
    """
    h = hashlib.sha256()
    h.update(stack.encode() + b"\0")
    try:
        h.update(_file_digest(entry_path))
        files = []
        for dirpath, dirnames, filenames in os.walk(circuits_dir):
            dirnames.sort()
            files += [os.path.join(dirpath, name) for name in filenames]
        for path in sorted(files):
            rel = os.path.relpath(path, circuits_dir).replace(os.sep, "/")
            h.update(rel.encode() + b"\0")
            h.update(_file_digest(path))
    except OSError:
        return None
    return h.hexdigest()


def load_circuit_record(path, stack):
    """Return {slug: key} for the passes recorded under `stack`, or {} for none.

    Anything short of a well-formed record made under this exact stack is an
    empty record, and the reason is printed, because an empty record means
    the whole tier and that should never be a surprise in a log.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"note: no circuit record at {path}; checking every circuit tier")
        return {}
    except (OSError, ValueError) as e:
        print(f"note: circuit record at {path} is unreadable ({type(e).__name__}); "
              "checking every circuit tier")
        return {}
    passed = data.get("passed") if isinstance(data, dict) else None
    if not isinstance(passed, dict) or data.get("version") != RECORD_VERSION:
        print(f"note: circuit record at {path} is not a version-{RECORD_VERSION} record; "
              "checking every circuit tier")
        return {}
    if data.get("stack") != stack:
        print(f"note: circuit record at {path} was made under another verifier stack; "
              "checking every circuit tier")
        return {}
    return {s: k for s, k in passed.items() if isinstance(s, str) and isinstance(k, str)}


def save_circuit_record(path, stack, passed):
    """Write the record atomically. A failed write is reported and costs the next run time."""
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": RECORD_VERSION, "stack": stack,
                       "passed": dict(sorted(passed.items()))}, f, indent=0)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        print(f"WARNING: could not write the circuit record to {path}: {e}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT,
                    help="repository tree containing codes/ to verify; verifier "
                         "code and fixtures still come from this checkout")
    ap.add_argument("--ler-base", default=None, metavar="REF",
                    help="re-measure circuit.ler claims only for entries whose "
                         "codes/<slug>.json or circuits/<slug>/ changed since "
                         "this git ref (PR runs); omit to re-measure every claim")
    ap.add_argument("--circuit-base", default=None, metavar="REF",
                    help="run the circuit tier only for entries whose "
                         "codes/<slug>.json or circuits/<slug>/ changed since "
                         "this git ref. Only sound when the verifier is the "
                         "one REF was checked with, so the flag is void when a "
                         "CIRCUIT_STACK file differs from REF; omit to check "
                         "every circuit tier")
    ap.add_argument("--circuit-record", default=None, metavar="PATH",
                    help="skip the circuit tier for entries this JSON record "
                         "says passed it on the same bytes under the same "
                         "verifier stack, and write the record back with this "
                         "run's passes. A trusted input: for runs on main only")
    args = ap.parse_args(argv)
    code_root = os.path.abspath(args.root)
    ler_slugs = (ler_slugs_to_measure(args.ler_base, code_root)
                 if args.ler_base else None)
    circuit_slugs = None
    if args.circuit_base:
        if circuit_stack_changed(args.circuit_base):
            print(f"note: the verifier stack differs from {args.circuit_base}, or could "
                  "not be compared with it; checking every circuit tier")
        else:
            circuit_slugs = circuit_slugs_to_check(args.circuit_base, code_root)
    stack = recorded = None
    passed = {}
    unwritten = 0
    if args.circuit_record:
        stack = circuit_stack_digest()
        recorded = load_circuit_record(args.circuit_record, stack)
    # One structural pass per tree, shared with every other consumer. The
    # reports are the memoized objects other callers in this process read, so
    # each is copied before the circuit tier writes a verdict into it.
    entries = [(e, True) for e in board_reports(os.path.join(code_root, "codes"))]
    entries += [(e, False) for e in
                board_reports(os.path.join(ROOT, "verify", "fixtures"))]
    if not entries:
        print("no submissions found")
        return 0
    failed = []
    skipped_circuits = 0
    recorded_circuits = 0
    sigs = {}
    fps = {}
    for e, is_code in entries:
        p = e["path"]
        rel = os.path.relpath(p, code_root if is_code else ROOT)
        if e["size_error"]:
            failed.append(rel)
            print(f"FAIL  {rel}  -> file_size_within_limit: {e['size_error']}")
            continue
        if e["load_error"]:
            failed.append(rel)
            print(f"FAIL  {rel}  -> {e['load_error']}")
            continue
        doc = e["doc"]
        rep = dict(e["report"])
        rep["checks"] = list(rep["checks"])
        circ = ""
        if rep["ok"] and is_code and doc.get("circuit"):
            slug = e["slug"]
            circuits_dir = os.path.join(code_root, "circuits", slug)
            if circuit_slugs is not None and slug not in circuit_slugs:
                # Not a pass on this run's evidence: the line says so, and
                # prints no d_circ, because none was earned here.
                circ = ", circuit unchanged since base (checked on the base branch)"
                skipped_circuits += 1
            else:
                key = (circuit_entry_key(stack, p, circuits_dir)
                       if recorded is not None else None)
                if key is not None and recorded.get(slug) == key:
                    # The same rule as above: no d_circ is printed, because
                    # this run did not earn one.
                    circ = ", circuit recorded as passing on these bytes (not re-run)"
                    recorded_circuits += 1
                    passed[slug] = key
                    crep = {"ok": True, "skipped": True}
                else:
                    crep = verify_circuit(doc, circuits_dir)
                if crep.get("skipped"):
                    pass
                elif crep["ok"]:
                    circ = (f", d_circ<="
                            f"{crep['earned_d_circ']['d_circ']['value']}")
                    if key is not None:
                        passed[slug] = key
                        unwritten += 1
                        if unwritten >= RECORD_FLUSH_EVERY:
                            # Carry what the old record still vouches for:
                            # a run cut off here must not cost the entries
                            # it had not reached yet.
                            save_circuit_record(args.circuit_record, stack,
                                                {**recorded, **passed})
                            unwritten = 0
                else:
                    rep["ok"] = False
                    rep["checks"] += [c for c in crep["checks"]
                                      if not c["ok"]]
            # measured-rate tier: an ler claim is re-measured,
            # never trusted; a missing decoder fails the claim rather than
            # skipping it, so an unverifiable number cannot merge.
            if rep["ok"] and (doc["circuit"] or {}).get("ler"):
                if ler_slugs is not None and slug not in ler_slugs:
                    circ += ", ler unchanged since base (re-measured on main)"
                    lrep = {"ok": True, "skipped": True}
                else:
                    lrep = verify_ler(doc, circuits_dir)
                if lrep.get("skipped"):
                    pass
                elif lrep["ok"]:
                    rate = summary_rate(doc)
                    circ += (f", ler/round<={rate:.3g} at the gate point"
                             if rate is not None else ", ler verified")
                else:
                    rep["ok"] = False
                    rep["checks"] += [c for c in lrep["checks"]
                                      if not c["ok"]]
        if rep["ok"]:
            ed = rep["earned_distance"].get("d", {})
            print(f"PASS  {rel}  -> d{ed.get('value','?')} "
                  f"({ed.get('tier','-')}){circ}")
            if is_code:
                if "signature" in rep:
                    sigs.setdefault(rep["signature"]["hash"], []).append(rel)
                if "fingerprint" in rep:
                    fps.setdefault(rep["fingerprint"], []).append(rel)
                # a CSS entry is also filed under its local-Hadamard images
                # (its X/Z swap, for a connected code), so a relabeled copy
                # collides with it; a stabilizer entry that is CSS up to
                # local Cliffords is rejected outright, so it never reaches
                # this point
                ceq = rep.get("css_equivalent") or {}
                for fp in set(ceq.get("fingerprints") or []):
                    fps.setdefault(fp, []).append(rel + " (via local Hadamard)")
                for h in set(ceq.get("signatures") or []):
                    sigs.setdefault(h, []).append(rel + " (via local Hadamard)")
        else:
            failed.append(rel)
            bad = [c["check"] for c in rep["checks"] if not c["ok"]]
            print(f"FAIL  {rel}  -> {', '.join(bad)}")

    # identical codes (same stabilizer group, same labeling): a hard error.
    # A stabilizer entry filed under its own CSS image is one entry twice,
    # not a collision, so count distinct entries per fingerprint.
    fps = {h: v for h, v in fps.items()
           if len({x.split(" (")[0] for x in v}) > 1}
    sigs = {h: v for h, v in sigs.items()
            if len({x.split(" (")[0] for x in v}) > 1}
    identical = {h: v for h, v in fps.items() if len(v) > 1}
    if identical:
        print("\nIDENTICAL CODES (same stabilizer group) -- reject:")
        for h, v in identical.items():
            print(f"  {', '.join(v)}")
    # same WL signature but not identical: likely permutation-equivalent, flag
    # for human review (WL is a strong necessary condition, not a proof).
    soft = {h: v for h, v in sigs.items()
            if len(v) > 1 and not any(set(v) <= set(iv)
                                      for iv in identical.values())}
    if soft:
        print("\nPOSSIBLE EQUIVALENT CODES (same Weisfeiler-Leman signature; "
              "review):")
        for h, v in soft.items():
            print(f"  {h}: {', '.join(v)}")

    if skipped_circuits:
        print(f"\ncircuit tier not re-run for {skipped_circuits} entries "
              f"unchanged since {args.circuit_base}")
    if recorded is not None:
        # The finished record holds this run's entries only, so an entry
        # that left the board, or stopped passing, leaves the record.
        save_circuit_record(args.circuit_record, stack, passed)
        print(f"\ncircuit tier not re-run for {recorded_circuits} entries recorded as "
              f"passing on these bytes; {len(passed)} passes now in {args.circuit_record}")
    print(f"\n{len(entries)-len(failed)}/{len(entries)} passed")
    return 1 if (failed or identical) else 0


if __name__ == "__main__":
    sys.exit(main())

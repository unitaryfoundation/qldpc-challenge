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
code no longer fit the verify job's 130-minute cap. With --circuit-base REF
the tier runs only for entries whose codes/<slug>.json or circuits/<slug>/
changed since REF, the diff --ler-base uses.

That skip may be used in fewer places than the LER one, and where it may be
used it loses nothing. Fewer places: a measured rate can only go stale
through the LER stack, but any file of the verifier can change a circuit
verdict, so verify.yml passes --circuit-base only on a data-only pull request
(every changed file under the submission surface), where the verifier is the
base branch's byte for byte. Loses nothing: circuit_verify is deterministic
and reads the entry and its circuits/<slug>/ directory and nothing else, so
on an unchanged entry it can only repeat the verdict that the run on the base
branch reached on the same bytes with the same verifier. A sampled rate at
least gains statistics from a re-run; this gains nothing. A push to main, a
scheduled run, and a pull request that changes anything outside the
submission surface still run the whole tier, so every state of main is
checked in full and a verifier change is checked against every entry before
it merges. A diff that cannot be computed falls back to checking everything.
The structural pass and the collision scan are never skipped: they are the
part of this file that needs the whole board, and they are the cheap part."""

import argparse
import os
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
                         "one REF was checked with (data-only PR runs); omit "
                         "to check every circuit tier")
    args = ap.parse_args(argv)
    code_root = os.path.abspath(args.root)
    ler_slugs = (ler_slugs_to_measure(args.ler_base, code_root)
                 if args.ler_base else None)
    circuit_slugs = (circuit_slugs_to_check(args.circuit_base, code_root)
                     if args.circuit_base else None)
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
                crep = verify_circuit(doc, circuits_dir)
                if crep["ok"]:
                    circ = (f", d_circ<="
                            f"{crep['earned_d_circ']['d_circ']['value']}")
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
    print(f"\n{len(entries)-len(failed)}/{len(entries)} passed")
    return 1 if (failed or identical) else 0


if __name__ == "__main__":
    sys.exit(main())

"""Verify every submission under codes/ and the verify/fixtures/ test inputs, and flag possible
duplicates by permutation-invariant signature. Used by CI. Exit 0 only if all
pass and no two codes/ entries share a signature.

This runs the cheap structural checks (schema, n/k/CSS/weight, witness validity,
duplicates) on every entry, plus the circuit-tier fast path (circuit_verify:
determinism, noise recipe, code binding, DEM + d_circ witness -- all
deterministic and cheap) on entries declaring one. Distance refutation is NOT
run here -- it is the per-submission job of gate_changed.py (changed files) and
the weekly job of refute_board.py (whole board, random seed).

The one expensive thing here is the measured-rate tier: a circuit.ler claim is
re-measured by a sampled replica (ler_verify), ~2 x 120 s per entry at the wall
budget, and on a hosted runner the handful of entries carrying one took ~13 of
the PR job's minutes -- for claims nothing in the PR had touched. With
--ler-base REF the replica runs only for entries whose codes/<slug>.json or
circuits/<slug>/ changed since REF (the same diff principle gate_changed prices
by); every other claim was admitted when it merged and is re-measured in full
on every push to main, which runs without the flag. A diff that cannot be
computed falls back to re-measuring everything.

Two things make the skip safe, and one is a cost. Safe: an unchanged claim
can only go stale through the verifier stack (a stim bump in uv.lock, a
ler_tools edit), and check_submission_scope.py rejects any PR that mixes those
critical files with codes/ -- so such a change arrives without code data and
CI routes it to the unflagged, full re-measure. Cost: for entries a PR does
not touch, LER regression detection moves from pre-merge to the post-merge
push run, and a failing push run reverts nothing on its own; it is a signal
to a maintainer, not a gate."""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from qldpc_verify import file_size_error, verify
from circuit_verify import verify_circuit
from gate_changed import changed_codes as changed_code_paths
from ler_verify import verify_ler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ler_slugs_to_measure(base, code_root):
    """Slugs whose codes/<slug>.json or circuits/<slug>/ differ from git ref
    `base`, or None when the diff is unavailable (then every claim is
    re-measured -- the failure mode must cost time, never coverage)."""
    changed = changed_code_paths(base, code_root)
    if changed is None:
        print(f"note: could not diff vs {base}; re-measuring every ler claim")
        return None
    return {os.path.splitext(os.path.basename(p))[0] for p in changed}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT,
                    help="repository tree containing codes/ to verify; verifier "
                         "code and fixtures still come from this checkout")
    ap.add_argument("--ler-base", default=None, metavar="REF",
                    help="re-measure circuit.ler claims only for entries whose "
                         "codes/<slug>.json or circuits/<slug>/ changed since "
                         "this git ref (PR runs); omit to re-measure every claim")
    args = ap.parse_args(argv)
    code_root = os.path.abspath(args.root)
    ler_slugs = (ler_slugs_to_measure(args.ler_base, code_root)
                 if args.ler_base else None)
    code_paths = sorted(glob.glob(os.path.join(code_root, "codes", "*.json")))
    fixture_paths = sorted(glob.glob(os.path.join(ROOT, "verify", "fixtures", "*.json")))
    paths = code_paths + fixture_paths
    if not paths:
        print("no submissions found")
        return 0
    failed = []
    sigs = {}
    fps = {}
    for p in paths:
        is_code = os.path.abspath(p).startswith(
            os.path.join(code_root, "codes") + os.sep)
        rel = os.path.relpath(p, code_root if is_code else ROOT)
        ferr = file_size_error(p)
        if ferr:
            failed.append(rel)
            print(f"FAIL  {rel}  -> file_size_within_limit: {ferr}")
            continue
        with open(p) as f:
            doc = json.load(f)
        rep = verify(doc)   # structural checks; refutation lives in gate_changed / refute_board
        circ = ""
        if rep["ok"] and is_code and doc.get("circuit"):
            slug = os.path.splitext(os.path.basename(p))[0]
            circuits_dir = os.path.join(code_root, "circuits", slug)
            crep = verify_circuit(doc, circuits_dir)
            if crep["ok"]:
                circ = (f", d_circ<="
                        f"{crep['earned_d_circ']['d_circ']['value']}")
            else:
                rep["ok"] = False
                rep["checks"] += [c for c in crep["checks"] if not c["ok"]]
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
                    lers = [doc["circuit"]["ler"][s]["ler_per_round"]
                            for s in ("X", "Z")]
                    circ += f", ler/round<={max(lers):.3g}"
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
                # a stabilizer entry that is CSS up to local Hadamards is also
                # filed under that CSS code's identity, so a
                # Hadamard-relabeled copy of a CSS entry collides with it
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

    print(f"\n{len(paths)-len(failed)}/{len(paths)} passed")
    return 1 if (failed or identical) else 0


if __name__ == "__main__":
    sys.exit(main())

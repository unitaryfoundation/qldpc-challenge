"""Integrity check for the repo-local production verdict/policy closure (CI).

Validation is only as trustworthy as the entrypoints, local dependencies, schema,
build inputs, and workflow definitions that produce its verdicts. If one of those
could change without appearing in the manifest, a later submission would inherit a
different trusted gate with no re-pin to call attention to the change. This pins the
SHA-256 of the current repo-local production closure and fails if any of it drifts.

Effect: a change to the trusted stack cannot be silent. It must re-pin the manifest
(`--update`), and that manifest diff is a small, reviewable, CODEOWNERS-gatable line
in the PR. Code submissions are still judged by the base branch's trusted checkout;
the manifest is the durable review signal for deliberate changes to that checkout.

  python verify/check_validator_integrity.py             # verify; exit 1 on drift
  python verify/check_validator_integrity.py --update     # re-pin a reviewed change
  python verify/check_validator_integrity.py --root PATH  # check another tree
"""
import argparse
import glob
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# Explicit repo-relative production closure. Keep this list readable: it is the
# statement of which local sources and configuration can change a validation,
# refutation, authorship, submission-scope, or prose-policy verdict. Tests,
# submissions, generated binaries, site rendering, and unused offline tools are not
# verdict dependencies. validator_manifest.json cannot hash itself without recursion.
TRUSTED = (
    # CI orchestration: selects the trusted checkout, commands, and arguments.
    ".github/workflows/prose.yml",
    ".github/workflows/refute-weekly.yml",
    ".github/workflows/verify.yml",
    # Environment definition and the optional C++ accelerator build inputs.
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    "verify/setup_gf2_fast.py",
    "verify/gf2_fast.cpp",
    # Local data/module dependencies outside verify/.
    "decode/distance.py",
    "schema/code.schema.json",
    # CI and autoresearch entrypoints plus their in-tree Python dependencies.
    "verify/build_receipt.py",
    "verify/check_authorship.py",
    "verify/check_prose.py",
    "verify/check_submission_scope.py",
    "verify/check_validator_integrity.py",
    "verify/circuit_tools.py",
    "verify/circuit_verify.py",
    "verify/fixtures/72-6-6.json",
    "verify/gate_changed.py",
    "verify/gf2.py",
    "verify/heuristic_distance.py",
    "verify/qldpc_verify.py",
    "verify/refute_board.py",
    "verify/validate_candidate.py",
    "verify/verify_all.py",
)

# verify_all.py deliberately validates every JSON fixture in this directory. The
# current fixture is explicit above so deleting it fails closed; discovery here also
# makes a newly added fixture require a manifest update automatically.
TRUSTED_FIXTURES = "verify/fixtures/*.json"


def trusted_files(root=_ROOT):
    files = list(TRUSTED)
    for path in sorted(glob.glob(os.path.join(root, TRUSTED_FIXTURES))):
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        if relative not in files:
            files.append(relative)
    return tuple(files)


def _manifest_path(root):
    return os.path.join(root, "verify", "validator_manifest.json")


def _sha256(root, filename):
    with open(os.path.join(root, filename), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def current_hashes(root=_ROOT):
    return {fn: _sha256(root, fn) for fn in trusted_files(root)
            if os.path.isfile(os.path.join(root, fn))}


def update(root=_ROOT):
    expected = trusted_files(root)
    hashes = current_hashes(root)
    missing = [fn for fn in expected if fn not in hashes]
    if missing:
        print("FAIL: cannot re-pin an incomplete trusted validation closure:")
        for fn in missing:
            print(f"  - {fn}: missing from tree")
        return 1
    manifest = {
        "_comment": ("Pinned SHA-256 of the repo-local production validation and "
                     "policy-gate execution closure. "
                     "CI (check_validator_integrity.py) fails if any of these files "
                     "drifts from this pin. Re-pin deliberately with "
                     "`python verify/check_validator_integrity.py --update` and get "
                     "the diff reviewed."),
        "files": hashes,
    }
    manifest_path = _manifest_path(root)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"re-pinned {len(expected)} files -> "
          f"{os.path.relpath(manifest_path, root)}")
    return 0


def check(root=_ROOT):
    manifest_path = _manifest_path(root)
    if not os.path.exists(manifest_path):
        print(f"FAIL: no manifest at {manifest_path}; run --update to create it")
        return 1
    try:
        with open(manifest_path) as f:
            pinned = json.load(f).get("files", {})
    except (OSError, ValueError) as e:
        print(f"FAIL: could not read integrity manifest: {e}")
        return 1
    if not isinstance(pinned, dict):
        print("FAIL: integrity manifest 'files' must be an object")
        return 1
    cur = current_hashes(root)
    expected = trusted_files(root)
    drift = []
    for fn in expected:
        if fn not in cur:
            drift.append(f"{fn}: missing from tree")
        elif fn not in pinned:
            drift.append(f"{fn}: not pinned (new trusted file)")
        elif pinned[fn] != cur[fn]:
            drift.append(f"{fn}: changed (pinned {pinned[fn][:12]}..., now {cur[fn][:12]}...)")
    stale = [fn for fn in pinned if fn not in expected]
    for fn in stale:
        drift.append(f"{fn}: pinned but no longer in the trusted list")
    if drift:
        print("FAIL: the trusted validation stack drifted from its pin:")
        for d in drift:
            print(f"  - {d}")
        print("\nIf this change is intended, re-pin with "
              "`python verify/check_validator_integrity.py --update` and have the "
              "manifest diff reviewed (these files gate what the board accepts).")
        return 1
    print(f"ok: trusted validation stack matches the pin ({len(expected)} files)")
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_ROOT,
                    help="repository tree to check (default: this checkout)")
    ap.add_argument("--update", action="store_true",
                    help="replace the manifest with hashes from the selected tree")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    return update(root) if args.update else check(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

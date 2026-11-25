"""Run the test suite. A thin wrapper over pytest, kept as the documented entry
point so CI and the README command do not change.

Discovery is still by convention -- pytest collects test_*.py under verify/,
research/, site/, and cli/ -- so a new test joins the suite the moment it exists and
cannot be silently left out of CI the way a hand-listed step can (which is how
two of five tests once went unrun).

  uv run --frozen python run_tests.py              # everything (what CI runs)
  uv run --frozen python run_tests.py --skip-slow  # quick local iteration

To run or debug one test, call pytest directly; it replaces running a test file
as a standalone script:

  uv run pytest verify/test_verifier.py            # one file
  uv run pytest verify/test_verifier.py::test_main # one test
  uv run pytest -k refute -x --pdb                 # match, stop, drop into pdb
"""

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# The suite's heavy hitters, as pytest node ids or a whole path. --skip-slow is a
# local-iteration flag: CI never passes it, so what it skips is the same set CI runs.
SLOW = [
    "verify/test_refute_gate.py::test_structural_stage_ordering",
    "verify/test_refute_gate.py::test_orbit_fold_stage_ordering",
    "verify/test_validate_candidate.py::test_validate_candidate",
    "verify/test_stabilizer_codes.py::test_hadamard_copy_of_a_board_code_is_a_duplicate",
    "verify/test_verifier.py::test_adversarial",
    "verify/test_verifier.py::test_main",
    "cli/test_reproduce.py::test_the_cheap_core_reproduces_and_writes_a_receipt",
    # a whole file, because its module-scoped board load costs more than its tests
    "verify/test_cli_targets.py",
]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-slow", action="store_true", help="skip the tests listed in SLOW")
    args, extra = ap.parse_known_args(argv)

    cmd = [sys.executable, "-m", "pytest", "verify", "research", "site", "cli"]
    if args.skip_slow and SLOW:
        for s in SLOW:
            # --deselect takes its id as a separate argv entry; a bare
            # "--deselect" is a pytest usage error.
            if "::" in s:
                cmd += ["--deselect", s]
            else:
                cmd += ["--ignore=" + s]
    cmd += extra
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

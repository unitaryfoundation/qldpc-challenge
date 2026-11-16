#!/usr/bin/env python3
"""Certify a challenge CSS code's exact distance with QEDist.

Usage:
    uv run python research/qedist_audit.py codes/90-12-12.json \
        --out research/candidates/qedist/90-12-12

QEDist must be installed separately (https://github.com/yeon-lee/QEDist);
set QEDIST=/path/to/qedist if it is not on PATH.  Results are evidence for
research use only -- they are not board certification (see AGENTS.md).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT / "research" / "kit") not in sys.path:
    sys.path.insert(0, str(_ROOT / "research" / "kit"))

from qedist import certify_challenge, find_qedist  # noqa: E402


def _default_out(code_path: Path) -> Path:
    slug = code_path.stem
    return _ROOT / "research" / "candidates" / "qedist" / slug


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", help="path to a challenge code JSON (CSS)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output run directory (default: research/candidates/qedist/<slug>)")
    parser.add_argument("--profile", default="css", choices=("css", "lp"))
    parser.add_argument("--cutoff", type=int, default=None,
                        help="exclude logicals up to this weight (default: d-1)")
    parser.add_argument("--seconds", type=float, default=60.0,
                        help="seconds per shard")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-witnesses", action="store_true")
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args(argv)

    code_path = Path(args.code)
    if not code_path.exists():
        print("code not found: %s" % code_path, file=sys.stderr)
        return 2
    out_dir = args.out if args.out is not None else _default_out(code_path)

    if find_qedist() is None:
        print("QEDist is not installed or not on PATH.", file=sys.stderr)
        print("Install: git clone https://github.com/yeon-lee/QEDist.git && "
              "cd QEDist && python -m venv .venv && . .venv/bin/activate "
              "&& python -m pip install .", file=sys.stderr)
        print("Or set QEDIST=/path/to/qedist", file=sys.stderr)
        return 2

    try:
        summary = certify_challenge(
            code_path,
            out_dir,
            profile=args.profile,
            cutoff=args.cutoff,
            seconds=args.seconds,
            workers=args.workers,
            include_witnesses=not args.no_witnesses,
        )
    except Exception as exc:  # noqa: BLE001
        print("QEDist failed: %s" % exc, file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("code:              %s" % summary["code"])
        print("status:            %s" % summary["status"])
        print("exact distance:     %s" % summary["exact_distance"])
        print("lower bound:       %s" % summary["distance_lower_bound"])
        print("upper bound:       %s" % summary["distance_upper_bound"])
        print("nodes:             %s" % summary["nodes"])
        print("run dir:           %s" % summary["run_dir"])
        sb = summary.get("sector_bounds") or {}
        for side, info in sb.items():
            print("  %s: lower=%s upper=%s" % (side, info.get("lower"), info.get("upper")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

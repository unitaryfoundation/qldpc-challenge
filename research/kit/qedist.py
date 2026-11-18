"""Adapter between challenge code JSON and QEDist (exact-distance certification).

QEDist (https://github.com/yeon-lee/QEDist) is an optional, external tool for
certifying exact CSS distances.  It is not part of the trusted verifier and
its results are *evidence*, not board certification; see AGENTS.md.  This
module only converts a challenge entry into QEDist's input format and drives
the ``qedist`` command-line tool when it is installed.

Nothing here touches ``verify/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional


QEDIST_SCHEMA = "cssdist.code.v1"


def challenge_to_qedist(doc: dict, *, include_witnesses: bool = True) -> dict:
    """Convert a challenge code document (CSS) into a QEDist code document."""
    if doc.get("code_type", "CSS") != "CSS":
        raise ValueError(
            "QEDist only handles CSS codes; got code_type=%r" % doc.get("code_type")
        )
    checks = doc.get("checks") or {}
    if "X" not in checks or "Z" not in checks:
        raise ValueError("challenge code is missing checks.X / checks.Z")
    n = int(doc["n"])
    out: dict[str, Any] = {
        "schema": QEDIST_SCHEMA,
        "name": doc.get("name"),
        "n": n,
        "hx": [list(r) for r in checks["X"]],
        "hz": [list(r) for r in checks["Z"]],
    }
    if include_witnesses:
        witnesses: dict[str, list] = {}
        dist = doc.get("distance") or {}
        for sector in ("X", "Z"):
            sec = dist.get(sector)
            if isinstance(sec, dict) and isinstance(sec.get("witness"), list):
                witnesses[sector] = [list(sec["witness"])]
        if witnesses:
            out["witnesses"] = witnesses
    return out


def find_qedist() -> Optional[list[str]]:
    """Return an argv prefix that invokes QEDist, or None if unavailable."""
    env = os.environ.get("QEDIST")
    if env:
        return [env]
    for name in ("qedist", "cssdist"):
        exe = shutil.which(name)
        if exe:
            return [exe]
    try:
        import cssdist  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "cssdist"]


def _run(cmd: list[str], *, cwd: Optional[Path] = None) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "QEDist command failed (exit %d): %s\n--- stdout ---\n%s\n--- stderr ---\n%s"
            % (proc.returncode, " ".join(cmd), proc.stdout, proc.stderr)
        )


def certify_challenge(
    code_path,
    out_dir,
    *,
    profile: str = "css",
    cutoff=None,
    seconds: float = 60.0,
    workers: int = 1,
    include_witnesses: bool = True,
) -> dict:
    """Certify one challenge code with QEDist; return a small summary dict."""
    code_path = Path(code_path)
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(code_path.read_text())

    if cutoff is None:
        d = (doc.get("distance") or {}).get("d")
        cutoff = (int(d) - 1) if d is not None else 10
    if cutoff < 1:
        cutoff = 1

    prefix = find_qedist()
    if prefix is None:
        raise RuntimeError(
            "QEDist is not installed. Install it with:\n"
            "  git clone https://github.com/yeon-lee/QEDist.git\n"
            "  cd QEDist && python -m venv .venv && . .venv/bin/activate "
            "&& python -m pip install .\n"
            "or set the QEDIST environment variable to the executable path."
        )

    inp = challenge_to_qedist(doc, include_witnesses=include_witnesses)
    input_path = out_dir.parent / (out_dir.name + ".input.json")
    input_path.write_text(json.dumps(inp, indent=2) + "\n")

    def _invoke(witnesses: bool) -> None:
        if not witnesses:
            inp2 = challenge_to_qedist(doc, include_witnesses=False)
            input_path.write_text(json.dumps(inp2, indent=2) + "\n")
        cmd = prefix + [
            "certify", str(input_path),
            "--profile", profile,
            "--cutoff", str(cutoff),
            "--seconds-per-shard", str(seconds),
            "--workers", str(workers),
            "--out", str(out_dir),
        ]
        if out_dir.exists():
            cmd.insert(-2, "--resume")
        _run(cmd)
        _run(prefix + ["audit", str(out_dir)])

    try:
        _invoke(include_witnesses)
    except RuntimeError as exc:
        if (include_witnesses and "Invalid" in str(exc)
                and "witness" in str(exc).lower()):
            _invoke(False)
        else:
            raise

    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError("QEDist did not write %s" % result_path)
    result = json.loads(result_path.read_text())
    return {
        "code": str(code_path),
        "status": result.get("status"),
        "exact_distance": result.get("exact_distance"),
        "distance_lower_bound": result.get("distance_lower_bound"),
        "distance_upper_bound": result.get("distance_upper_bound"),
        "nodes": result.get("nodes_in_recorded_attempts"),
        "run_dir": str(out_dir),
        "sector_bounds": result.get("sector_bounds"),
    }


QEDIST_STABILIZER_SCHEMA = "qedist.stabilizer.v1"


def _supports_to_pauli(n: int, x, z) -> str:
    xs = set(x or [])
    zs = set(z or [])
    chars = []
    for q in range(n):
        has_x = q in xs
        has_z = q in zs
        if has_x and has_z:
            chars.append("Y")
        elif has_x:
            chars.append("X")
        elif has_z:
            chars.append("Z")
        else:
            chars.append("I")
    return "".join(chars)


def challenge_stabilizer_to_qedist(doc: dict, *, include_witnesses: bool = True) -> dict:
    if doc.get("code_type", "stabilizer") != "stabilizer":
        raise ValueError(
            "QEDist stabilizer path handles stabilizer codes; got code_type=%r"
            % doc.get("code_type")
        )
    n = int(doc["n"])
    checks = doc.get("checks") or {}
    stabs = checks.get("S")
    if not isinstance(stabs, list) or not stabs:
        raise ValueError("challenge stabilizer code is missing checks.S")
    out = {
        "schema": QEDIST_STABILIZER_SCHEMA,
        "name": doc.get("name"),
        "n": n,
        "stabilizers": [_supports_to_pauli(n, s.get("X"), s.get("Z")) for s in stabs],
    }
    if include_witnesses:
        dist = doc.get("distance") or {}
        side = dist.get("P")
        if isinstance(side, dict):
            wit = side.get("witness")
            if isinstance(wit, dict):
                out["witnesses"] = [_supports_to_pauli(n, wit.get("X"), wit.get("Z"))]
    return out


def certify_stabilizer_challenge(
    code_path,
    out_dir,
    *,
    cutoff=None,
    seconds: float = 60.0,
    workers: int = 1,
    include_witnesses: bool = True,
    shards: int = 1,
) -> dict:
    code_path = Path(code_path)
    out_dir = Path(out_dir)
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(code_path.read_text())

    if cutoff is None:
        d = (doc.get("distance") or {}).get("d")
        if d is None:
            d = ((doc.get("distance") or {}).get("P") or {}).get("value")
        cutoff = (int(d) - 1) if d is not None else 10
    if cutoff < 1:
        cutoff = 1

    prefix = find_qedist()
    if prefix is None:
        raise RuntimeError(
            "QEDist is not installed. Install it with:\\n"
            "  git clone https://github.com/yeon-lee/QEDist.git\\n"
            "  cd QEDist && python -m venv .venv && . .venv/bin/activate "
            "&& python -m pip install .\\n"
            "or set the QEDIST environment variable to the executable path."
        )

    inp = challenge_stabilizer_to_qedist(doc, include_witnesses=include_witnesses)
    input_path = out_dir.parent / (out_dir.name + ".input.json")
    input_path.write_text(json.dumps(inp, indent=2) + "\n")

    def _invoke(witnesses: bool) -> None:
        if not witnesses:
            inp2 = challenge_stabilizer_to_qedist(doc, include_witnesses=False)
            input_path.write_text(json.dumps(inp2, indent=2) + "\n")
        cmd = prefix + [
            "certify-stabilizer", str(input_path),
            "--cutoff", str(cutoff),
            "--seconds", str(seconds),
            "--workers", str(workers),
            "--shards", str(shards),
            "--out", str(out_dir),
        ]
        if out_dir.exists():
            cmd.append("--resume")
        _run(cmd)
        _run(prefix + ["audit-stabilizer", str(out_dir)])

    try:
        _invoke(include_witnesses)
    except RuntimeError as exc:
        if (include_witnesses and "Invalid" in str(exc)
                and "witness" in str(exc).lower()):
            _invoke(False)
        else:
            raise

    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise RuntimeError("QEDist did not write %s" % result_path)
    result = json.loads(result_path.read_text())
    return {
        "code": str(code_path),
        "status": result.get("status"),
        "exact_distance": result.get("exact_distance"),
        "distance_lower_bound": result.get("distance_lower_bound"),
        "distance_upper_bound": result.get("distance_upper_bound"),
        "nodes": result.get("nodes_in_recorded_attempts"),
        "run_dir": str(out_dir),
        "witness": result.get("witness"),
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Certify a challenge code with QEDist")
    parser.add_argument("code", help="path to a challenge code JSON (CSS)")
    parser.add_argument("--out", required=True, help="output run directory")
    parser.add_argument("--profile", default="css", choices=("css", "lp"))
    parser.add_argument("--cutoff", type=int, default=None)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--no-witnesses", action="store_true")
    args = parser.parse_args(argv)

    import json as _json
    _doc = _json.loads(Path(args.code).read_text())
    if _doc.get("code_type") == "stabilizer":
        summary = certify_stabilizer_challenge(
            args.code,
            args.out,
            cutoff=args.cutoff,
            seconds=args.seconds,
            workers=args.workers,
            include_witnesses=not args.no_witnesses,
        )
    else:
        summary = certify_challenge(
            args.code,
            args.out,
            profile=args.profile,
            cutoff=args.cutoff,
            seconds=args.seconds,
            workers=args.workers,
            include_witnesses=not args.no_witnesses,
        )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

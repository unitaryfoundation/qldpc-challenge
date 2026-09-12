"""Build pinned DistQLDPC with an observation-only patch on macOS or Linux."""

import argparse
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

from common import HERE, atomic_json, sha256

SPEC = HERE / "distqldpc"
BUILD_RECORD = HERE / "build" / "distqldpc.json"


def build(checkout, compiler, sources):
    """Extract the pinned commit separately; never patch the cached checkout."""
    pin = json.loads((SPEC / "source.json").read_text())
    checkout = checkout.resolve()
    if not checkout.exists():
        subprocess.run(["git", "clone", pin["url"], str(checkout)], check=True)
    subprocess.run(["git", "cat-file", "-e", f"{pin['commit']}^{{commit}}"], cwd=checkout, check=True)
    # git archive reads the exact commit even if a developer uses another checkout state.
    archive = subprocess.check_output(["git", "archive", pin["commit"]], cwd=checkout)
    sources = sources.resolve()
    if sources.exists():
        raise FileExistsError(f"Build directory already exists: {sources}; choose a fresh --build-directory")
    sources.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(sources, filter="data")
    # The upstream engine uses CRLF; normalize before applying the portable diff.
    solver = sources / "src" / "solver" / "Solver.cc"
    solver.write_bytes(solver.read_bytes().replace(b"\r\n", b"\n"))
    subprocess.run(["patch", "-p1", "-i", str(SPEC / "upstream.patch")], cwd=sources, check=True)
    shutil.copyfile(SPEC / "observer.h", sources / "src" / "core" / "observer.h")
    command = [
        "make",
        "-j4",
        f"CXX={compiler}",
        "CXXFLAGS=-Isrc/solver -Wall -Wno-parentheses -std=c++98 -O3 -g "
        "-D__STDC_LIMIT_MACROS -D__STDC_FORMAT_MACROS -DNDEBUG",
    ]
    with (sources / "build.log").open("w") as log:
        subprocess.run(command, cwd=sources, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = sources / "bin" / "distqldpc"
    record = {
        "upstream": pin,
        "binary": str(binary),
        "binary_sha256": sha256(binary),
        "source_hashes": {
            str(p.relative_to(sources)): sha256(p)
            for p in sorted((sources / "src").rglob("*"))
            if p.is_file() and p.suffix in (".cc", ".h")
        },
        "patch_sha256": sha256(SPEC / "upstream.patch"),
        "observer_sha256": sha256(SPEC / "observer.h"),
        "compiler": subprocess.check_output([compiler, "--version"], text=True),
        "build_command": command,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "search_threads": 1,
    }
    atomic_json(BUILD_RECORD, record)
    print(f"Built {binary}\nBuild record: {BUILD_RECORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, default=HERE / "cache" / "deps" / "distqldpc")
    parser.add_argument("--compiler", default=os.environ.get("CXX", "c++"))
    parser.add_argument("--build-directory", type=Path, default=HERE / "build" / "distqldpc-source")
    args = parser.parse_args()
    build(args.checkout, args.compiler, args.build_directory)

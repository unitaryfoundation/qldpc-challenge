"""Build pinned native dependencies in an isolated benchmark directory."""

import argparse
import json
import os
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from common import HERE, ROOT, atomic_json, sha256


def run(command, cwd=None, env=None):
    """Run an explicit command and fail on any build error."""
    print(" ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def main(directory):
    """Use local-only prefixes and disable nested M4RI OpenMP workers."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    sources = json.loads((HERE / "sources.json").read_text())
    native = directory / "dist-m4ri"
    if not native.exists():
        run(["git", "clone", sources["dist_m4ri"]["url"], native])
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=native, text=True).strip():
        raise RuntimeError("Refusing to build from a modified dist-m4ri checkout")
    run(["git", "checkout", "--detach", sources["dist_m4ri"]["commit"]], cwd=native)
    archive = directory / "m4ri.tar.gz"
    if not archive.exists():
        with urllib.request.urlopen(sources["m4ri"]["url"], timeout=60) as response:
            archive.write_bytes(response.read())
    if sha256(archive) != sources["m4ri"]["sha256"]:
        raise ValueError("The M4RI release archive does not match its pinned SHA256")
    library = directory / f"m4ri-{sources['m4ri']['version']}"
    if not library.exists():
        with tarfile.open(archive) as stream:
            stream.extractall(directory, filter="data")
    prefix = directory / "m4ri-install"
    environment = dict(os.environ, CFLAGS="-O3", ac_cv_sys_max_cmd_len="196608")
    run(["./configure", f"--prefix={prefix}", "--disable-openmp", "--disable-shared"], cwd=library, env=environment)
    run(["make", "clean"], cwd=library)
    run(["make", "-j4"], cwd=library)
    run(["make", "install"], cwd=library)
    compiler = os.environ.get("CC", "cc")
    # Both benchmark and dist-m4ri use O3 without architecture-specific ISA
    # overrides. M4RI itself is built without nested OpenMP parallelism.
    run(["make", "clean"], cwd=native / "src")
    run(["make", "-j4", "dist_m4ri", f"CC={compiler} -I{prefix}/include -L{prefix}/lib", "OPT=-O3"], cwd=native / "src")
    run(
        [
            sys.executable,
            HERE / "setup_native.py",
            "build_ext",
            "--build-lib",
            HERE / "build",
            "--build-temp",
            HERE / "build" / "temp",
        ],
        cwd=ROOT,
    )
    atomic_json(
        directory / "build.json",
        {
            "sources": sources,
            "m4ri_archive_sha256": sha256(archive),
            "m4ri_binary_sha256": sha256(native / "src" / "dist_m4ri"),
            "m4ri_openmp": False,
            "optimization": "-O3",
            "compiler": compiler,
            "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=HERE / "cache" / "deps")
    main(parser.parse_args().directory)

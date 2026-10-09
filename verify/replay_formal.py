"""Re-run the recorded recipe behind every `formal` certificate (issue #2955, item 1).

A `formal` certificate (`certs/<slug>.json`, `verification.level == "formal"`)
rests on a proof checked by a proof assistant, and it records exactly how to
check it again: the repository and commit, the toolchain, the mathlib revision,
the theorem, and the build command. `check_certs.py` holds the certificate to
its entry by hash on every CI run, but a hash says the certificate is about the
right code, not that the recorded recipe still reaches the theorem. Two decay
modes are invisible to it: the pinned commit stops resolving (a fork branch is
deleted when its upstream PR merges), or the toolchain and mathlib move and the
file no longer builds. This script is what makes the tier a check that runs
rather than one that was run once in a scrollback.

For each formal certificate: clone the recorded repo, check out the recorded
commit, write the recorded toolchain to `lean-toolchain` if the checkout's
differs, run the recorded `build` command verbatim under a wall-clock cap, and
report one line per certificate. A run fails (exit 1) if any certificate's
recipe does not replay. Nothing here changes the board or any certificate:
a red run is information for the maintainers, who decide whether to re-pin
the recipe (the position argued in
fieldnotes/2026-10-05-formal-tier-first-replay-72-12-6.md) and never auto-repoint.

    python verify/replay_formal.py --all                    # every formal certificate
    python verify/replay_formal.py 72-12-6                  # named entries
    python verify/replay_formal.py --all --timeout 1800 --json out.json
    python verify/replay_formal.py --list                   # what would run, no cloning

Requirements on the machine: git with git-lfs, and `elan` on PATH (`lake` is
resolved through it from the recorded toolchain). Network access to the
recorded repository and to the mathlib cache.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "certs")
REQUIRED = ("repo", "commit", "build")


def formal_certs():
    """{slug: cert} for every certificate at level formal with a replay block."""
    out = {}
    for path in sorted(glob.glob(os.path.join(CERTS, "*.json"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, encoding="utf-8") as f:
                cert = json.load(f)
        except (OSError, ValueError):
            continue
        v = cert.get("verification") or {}
        if v.get("level") == "formal":
            out[slug] = cert
    return out


def recipe_problems(v):
    """Why a formal certificate cannot be replayed from what it records."""
    r = v.get("replay") or {}
    missing = [k for k in REQUIRED if not r.get(k)]
    if missing:
        return [f"replay block lacks {missing}"]
    if not r.get("theorem"):
        return ["replay block names no theorem"]
    return []


def _run(cmd, cwd, timeout, log, env=None):
    log.write(f"$ {cmd}\n")
    log.flush()
    t = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout, env=env, check=False)
        return p.returncode, time.monotonic() - t
    except subprocess.TimeoutExpired:
        return "timeout", time.monotonic() - t


def replay(slug, cert, *, timeout, keep=False, workdir=None):
    """Replay one certificate; return a result dict with status in
    {"ok", "clone_failed", "checkout_failed", "build_failed", "timeout",
    "unreplayable"} and the seconds spent."""
    v = cert["verification"]
    probs = recipe_problems(v)
    if probs:
        return {"slug": slug, "status": "unreplayable", "detail": "; ".join(probs), "seconds": 0.0}
    r = v["replay"]
    repo = r["repo"]
    url = repo if "://" in repo or repo.startswith("git@") else f"https://{repo}"
    base = workdir or tempfile.mkdtemp(prefix=f"formal-{slug}-")
    os.makedirs(base, exist_ok=True)
    src = os.path.join(base, "src")
    if os.path.exists(src):
        shutil.rmtree(src)
    logpath = os.path.join(base, "replay.log")
    t0 = time.monotonic()
    result = {"slug": slug, "theorem": r.get("theorem"), "commit": r["commit"], "repo": repo,
              "log": logpath}
    with open(logpath, "w", encoding="utf-8") as log:
        deadline = lambda: max(1, int(timeout - (time.monotonic() - t0)))  # noqa: E731
        rc, _ = _run(f"git clone --quiet --no-checkout {url} src", base, deadline(), log)
        if rc != 0:
            result.update(status="clone_failed" if rc != "timeout" else "timeout")
        else:
            # fetch by hash where the server allows it (GitHub does); a clone
            # already carries every branch, so the checkout is what decides
            rc, _ = _run(f"git fetch --quiet origin {r['commit']} >/dev/null 2>&1; "
                         f"git checkout --quiet {r['commit']}", src, deadline(), log)
            if rc != 0:
                result.update(status="checkout_failed" if rc != "timeout" else "timeout",
                              detail=f"commit {r['commit']} is not reachable from {repo}")
            else:
                tc = r.get("toolchain")
                if tc:
                    have = ""
                    try:
                        with open(os.path.join(src, "lean-toolchain"), encoding="utf-8") as f:
                            have = f.read().strip()
                    except OSError:
                        pass
                    if have != tc:
                        log.write(f"lean-toolchain was {have!r}; writing recorded {tc!r}\n")
                        with open(os.path.join(src, "lean-toolchain"), "w", encoding="utf-8") as f:
                            f.write(tc + "\n")
                rc, _ = _run(r["build"], src, deadline(), log)
                if rc == "timeout":
                    result.update(status="timeout")
                elif rc != 0:
                    result.update(status="build_failed", detail=f"`{r['build']}` exited {rc}")
                else:
                    result.update(status="ok")
    result["seconds"] = round(time.monotonic() - t0, 1)
    if not keep and result["status"] == "ok":
        shutil.rmtree(base, ignore_errors=True)
        result.pop("log", None)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slugs", nargs="*", help="certificates to replay (default: --all)")
    ap.add_argument("--all", action="store_true", help="every formal certificate")
    ap.add_argument("--list", action="store_true", help="print what would run and exit")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="wall-clock cap per certificate, seconds (default 3600)")
    ap.add_argument("--keep", action="store_true", help="keep the checkout and log of every run")
    ap.add_argument("--workdir", default=None, help="parent directory for checkouts (default: temp)")
    ap.add_argument("--json", default=None, help="write the per-certificate results here")
    args = ap.parse_args(argv)
    certs = formal_certs()
    if not certs:
        print("no formal certificates in certs/; nothing to replay")
        return 0
    wanted = certs if (args.all or not args.slugs) else {s: certs[s] for s in args.slugs if s in certs}
    unknown = [s for s in args.slugs if s not in certs]
    if unknown:
        print(f"not formal certificates: {unknown}", file=sys.stderr)
        return 2
    if args.list:
        for slug, cert in wanted.items():
            r = cert["verification"].get("replay") or {}
            print(f"{slug}: {r.get('repo')} @ {str(r.get('commit'))[:12]} toolchain {r.get('toolchain')} "
                  f"theorem {r.get('theorem')} :: {r.get('build')}")
        return 0
    results = []
    for slug, cert in wanted.items():
        wd = os.path.join(args.workdir, slug) if args.workdir else None
        if wd:
            os.makedirs(wd, exist_ok=True)
        res = replay(slug, cert, timeout=args.timeout, keep=args.keep, workdir=wd)
        results.append(res)
        mark = "ok  " if res["status"] == "ok" else "FAIL"
        print(f"{mark} {slug}: {res['status']} in {res['seconds']}s"
              + (f" ({res['detail']})" if res.get("detail") else "")
              + (f"; log {res['log']}" if res.get("log") else ""), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    bad = [r for r in results if r["status"] != "ok"]
    print(f"{len(results) - len(bad)} replayed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

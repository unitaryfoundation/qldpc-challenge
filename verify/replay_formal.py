"""Re-run the recorded recipe behind every `formal` certificate (#2955, item 1).

A formal certificate records repo, commit, toolchain, theorem, and build
command. check_certs.py verifies the hash binding to the entry; this script
verifies the recipe still builds: clone, check out the commit, init LFS,
write the recorded toolchain, run the build under a cap, report one line per
certificate. Exit 1 if any fails. Nothing is modified.

    python verify/replay_formal.py --all [--timeout 1800] [--json out.json]
    python verify/replay_formal.py 72-12-6
    python verify/replay_formal.py --list

--head replays against the repository's current default branch with that
branch's own toolchain instead of the recorded commit and toolchain. A
verbatim replay keeps building the frozen snapshot, so a Lean or mathlib bump
upstream never turns it red; the head replay does. It is advisory and should
not gate anything. Every result also carries the release date of its Lean
toolchain and the commit date of its mathlib revision, from the GitHub API
(--offline skips the lookup), so a green line comes with a date.

Needs git with git-lfs and elan on PATH.
"""
import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "certs")
REQUIRED = ("repo", "commit", "build")
GITHUB_API = "https://api.github.com"
MATHLIB = "leanprover-community/mathlib4"


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


def _replay_url(repo):
    """Construct the clone URL from a recorded repo, or None if unsupported."""
    if not isinstance(repo, str) or not repo or any(c.isspace() for c in repo):
        return None
    if "://" in repo or repo.startswith("git@"):
        url = repo
    else:
        url = f"https://{repo}"
    # Only transports that cannot execute arbitrary helpers are allowed; the
    # commit is validated separately as a 40-hex SHA, so no option injection.
    if "://" in url:
        scheme = url.split("://", 1)[0].lower()
        if scheme not in ("http", "https", "file"):
            return None
    elif not url.startswith("git@"):
        return None
    return url


def recipe_problems(v):
    """Why a formal certificate cannot be replayed from what it records."""
    r = v.get("replay") or {}
    missing = [k for k in REQUIRED if not r.get(k)]
    if missing:
        return [f"replay block lacks {missing}"]
    if not r.get("theorem"):
        return ["replay block names no theorem"]
    commit = r.get("commit")
    if not (isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)):
        return ["replay commit is not a 40-hex SHA"]
    if _replay_url(r.get("repo")) is None:
        return ["replay repo is not a supported URL"]
    return []


def _gh_json(path):
    """GET api.github.com<path> as JSON, or None on any failure.

    GITHUB_TOKEN or GH_TOKEN is sent when set, so CI stays inside its rate limit.
    """
    req = urllib.request.Request(GITHUB_API + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "qldpc-replay-formal"})
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except (urllib.error.URLError, ValueError, OSError):
        return None


def toolchain_tag(toolchain):
    """Split 'leanprover/lean4:v4.30.0-rc2' into (origin, tag); None for other shapes.

    elan also accepts local toolchain names and paths, which have no release date.
    """
    if not toolchain or ":" not in toolchain:
        return None
    origin, tag = toolchain.rsplit(":", 1)
    origin, tag = origin.strip(), tag.strip()
    return (origin, tag) if origin.count("/") == 1 and tag else None


def _age_days(iso, now):
    return (now - datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def toolchain_dates(toolchain, mathlib, now=None, fetch=_gh_json):
    """Date a Lean toolchain and a mathlib revision.

    Returns the toolchain's release date and age, the current Lean release,
    and the mathlib commit date and age. Unknown values are None; nothing
    here can fail a replay.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    out = {"toolchain_date": None, "toolchain_age_days": None, "latest_toolchain": None,
           "latest_toolchain_date": None, "mathlib_date": None, "mathlib_age_days": None}
    tc = toolchain_tag(toolchain)
    if tc:
        origin, tag = tc
        rel = fetch(f"/repos/{origin}/releases/tags/{tag}") or {}
        if rel.get("published_at"):
            out["toolchain_date"] = rel["published_at"][:10]
            out["toolchain_age_days"] = _age_days(rel["published_at"], now)
        latest = fetch(f"/repos/{origin}/releases/latest") or {}
        if latest.get("tag_name"):
            out["latest_toolchain"] = latest["tag_name"]
            out["latest_toolchain_date"] = (latest.get("published_at") or "")[:10] or None
    if mathlib:
        c = fetch(f"/repos/{MATHLIB}/commits/{mathlib}") or {}
        date = ((c.get("commit") or {}).get("committer") or {}).get("date")
        if date:
            out["mathlib_date"] = date[:10]
            out["mathlib_age_days"] = _age_days(date, now)
    return out


def _read_pins(src):
    """Return (lean-toolchain, mathlib rev) as the checkout has them, None when absent."""
    tc = ml = None
    try:
        with open(os.path.join(src, "lean-toolchain"), encoding="utf-8") as f:
            tc = f.read().strip() or None
    except OSError:
        pass
    try:
        with open(os.path.join(src, "lake-manifest.json"), encoding="utf-8") as f:
            for p in json.load(f).get("packages", []):
                if p.get("name") == "mathlib":
                    ml = (p.get("rev") or "")[:12] or None
    except (OSError, ValueError):
        pass
    return tc, ml


def _run(cmd, cwd, timeout, log, env=None):
    # `cmd` may be a shell string (a recorded build command, which is a shell
    # command by construction) or a list of arguments. Lists are executed
    # without a shell so that certificate-controlled values such as the
    # repository URL or commit cannot inject shell syntax. Callers that pass
    # attacker-controlled positionals also put `--end-of-options` ahead of them
    # so a value beginning with `-` is not parsed as an option; commit and repo
    # are validated in recipe_problems before any git call.
    if isinstance(cmd, str):
        display = cmd
        shell = True
    else:
        display = " ".join(str(x) for x in cmd)
        shell = False
    log.write(f"$ {display}\n")
    log.flush()
    t = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=shell, cwd=cwd, stdout=log,
                           stderr=subprocess.STDOUT, timeout=timeout,
                           env=env, check=False)
        return p.returncode, time.monotonic() - t
    except subprocess.TimeoutExpired:
        return "timeout", time.monotonic() - t


def replay(slug, cert, *, timeout, keep=False, workdir=None, head=False):
    """Replay one certificate and return a result dict.

    status is one of "ok", "clone_failed", "checkout_failed", "build_failed",
    "timeout", "unreplayable"; "seconds" is the wall time spent. With
    head=True the checkout is the repository's default branch with its own
    toolchain; "commit" is then the resolved head and "pinned_commit" the
    recorded one.
    """
    v = cert["verification"]
    probs = recipe_problems(v)
    if probs:
        return {"slug": slug, "status": "unreplayable", "detail": "; ".join(probs),
                "seconds": 0.0, "mode": "head" if head else "pinned"}
    r = v["replay"]
    repo = r["repo"]
    url = _replay_url(repo)
    if url is None:
        url = repo
    base = workdir or tempfile.mkdtemp(prefix=f"formal-{slug}-")
    os.makedirs(base, exist_ok=True)
    src = os.path.join(base, "src")
    if os.path.exists(src):
        shutil.rmtree(src)
    logpath = os.path.join(base, "replay.log")
    t0 = time.monotonic()
    result = {"slug": slug, "theorem": r.get("theorem"), "commit": r["commit"], "repo": repo,
              "toolchain": r.get("toolchain"), "mathlib": r.get("mathlib"),
              "mode": "head" if head else "pinned", "log": logpath}
    if head:
        result["pinned_commit"] = r["commit"]
    with open(logpath, "w", encoding="utf-8") as log:
        deadline = lambda: max(1, int(timeout - (time.monotonic() - t0)))  # noqa: E731
        rc, _ = _run(["git", "clone", "--quiet", "--no-checkout", "--end-of-options",
                      url, "src"], base, deadline(), log)
        if rc != 0:
            result.update(status="clone_failed" if rc != "timeout" else "timeout")
        else:
            if head:
                rc, _ = _run(["git", "checkout", "--quiet", "--end-of-options",
                            "origin/HEAD"], src, deadline(), log)
                detail = f"the default branch of {repo} could not be checked out"
            else:
                rc, _ = _run(["git", "fetch", "--quiet", "--end-of-options",
                            "origin", r["commit"]], src, deadline(), log)
                if rc == 0:
                    rc, _ = _run(["git", "checkout", "--quiet", "--end-of-options",
                                r["commit"]], src, deadline(), log)
                detail = f"commit {r['commit']} is not reachable from {repo}"
            if rc != 0:
                result.update(status="checkout_failed" if rc != "timeout" else "timeout",
                              detail=detail)
            else:
                if head:
                    try:
                        result["commit"] = subprocess.check_output(
                            ["git", "rev-parse", "HEAD"], cwd=src, text=True).strip()
                    except subprocess.CalledProcessError:
                        pass
                # without LFS filters `git lfs pull` leaves pointer files
                _run(["git", "lfs", "install", "--local"], src, deadline(), log)
                tc = r.get("toolchain")
                if head:
                    # the branch's own pins are the point of this mode
                    result["toolchain"], result["mathlib"] = _read_pins(src)
                    log.write(f"head {result['commit']}: lean-toolchain {result['toolchain']!r}, "
                              f"mathlib {result['mathlib']!r}\n")
                elif tc:
                    have, _ = _read_pins(src)
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


def _dated(name, date, age):
    if not name:
        return "?"
    return name + (f" ({date}, {age} d old)" if date else "")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("slugs", nargs="*", help="certificates to replay (default: --all)")
    ap.add_argument("--all", action="store_true", help="every formal certificate")
    ap.add_argument("--list", action="store_true", help="print what would run and exit")
    ap.add_argument("--head", action="store_true",
                    help="advisory: build at the repository's current default branch with "
                         "its own toolchain instead of the recorded commit")
    ap.add_argument("--offline", action="store_true",
                    help="skip the GitHub lookups for toolchain and mathlib dates")
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
                  f"mathlib {r.get('mathlib')} theorem {r.get('theorem')} :: {r.get('build')}")
        return 0
    results = []
    for slug, cert in wanted.items():
        wd = os.path.join(args.workdir, slug) if args.workdir else None
        if wd:
            os.makedirs(wd, exist_ok=True)
        res = replay(slug, cert, timeout=args.timeout, keep=args.keep, workdir=wd, head=args.head)
        if not args.offline:
            res.update(toolchain_dates(res.get("toolchain"), res.get("mathlib")))
        results.append(res)
        mark = "ok  " if res["status"] == "ok" else "FAIL"
        print(f"{mark} {slug}: {res['status']} in {res['seconds']}s"
              + (f" ({res['detail']})" if res.get("detail") else "")
              + (f" at head {str(res.get('commit'))[:12]}" if args.head else "")
              + f"; toolchain {_dated(res.get('toolchain'), res.get('toolchain_date'), res.get('toolchain_age_days'))}"
              + (f", current release {res['latest_toolchain']}" if res.get("latest_toolchain") else "")
              + f"; mathlib {_dated(res.get('mathlib'), res.get('mathlib_date'), res.get('mathlib_age_days'))}"
              + (f"; log {res['log']}" if res.get("log") else ""), flush=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)
    bad = [r for r in results if r["status"] != "ok"]
    print(f"{len(results) - len(bad)} replayed, {len(bad)} failed"
          + (" (advisory head replay; nothing gates on it)" if args.head else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

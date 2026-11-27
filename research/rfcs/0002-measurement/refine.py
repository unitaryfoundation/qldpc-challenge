"""Refine the recurrence pairs: first-side added paths only, main-side adds only, CI outcome of the first PR."""

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime

R = sys.argv[1]
REPO = "unitaryfoundation/qldpc-challenge"
CLONE = "."  # run from the repository root
pairs = json.load(open(f"{R}/pairs.json"))
um = json.load(open(f"{R}/unmerged.json"))
op = json.load(open(f"{R}/open.json"))
status = {(p["number"], c["path"]): c["status"] for p in um + op for c in (p.get("codes") or [])}
nkd_cache = {}


def log(*a):
    print(*a, flush=True)


# main-side: which commits ADDED the path
adds = {}
for path in {x["path"] for x in pairs if x["later_kind"] == "main"}:
    out = subprocess.run(
        ["git", "-C", CLONE, "log", "origin/main", "--format=%H %s", "--diff-filter=A", "--", path],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    prs = set()
    for line in out.splitlines():
        import re

        m = re.search(r"\(#(\d+)\)\s*$", line)
        if m:
            prs.add(int(m.group(1)))
    adds[path] = prs

kept = []
for x in pairs:
    if status.get((x["first_pr"], x["path"])) != "added":
        continue
    if x["later_kind"] == "main" and x["later_pr"] not in adds.get(x["path"], set()):
        continue
    if x["later_kind"] in ("unmerged", "open") and status.get((x["later_pr"], x["path"])) != "added":
        continue
    kept.append(x)
log("pairs kept (added -> added):", len(kept), "of", len(pairs))
same = [x for x in kept if x["same_fingerprint"]]
log("same fingerprint:", len(same), "same blob:", sum(1 for x in same if x["same_blob"]))
log("by later kind:", Counter(x["later_kind"] for x in same))

# collapse to (first_pr, path) -> earliest later occurrence per kind
first_keys = sorted({(x["first_pr"], x["path"]) for x in same})
log("distinct refiled (first_pr, path):", len(first_keys), "distinct first PRs:", len({k[0] for k in first_keys}))

# CI outcome of each first PR (and of later unmerged/open PRs)
want = {x["first_pr"] for x in same} | {x["later_pr"] for x in same if x["later_kind"] != "main"}
ci = {}
for i, n in enumerate(sorted(want)):
    try:
        txt = subprocess.run(
            ["gh", "pr", "view", str(n), "-R", REPO, "--json", "statusCheckRollup,closedAt,createdAt,headRefOid"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        d = json.loads(txt)
        rows = d.get("statusCheckRollup") or []
        verify = [
            r
            for r in rows
            if (r.get("name") or r.get("context") or "").lower().startswith(("verify", "gate", "validate"))
        ]
        concl = Counter((r.get("conclusion") or r.get("state") or "").upper() for r in verify)
        dur = None
        for r in verify:
            if r.get("startedAt") and r.get("completedAt"):
                a = datetime.fromisoformat(r["startedAt"].replace("Z", "+00:00"))
                b = datetime.fromisoformat(r["completedAt"].replace("Z", "+00:00"))
                dur = max(dur or 0, (b - a).total_seconds())
        ci[n] = {
            "verify_conclusions": dict(concl),
            "verify_names": sorted({r.get("name") or r.get("context") for r in verify}),
            "max_verify_seconds": dur,
            "all_names": sorted({r.get("name") or r.get("context") or "" for r in rows}),
        }
    except subprocess.CalledProcessError as e:
        ci[n] = {"error": e.stderr.strip()[:120]}
    if i % 40 == 0:
        log("ci", i, "/", len(want))
json.dump(ci, open(f"{R}/ci.json", "w"), indent=1)


def failed(n):
    c = ci.get(n, {}).get("verify_conclusions") or {}
    return any(k in ("FAILURE", "TIMED_OUT", "CANCELLED", "ERROR") for k in c)


def passed(n):
    c = ci.get(n, {}).get("verify_conclusions") or {}
    return bool(c) and all(k == "SUCCESS" for k in c)


summary = {
    "closed_unmerged_code_prs_adding_a_code": len(
        {p["number"] for p in um for c in (p.get("codes") or []) if c["status"] == "added"}
    ),
    "added_paths": sum(1 for p in um for c in (p.get("codes") or []) if c["status"] == "added"),
    "refiled_same_fingerprint_paths": len(first_keys),
    "refiled_first_prs": len({k[0] for k in first_keys}),
    "first_pr_verify_failed": len({k[0] for k in first_keys if failed(k[0])}),
    "first_pr_verify_passed": len({k[0] for k in first_keys if passed(k[0])}),
    "first_pr_verify_unknown": len({k[0] for k in first_keys if not failed(k[0]) and not passed(k[0])}),
}
# per (first_pr, path): classify the later occurrences
cls = Counter()
store_targets = []
for fp, path in first_keys:
    laters = [x for x in same if x["first_pr"] == fp and x["path"] == path]
    kinds = {x["later_kind"] for x in laters}
    merged_same_code = "main" in kinds
    f_failed = failed(fp)
    for x in laters:
        if x["later_kind"] == "main":
            continue
        fd = (x.get("first_nkd") or [None, None, None])[2] if not x["same_blob"] else "same"
        ld = (x.get("later_nkd") or [None, None, None])[2] if not x["same_blob"] else "same"
        d_rel = "same" if x["same_blob"] or fd == ld else ("lower" if (ld or 0) < (fd or 0) else "higher")
        cls[(f_failed, x["later_kind"], d_rel, failed(x["later_pr"]))] += 1
        if f_failed and d_rel in ("same", "higher"):
            store_targets.append(
                {
                    **x,
                    "later_failed": failed(x["later_pr"]),
                    "later_verify_seconds": ci.get(x["later_pr"], {}).get("max_verify_seconds"),
                }
            )
    if merged_same_code:
        cls[("merged later", f_failed)] += 1
summary["classes"] = {str(k): v for k, v in sorted(cls.items(), key=str)}
summary["store_targets"] = len(store_targets)
summary["store_targets_distinct_later_prs"] = len({x["later_pr"] for x in store_targets})
secs = [x["later_verify_seconds"] for x in store_targets if x["later_verify_seconds"]]
summary["store_targets_later_verify_seconds"] = {
    "n": len(secs),
    "sum_min": round(sum(secs) / 60, 1),
    "median_min": round(sorted(secs)[len(secs) // 2] / 60, 1) if secs else None,
}
summary["store_targets_same_author"] = sum(1 for x in store_targets if x["first_author"] == x["later_author"])
summary["store_targets_same_blob"] = sum(1 for x in store_targets if x["same_blob"])
json.dump({"summary": summary, "store_targets": store_targets}, open(f"{R}/refined.json", "w"), indent=1)
log(json.dumps(summary, indent=1))

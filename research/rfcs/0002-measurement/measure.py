"""Recurrence of codes/ paths from closed-unmerged PRs in later PRs (RFC 0002 evidence).

Usage: uv run python research/rfcs/0002-measurement/measure.py <out-dir>
Then:  uv run python research/rfcs/0002-measurement/refine.py <out-dir>
Both read the GitHub API through ``gh`` and the local ``origin/main``.
"""

import base64
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = "unitaryfoundation/qldpc-challenge"
CLONE = Path.cwd()  # run from the repository root
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(CLONE))

from verify import qldpc_verify as qv  # noqa: E402


def gh(*args):
    return subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True).stdout


def log(*a):
    print(*a, flush=True)


# 1. closed-unmerged PRs
unmerged = []
for page in range(1, 6):
    txt = gh(
        "-X",
        "GET",
        "search/issues",
        "-f",
        f"q=repo:{REPO} is:pr is:closed is:unmerged",
        "-f",
        "per_page=100",
        "-f",
        f"page={page}",
    )
    items = json.loads(txt)["items"]
    if not items:
        break
    for it in items:
        unmerged.append(
            {
                "number": it["number"],
                "created_at": it["created_at"],
                "closed_at": it["closed_at"],
                "author": it["user"]["login"],
                "title": it["title"],
            }
        )
log("closed-unmerged PRs:", len(unmerged))

# 2. open PRs
txt = subprocess.run(
    ["gh", "pr", "list", "-R", REPO, "--state", "open", "--limit", "200", "--json", "number,createdAt,author,title"],
    capture_output=True,
    text=True,
    check=True,
).stdout
open_prs = [
    {
        "number": p["number"],
        "created_at": p["createdAt"],
        "closed_at": None,
        "author": p["author"]["login"],
        "title": p["title"],
    }
    for p in json.loads(txt)
]
log("open PRs:", len(open_prs))


# 3. files per PR
def files_of(number):
    out = []
    for page in range(1, 10):
        txt = gh(f"repos/{REPO}/pulls/{number}/files?per_page=100&page={page}")
        items = json.loads(txt)
        if not items:
            break
        for f in items:
            if f["filename"].startswith("codes/") and f["filename"].endswith(".json"):
                out.append({"path": f["filename"], "sha": f["sha"], "status": f["status"]})
        if len(items) < 100:
            break
    return out


for lst, name in ((unmerged, "unmerged"), (open_prs, "open")):
    for i, p in enumerate(lst):
        try:
            p["codes"] = files_of(p["number"])
        except subprocess.CalledProcessError as e:
            p["codes"] = None
            p["error"] = e.stderr.strip()[:200]
        if i % 50 == 0:
            log(name, i, "/", len(lst))
(OUT / "unmerged.json").write_text(json.dumps(unmerged, indent=1))
(OUT / "open.json").write_text(json.dumps(open_prs, indent=1))

unmerged_code = [p for p in unmerged if p.get("codes")]
log("closed-unmerged PRs touching codes/:", len(unmerged_code), "paths:", sum(len(p["codes"]) for p in unmerged_code))

# 4. main history for every slug seen in an unmerged PR
slugs = sorted({c["path"] for p in unmerged_code for c in p["codes"]})
main_hist = {}
for s in slugs:
    txt = subprocess.run(
        ["git", "-C", str(CLONE), "log", "origin/main", "--format=%H %cI %s", "--diff-filter=AM", "--", s],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    rows = []
    for line in txt.splitlines():
        h, when, subj = line.split(" ", 2)
        m = re.search(r"\(#(\d+)\)\s*$", subj)
        blob = subprocess.run(
            ["git", "-C", str(CLONE), "rev-parse", f"{h}:{s}"], capture_output=True, text=True, check=False
        ).stdout.strip()
        rows.append({"commit": h, "when": when, "pr": int(m.group(1)) if m else None, "blob": blob})
    main_hist[s] = rows
log("slugs with main history:", sum(1 for s in slugs if main_hist[s]), "/", len(slugs))

# 5. recurrence
by_path = defaultdict(list)  # path -> [(kind, pr dict, file dict)]
for p in unmerged_code:
    for c in p["codes"]:
        by_path[c["path"]].append(("unmerged", p, c))
for p in open_prs:
    for c in p.get("codes") or []:
        by_path[c["path"]].append(("open", p, c))
for s, rows in main_hist.items():
    for r in rows:
        by_path[s].append(
            (
                "main",
                {"number": r["pr"], "created_at": r["when"], "closed_at": r["when"]},
                {"sha": r["blob"], "status": "merged"},
            )
        )

pairs = []
for p in unmerged_code:
    for c in p["codes"]:
        for kind, q, cq in by_path[c["path"]]:
            if kind == "unmerged" and q["number"] == p["number"]:
                continue
            if q["created_at"] <= p["created_at"]:
                continue
            pairs.append(
                {
                    "path": c["path"],
                    "first_pr": p["number"],
                    "first_author": p["author"],
                    "first_closed": p["closed_at"],
                    "later_kind": kind,
                    "later_pr": q["number"],
                    "later_author": q.get("author"),
                    "later_created": q["created_at"],
                    "same_blob": cq["sha"] == c["sha"],
                    "first_sha": c["sha"],
                    "later_sha": cq["sha"],
                }
            )
log("recurrence pairs:", len(pairs), "same blob:", sum(1 for x in pairs if x["same_blob"]))


# 6. fingerprints for different-blob pairs
def fingerprint_of_blob(sha):
    txt = gh(f"repos/{REPO}/git/blobs/{sha}")
    raw = base64.b64decode(json.loads(txt)["content"])
    doc = json.loads(raw)
    if doc.get("code_type") != "CSS":
        return ("non-CSS", doc.get("n"), doc.get("k"), (doc.get("distance") or {}).get("d"))
    n = doc["n"]
    HX = qv._matrix(doc["checks"]["X"], n)
    HZ = qv._matrix(doc["checks"]["Z"], n)
    return (qv.css_fingerprint(HX, HZ), n, doc.get("k"), (doc.get("distance") or {}).get("d"))


fp_cache = {}
for x in pairs:
    if x["same_blob"]:
        x["same_fingerprint"] = True
        continue
    for key in ("first_sha", "later_sha"):
        if x[key] not in fp_cache:
            try:
                fp_cache[x[key]] = fingerprint_of_blob(x[key])
            except Exception as e:  # noqa: BLE001
                fp_cache[x[key]] = ("error", str(e)[:100])
    a, b = fp_cache[x["first_sha"]], fp_cache[x["later_sha"]]
    x["first_nkd"] = a[1:]
    x["later_nkd"] = b[1:]
    x["same_fingerprint"] = a[0] == b[0] and a[0] not in ("non-CSS", "error")
log(
    "different-blob pairs with the same fingerprint:",
    sum(1 for x in pairs if not x["same_blob"] and x["same_fingerprint"]),
)
(OUT / "pairs.json").write_text(json.dumps(pairs, indent=1))

# summary
first_prs = {x["first_pr"] for x in pairs}
summary = {
    "closed_unmerged_prs": len(unmerged),
    "closed_unmerged_code_prs": len(unmerged_code),
    "closed_unmerged_code_paths": sum(len(p["codes"]) for p in unmerged_code),
    "open_prs": len(open_prs),
    "pairs": len(pairs),
    "pairs_same_blob": sum(1 for x in pairs if x["same_blob"]),
    "pairs_same_fingerprint_diff_blob": sum(1 for x in pairs if not x["same_blob"] and x["same_fingerprint"]),
    "pairs_different_code": sum(1 for x in pairs if not x["same_fingerprint"]),
    "first_prs_with_any_recurrence": len(first_prs),
    "by_later_kind": dict(
        sorted(((k, sum(1 for x in pairs if x["later_kind"] == k)) for k in {x["later_kind"] for x in pairs}))
    ),
    "same_fingerprint_by_later_kind": dict(
        sorted(
            (
                (k, sum(1 for x in pairs if x["later_kind"] == k and x["same_fingerprint"]))
                for k in {x["later_kind"] for x in pairs}
            )
        )
    ),
    "same_author_same_fingerprint": sum(
        1 for x in pairs if x["same_fingerprint"] and x["first_author"] == x["later_author"]
    ),
}
(OUT / "summary.json").write_text(json.dumps(summary, indent=1))
log(json.dumps(summary, indent=1))

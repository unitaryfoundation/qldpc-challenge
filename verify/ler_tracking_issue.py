"""Body of the tracking issue for failed and unverifiable LER replication points (issue #2820).

The weekly ler-weekly workflow re-measures every point of every measured-rate
claim (verify/ler_replicate.py) and writes receipts/ler/<slug>.json. A point
whose replica disagrees with the claim is recorded as failed, one the budget
could not check to the admissibility bound as unverifiable; the entry page
shows both and neither counts toward the frontier. This prints one issue body
listing those points, so a contradicted claim is visible without opening each
entry page. The workflow opens, edits, or closes the issue from the summary
line; this script reports and changes nothing.

A receipt whose claim digest no longer matches the entry (the claim was edited
after the measurement) or whose entry is gone reads as pending on the site and
is left out here too; the footer counts them.

Usage:
  python verify/ler_tracking_issue.py [--root DIR]            # body on stdout
  python verify/ler_tracking_issue.py [--root DIR] --out BODY  # body to a file,
        one line on stdout: points=N failed=F unverifiable=U stale=S receipts=R
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ler_receipts as lr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKER = "<!-- ler-tracking-issue -->"
TITLE = "LER replication: failed and unverifiable points"
REPORTED = ("failed", "unverifiable")


def _claimed_points(doc):
    """(basis, rate string) -> claimed point, from the entry's circuit.ler block."""
    out = {}
    for side, points in ((doc.get("circuit") or {}).get("ler") or {}).items():
        if isinstance(points, list):
            for q in points:
                if isinstance(q, dict) and "p" in q:
                    out[(side, str(q["p"]))] = q
    return out


def collect(root=ROOT):
    """Collect the reported points, the stale receipts, and the receipt count under ``root``."""
    rows, stale, receipts = [], [], 0
    for path in sorted(glob.glob(os.path.join(root, lr.RECEIPT_DIR, "*.json"))):
        receipts += 1
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        slug = rec.get("slug") or os.path.splitext(os.path.basename(path))[0]
        doc_path = os.path.join(root, "codes", slug + ".json")
        if not os.path.exists(doc_path):
            stale.append((slug, "entry removed"))
            continue
        with open(doc_path, encoding="utf-8") as f:
            doc = json.load(f)
        if rec.get("claim_digest") != lr.claim_digest(doc, os.path.join(root, "circuits", slug)):
            stale.append((slug, "claim edited after the measurement"))
            continue
        claimed = _claimed_points(doc)
        for side, points in (rec.get("points") or {}).items():
            for p, r in (points or {}).items():
                if r.get("status") not in REPORTED:
                    continue
                q = claimed.get((side, str(p)))
                claimed_p = r.get("claimed_p_shot")
                if claimed_p is None and q and q.get("shots"):
                    claimed_p = q["failures"] / q["shots"]
                rows.append(
                    {
                        "slug": slug,
                        "basis": side,
                        "p": str(p),
                        "status": r["status"],
                        "claimed_p_shot": claimed_p,
                        "replica_p_shot": r.get("replica_p_shot"),
                        "replica_shots": r.get("replica_shots", 0),
                        "replica_failures": r.get("replica_failures", 0),
                        "detectable_factor": r.get("detectable_factor"),
                        "measured_at": rec.get("measured_at"),
                    }
                )
    rows.sort(key=lambda r: (REPORTED.index(r["status"]), r["slug"], r["basis"], -float(r["p"])))
    return rows, stale, receipts


def _rate(x):
    return "n/a" if x is None else f"{x:.3g}"


def body(rows, stale, receipts):
    """Render the issue body: a marker, the explanation, one table row per point, a footer."""
    lines = [
        MARKER,
        "Points of measured-rate claims whose weekly re-measurement (`ler-weekly`, "
        "`verify/ler_replicate.py`) disagreed with the claim (failed) or could not reach the "
        "admissibility bound inside its budget (unverifiable). A failed point is a claim on the board "
        "that an independent replica contradicts. The entry page shows the same status, and neither "
        "kind counts toward the frontier. Written from `receipts/ler/` by "
        "`verify/ler_tracking_issue.py`, which reports and changes nothing (issue #2820).",
        "",
    ]
    if rows:
        lines += [
            "| entry | basis | p | status | claimed p_shot | replica p_shot | replica shots (failures) | "
            "detectable factor | measured at |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| `{r['slug']}` | {r['basis']} | {r['p']} | {r['status']} | "
                f"{_rate(r['claimed_p_shot'])} | {_rate(r['replica_p_shot'])} | "
                f"{r['replica_shots']} ({r['replica_failures']}) | "
                f"{r['detectable_factor'] if r['detectable_factor'] is not None else 'n/a'} | "
                f"{r['measured_at'] or 'n/a'} |"
            )
        lines.append("")
    n_failed = sum(r["status"] == "failed" for r in rows)
    entries = len({r["slug"] for r in rows})
    lines.append(
        f"{len(rows)} point(s) ({n_failed} failed, {len(rows) - n_failed} unverifiable) across "
        f"{entries} entr{'y' if entries == 1 else 'ies'}, from {receipts} receipt(s)."
    )
    if stale:
        lines.append(
            f"{len(stale)} receipt(s) left out as stale, pending on the site until the next run: "
            + ", ".join(f"`{slug}` ({why})" for slug, why in stale)
            + "."
        )
    return "\n".join(lines) + "\n"


def summary(rows, stale, receipts):
    """Render the one-line summary the workflow parses."""
    n_failed = sum(r["status"] == "failed" for r in rows)
    return (
        f"points={len(rows)} failed={n_failed} unverifiable={len(rows) - n_failed} "
        f"stale={len(stale)} receipts={receipts}"
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--out", help="write the body here and print only the summary line")
    a = ap.parse_args(argv)
    rows, stale, receipts = collect(os.path.abspath(a.root))
    text = body(rows, stale, receipts)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(summary(rows, stale, receipts))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

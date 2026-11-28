#!/usr/bin/env python3
r"""Aggregate direction 8's per-parent reports into the board-wide and per-pool tables.

    uv run python research/campaigns/cc-v032-direction8-applicability/aggregate.py \\
        research/candidates/<run>/reports.jsonl --out result-table.json [--markdown]

Per pool (ALL, C2, C3, C4, C6) and per move family: parents asked, total
candidate domain, derived children, usable children, parents with at least
one usable child, and the dominant blocker (the refusal or screen that
accounts for most of the non-usable candidates, with its share). Records
with an error are counted and left out of the tables.
"""

import argparse
import collections
import json

FAMILIES = ("C-DELETE-CHECK", "E-PEEL", "E-PUNCTURE", "E-GRAFT", "P-REBASE", "E-EXTEND")
POOLS = ("ALL", "C2", "C3", "C4", "C6")


LONG = {
    "DEL": "C-DELETE-CHECK",
    "PEEL": "E-PEEL",
    "PUN": "E-PUNCTURE",
    "GRAFT": "E-GRAFT",
    "REB": "P-REBASE",
    "EXT": "E-EXTEND",
}


def normalize(record):
    """Expand the compact committed form (short family keys, elided fields) to the runner's form."""
    fams = {}
    for key, e in record.get("families", {}).items():
        fam = LONG.get(key, key)
        if not e.get("enabled", True):
            fams[fam] = {"enabled": False}
            continue
        fams[fam] = {
            "enabled": True,
            "domain": e["domain"],
            "derived": e["derived"],
            "usable": e["usable"],
            "blocking": e.get("blocking"),
            "best_child_w": e.get("best_child_w"),
            "refusals": e.get("refusals") or {},
            "screens": e.get("screens") or {},
        }
    record = dict(record)
    record["families"] = fams
    return record


def legend_for(path):
    """Return the reason-code legend beside a reports file (``result-legend.json``), or {}."""
    import os

    side = os.path.join(os.path.dirname(os.path.abspath(path)), "result-legend.json")
    try:
        with open(side, encoding="utf-8") as f:
            return json.load(f).get("codes", {})
    except (OSError, ValueError):
        return {}


def expand(record, legend):
    """Replace reason codes by the consumer's own reason text."""
    for e in record["families"].values():
        if not e.get("enabled"):
            continue
        e["refusals"] = {legend.get(k, k): v for k, v in e["refusals"].items()}
        e["screens"] = {legend.get(k, k): v for k, v in e["screens"].items()}
        if e.get("blocking"):
            e["blocking"] = legend.get(e["blocking"], e["blocking"])
    return record


def load(path):
    legend = legend_for(path)
    rows = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if line:
                rows.append(expand(normalize(json.loads(line)), legend))
    return rows


def table(rows):
    out = {"parents": {}, "errors": sum(1 for r in rows if "error" in r), "families": {}}
    good = [r for r in rows if "error" not in r]
    for pool in POOLS:
        members = [r for r in good if pool == "ALL" or pool in (r.get("pools") or [])]
        out["parents"][pool] = len(members)
        for fam in FAMILIES:
            asked = [r for r in members if r["families"].get(fam, {}).get("enabled")]
            reasons = collections.Counter()
            domain = derived = usable = with_usable = 0
            for r in asked:
                e = r["families"][fam]
                domain += e["domain"]
                derived += e["derived"]
                usable += e["usable"]
                with_usable += 1 if e["usable"] > 0 else 0
                for name, count in list(e.get("refusals", {}).items()) + list(e.get("screens", {}).items()):
                    reasons[name] += count
            top = reasons.most_common(1)[0] if reasons else (None, 0)
            blocked = domain - usable
            out["families"].setdefault(fam, {})[pool] = {
                "parents_asked": len(asked),
                "domain": domain,
                "derived": derived,
                "usable": usable,
                "parents_with_usable": with_usable,
                "dominant_blocker": top[0],
                "dominant_blocker_share": round(top[1] / blocked, 3) if blocked else None,
                "blockers": dict(reasons.most_common(6)),
            }
    return out


def markdown(agg):
    lines = []
    for pool in POOLS:
        lines.append(f"\n{pool}: {agg['parents'][pool]} parents\n")
        lines.append(
            "| family | parents asked | domain | derived | usable | parents with a usable child | "
            "dominant blocker (share of blocked) |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for fam in FAMILIES:
            e = agg["families"][fam][pool]
            share = f" ({e['dominant_blocker_share']:.0%})" if e["dominant_blocker_share"] is not None else ""
            lines.append(
                f"| {fam} | {e['parents_asked']} | {e['domain']:,} | {e['derived']:,} | {e['usable']:,} | "
                f"{e['parents_with_usable']} | {e['dominant_blocker'] or '-'}{share} |"
            )
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports")
    ap.add_argument("--out", default=None)
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args(argv)
    rows = load(args.reports)
    agg = table(rows)
    agg["records"] = len(rows)
    agg["seconds_total"] = round(sum(r.get("seconds", 0) for r in rows))
    agg["n_range"] = [min(r["n"] for r in rows), max(r["n"] for r in rows)] if rows else None
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(agg, f, indent=1)
            f.write("\n")
    print(markdown(agg) if args.markdown else json.dumps(agg, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

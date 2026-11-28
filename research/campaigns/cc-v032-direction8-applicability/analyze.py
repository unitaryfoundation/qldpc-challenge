r"""Derived readings of direction 8's per-parent reports, beyond aggregate.py's tables.

    uv run python research/campaigns/cc-v032-direction8-applicability/analyze.py \
        <reports.jsonl ...> [--out result-readings.json]

Answers, over the merged records: how many parents have no usable child in
any family (and what blocks them), the share of parents with a usable child
per family by n band, the E-PEEL precondition (a qubit of column weight 1 in
some sector) against the peel yield, the E-EXTEND yield, and, for P-REBASE
and E-GRAFT, how often the best derived child is lighter than the parent.
"""

import argparse
import collections
import json

FAMILIES = ("C-DELETE-CHECK", "E-PEEL", "E-PUNCTURE", "E-GRAFT", "P-REBASE", "E-EXTEND")
BANDS = ((1, 50), (51, 100), (101, 200), (201, 500), (501, 1000))


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


def load(paths):
    rows = []
    for path in paths:
        legend = legend_for(path)
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if line:
                    rows.append(expand(normalize(json.loads(line)), legend))
    return [r for r in rows if "error" not in r]


def band_of(n):
    for lo, hi in BANDS:
        if lo <= n <= hi:
            return f"{lo}-{hi}"
    return "other"


def readings(rows):
    out = {"parents": len(rows)}
    # dead parents: no usable child in any asked family
    dead = []
    for r in rows:
        fams = r["families"]
        if all(not e.get("enabled") or e["usable"] == 0 for e in fams.values()):
            blockers = collections.Counter()
            for e in fams.values():
                if e.get("enabled") and e.get("blocking"):
                    blockers[e["blocking"]] += 1
            dead.append(
                {"slug": r["slug"], "n": r["n"], "k": r["k"], "d": r["d"], "w": r["w"], "blockers": dict(blockers)}
            )
    out["dead_parents"] = {
        "count": len(dead),
        "by_n_band": dict(collections.Counter(band_of(x["n"]) for x in dead)),
        "examples": sorted(dead, key=lambda x: x["n"])[:12],
    }
    # share of parents with a usable child, per family and n band
    share = {}
    for fam in FAMILIES:
        share[fam] = {}
        for lo, hi in BANDS:
            asked = [r for r in rows if lo <= r["n"] <= hi and r["families"].get(fam, {}).get("enabled")]
            if not asked:
                continue
            hit = sum(1 for r in asked if r["families"][fam]["usable"] > 0)
            frac = sum(r["families"][fam]["usable"] for r in asked) / max(
                1, sum(r["families"][fam]["domain"] for r in asked)
            )
            share[fam][f"{lo}-{hi}"] = {
                "parents": len(asked),
                "with_usable": hit,
                "usable_share_of_domain": round(frac, 4),
            }
    out["usable_by_family_and_band"] = share
    # E-PEEL precondition: column weight 1 somewhere
    peelable = [r for r in rows if any(r["parent"]["column_weight"][s]["min"] == 1 for s in ("X", "Z"))]
    peel_hits = [r for r in rows if r["families"]["E-PEEL"]["usable"] > 0]
    out["peel"] = {
        "parents_with_a_column_weight_1_qubit": len(peelable),
        "parents_with_a_usable_peel": len(peel_hits),
        "usable_peels_without_the_precondition": sum(1 for r in peel_hits if r not in peelable),
    }
    # E-EXTEND
    ext = [r for r in rows if r["families"]["E-EXTEND"]["usable"] > 0]
    out["extend"] = {
        "parents_with_a_usable_extension": len(ext),
        "usable_extensions": sum(r["families"]["E-EXTEND"]["usable"] for r in ext),
        "examples": [
            {"slug": r["slug"], "n": r["n"], "k": r["k"], "d": r["d"], "usable": r["families"]["E-EXTEND"]["usable"]}
            for r in sorted(ext, key=lambda x: x["n"])[:10]
        ],
    }
    # weight shedding: best derived child lighter than the parent
    shed = {}
    for fam in ("P-REBASE", "E-GRAFT", "C-DELETE-CHECK", "E-PUNCTURE"):
        asked = [
            r for r in rows if r["families"].get(fam, {}).get("enabled") and r["families"][fam].get("best_child_w")
        ]
        lighter = [r for r in asked if r["families"][fam]["best_child_w"] < r["w"]]
        shed[fam] = {
            "parents_asked": len(asked),
            "parents_with_a_lighter_child": len(lighter),
            "examples": [
                {"slug": r["slug"], "w": r["w"], "best_child_w": r["families"][fam]["best_child_w"]}
                for r in lighter[:8]
            ],
        }
    out["lighter_children"] = shed
    # parents with weight-1 logicals already (distance 1 placeholders)
    out["parents_with_weight_one_logicals"] = sum(
        1 for r in rows if any(r["parent"]["weight_one_logicals"].get(s, 0) for s in ("X", "Z"))
    )
    out["seconds_total"] = round(sum(r.get("seconds", 0) for r in rows))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("reports", nargs="+")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    out = readings(load(args.reports))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
            f.write("\n")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

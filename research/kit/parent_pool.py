"""A stable parent-code manifest for code-calculus consumers (issue #7440).

The code-calculus campaigns under ``research/campaigns/cc-*`` and
``research/reachability_campaign.py`` each scraped ``codes/*.json`` on their
own to pick parents. This module is the one export they can read instead:
one JSON document, ``schema_version`` 1, validated by
``research/kit/parent_pool.schema.json``, with one record per board entry
that holds everything a consumer needs and nothing it has to re-derive.

Each parent record carries:

* ``slug``, ``name``, ``n``, ``k``, ``d``, ``w``, ``code_type``, ``family``,
  ``weight_class``, ``locality_class``, ``kd2_over_n``;
* ``checks``: the entry's own block (``X`` and ``Z`` supports for a CSS code,
  ``S`` generators for a stabilizer one), so the record itself is the
  presentation ``CodeState.from_challenge`` takes (it reads ``n``, ``k``,
  and ``checks``; `calculus_bridge.state_from_entry` loads a record as it
  loads an entry);
* ``checks_sha256``: the binding hash (``verify/qldpc_verify.checks_sha256``,
  which code-calculus's ``machine.ingestion.checks_sha256`` reproduces);
* ``distance``: the entry's block (``d``, per-side ``value``, ``confidence``,
  and ``witness``) plus ``tier`` and ``lower_bound`` from ``certs/<slug>.json``
  as the site reads them: ``exact`` when an honored certificate proves d,
  ``lower_bounded`` when a partial certificate proves ``lower_bound <= d``,
  ``upper_bound`` otherwise;
* ``locality``: ``layers`` and ``interaction_radius`` when the entry has a
  layout (the coordinates themselves are not copied; a consumer that needs
  them reads the entry);
* ``provenance``: ``construction``, ``origin``, ``model``, ``date``, and
  ``authors`` as the entry states them.

The manifest header records ``generated_at``, ``board_commit`` (the checkout's
HEAD), the filters applied, and ``count``. Filters: ``n_min``/``n_max``,
``k_min``, ``d_min``, ``w_max``, ``families``, ``localities``, ``code_types``,
``tiers``, ``slugs``, and ``since_commit``, which keeps the entries whose file
was added to ``codes/`` after that commit (``git diff --diff-filter=A``), the
"fresh parents since the last campaign" question.

    uv run python research/kit/parent_pool.py --n-max 200 --family bivariate-bicycle --out parents.json
    uv run python research/kit/parent_pool.py --since-commit <sha> --code-type CSS --tier exact
    uv run python research/kit/parent_pool.py --summary

Nothing here is evidence: every distance is the board's claim, an upper
bound unless ``tier`` says otherwise, and a child derived from a parent is
gated like any other candidate.
"""

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "verify"), os.path.join(_ROOT, "site")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import qldpc_verify  # noqa: E402
from build import cert_consistent, cert_lower_bounds  # noqa: E402

SCHEMA_VERSION = 1
SCHEMA_PATH = os.path.join(_HERE, "parent_pool.schema.json")
CODES = os.path.join(_ROOT, "codes")
CERTS = os.path.join(_ROOT, "certs")
TIERS = ("exact", "lower_bounded", "upper_bound")


def _git(root, *args):
    try:
        out = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def board_commit(root=None):
    """Return the checkout's HEAD, or None outside a git checkout."""
    out = _git(root or _ROOT, "rev-parse", "HEAD")
    return out.strip() if out else None


def added_since(commit, root=None, codes_rel="codes"):
    """Return the slugs whose ``codes/<slug>.json`` was added after ``commit`` (``git diff --diff-filter=A``)."""
    out = _git(root or _ROOT, "diff", "--name-only", "--diff-filter=A", f"{commit}..HEAD", "--", codes_rel)
    if out is None:
        raise ValueError(f"git could not diff {commit}..HEAD under {codes_rel}/; is it a commit of this checkout?")
    slugs = set()
    for line in out.splitlines():
        base = os.path.basename(line.strip())
        if base.endswith(".json"):
            slugs.add(base[:-5])
    return slugs


def cert_of(slug, certs_dir=None):
    """Return ``certs/<slug>.json`` as a dict, or None."""
    path = os.path.join(certs_dir or CERTS, f"{slug}.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def distance_block(doc, cert, slug):
    """Return the entry's distance block with ``tier`` and ``lower_bound`` as the site derives them."""
    dist = dict(doc.get("distance") or {})
    tier = "upper_bound"
    lower = None
    if cert and cert.get("d_exact") and cert_consistent(cert, doc):
        tier = "exact"
        lower = dist.get("d")
    elif cert:
        lb = cert_lower_bounds(cert, doc, slug).get("d")
        if lb is not None:
            tier = "lower_bounded"
            lower = lb
    dist["tier"] = tier
    dist["lower_bound"] = lower
    return dist


def record_of(doc, report, slug, *, cert=None, include_checks=True):
    """Return one parent record for a board entry and its verifier report."""
    comp = report.get("computed") or {}
    n, k, d = doc["n"], doc["k"], doc["distance"]["d"]
    w = comp.get("max_check_weight")
    loc = doc.get("locality") or {}
    prov = doc.get("provenance") or {}
    out = {
        "slug": slug,
        "name": doc.get("name"),
        "n": n,
        "k": k,
        "d": d,
        "w": w,
        "code_type": doc.get("code_type", "CSS"),
        "family": doc.get("family"),
        "weight_class": comp.get("weight_class"),
        "locality_class": comp.get("locality_class"),
        "kd2_over_n": round(k * d * d / n, 4) if n else None,
        "checks_sha256": qldpc_verify.checks_sha256(doc),
        "distance": distance_block(doc, cert, slug),
        "locality": {"layers": loc.get("layers"), "interaction_radius": loc.get("interaction_radius")}
        if loc.get("coordinates")
        else None,
        "provenance": {
            "construction": prov.get("construction"),
            "origin": prov.get("origin"),
            "model": prov.get("model"),
            "date": prov.get("date"),
            "authors": prov.get("authors"),
        },
    }
    if include_checks:
        out["checks"] = doc["checks"]
    return out


def _passes(rec, f):
    if f.get("code_types") and rec["code_type"] not in f["code_types"]:
        return False
    if f.get("n_min") is not None and rec["n"] < f["n_min"]:
        return False
    if f.get("n_max") is not None and rec["n"] > f["n_max"]:
        return False
    if f.get("k_min") is not None and rec["k"] < f["k_min"]:
        return False
    if f.get("d_min") is not None and rec["d"] < f["d_min"]:
        return False
    if f.get("w_max") is not None and (rec["w"] is None or rec["w"] > f["w_max"]):
        return False
    if f.get("families") and rec["family"] not in f["families"]:
        return False
    if f.get("localities") and rec["locality_class"] not in f["localities"]:
        return False
    if f.get("tiers") and rec["distance"]["tier"] not in f["tiers"]:
        return False
    if f.get("slugs") is not None and rec["slug"] not in f["slugs"]:
        return False
    return True


def build(
    *,
    codes_dir=None,
    certs_dir=None,
    root=None,
    n_min=None,
    n_max=None,
    k_min=None,
    d_min=None,
    w_max=None,
    families=None,
    localities=None,
    code_types=None,
    tiers=None,
    slugs=None,
    since_commit=None,
    include_checks=True,
):
    """Return the manifest for the board under ``codes_dir`` after the filters.

    The entries come from ``qldpc_verify.board_reports`` (the memoized
    structural pass the gate and the site share), so ``w`` and the classes
    are the verifier's. An entry whose report is not ok is left out, as the
    site leaves it out.
    """
    codes_dir = codes_dir or CODES
    root = root or _ROOT
    filters = {
        "n_min": n_min,
        "n_max": n_max,
        "k_min": k_min,
        "d_min": d_min,
        "w_max": w_max,
        "families": sorted(families) if families else None,
        "localities": sorted(localities) if localities else None,
        "code_types": sorted(code_types) if code_types else None,
        "tiers": sorted(tiers) if tiers else None,
        "slugs": sorted(slugs) if slugs is not None else None,
        "since_commit": since_commit,
    }
    keep = set(slugs) if slugs is not None else None
    if since_commit:
        fresh = added_since(since_commit, root, os.path.relpath(codes_dir, root))
        keep = fresh if keep is None else keep & fresh
    f = dict(filters, slugs=keep)
    parents = []
    skipped = []
    for e in qldpc_verify.board_reports(codes_dir):
        doc, rep = e.get("doc"), e.get("report")
        slug = os.path.basename(e["path"])[:-5]
        if doc is None or rep is None or not rep.get("ok", False):
            skipped.append(slug)
            continue
        if keep is not None and slug not in keep:
            continue
        rec = record_of(doc, rep, slug, cert=cert_of(slug, certs_dir), include_checks=include_checks)
        if _passes(rec, f):
            parents.append(rec)
    parents.sort(key=lambda r: (r["n"], r["k"], r["d"], r["slug"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "board_commit": board_commit(root),
        "codes": os.path.relpath(codes_dir, root),
        "filters": filters,
        "count": len(parents),
        "skipped_not_ok": sorted(skipped),
        "parents": parents,
    }


def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate(manifest):
    """Return the schema violations of a manifest (empty when it validates); needs ``jsonschema``."""
    import jsonschema

    v = jsonschema.Draft7Validator(schema())
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}" for err in v.iter_errors(manifest)
    ]


def summary(manifest, limit=20):
    """Return a short human listing of a manifest."""
    lines = [
        f"parent pool: {manifest['count']} entries from {manifest['codes']} at "
        f"{(manifest.get('board_commit') or 'no commit')[:12]}, filters "
        + ", ".join(f"{k}={v}" for k, v in manifest["filters"].items() if v is not None)
    ]
    for r in manifest["parents"][:limit]:
        tier = r["distance"]["tier"]
        lines.append(
            f"  {r['slug']:<16} [[{r['n']},{r['k']},{r['d']}]] w={r['w']} {r['code_type']} {r['family'] or '-'} "
            f"{r['locality_class']} d:{tier} kd2/n={r['kd2_over_n']}"
        )
    if manifest["count"] > limit:
        lines.append(f"  ... {manifest['count'] - limit} more")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Export board entries as a parent-pool manifest for code-calculus consumers."
    )
    ap.add_argument("--n-min", type=int, default=None)
    ap.add_argument("--n-max", type=int, default=None)
    ap.add_argument("--k-min", type=int, default=None)
    ap.add_argument("--d-min", type=int, default=None)
    ap.add_argument("--w-max", type=int, default=None)
    ap.add_argument("--family", action="append", default=None, help="keep this family tag (repeatable)")
    ap.add_argument("--locality", action="append", default=None, help="keep this locality class (repeatable)")
    ap.add_argument("--code-type", action="append", default=None, choices=["CSS", "stabilizer"], help="repeatable")
    ap.add_argument("--tier", action="append", default=None, choices=list(TIERS), help="distance tier (repeatable)")
    ap.add_argument("--slug", action="append", default=None, help="keep this slug (repeatable)")
    ap.add_argument("--since-commit", default=None, help="keep entries whose file was added after this commit")
    ap.add_argument("--no-checks", action="store_true", help="leave the check matrices out (a parameter listing)")
    ap.add_argument("--codes", default=None, help="the board directory (default codes/)")
    ap.add_argument("--out", default=None, help="write the manifest here instead of stdout")
    ap.add_argument("--summary", action="store_true", help="print a human listing instead of the manifest")
    ap.add_argument("--validate", action="store_true", help="validate the manifest against the schema before writing")
    args = ap.parse_args(argv)
    manifest = build(
        codes_dir=args.codes,
        n_min=args.n_min,
        n_max=args.n_max,
        k_min=args.k_min,
        d_min=args.d_min,
        w_max=args.w_max,
        families=args.family,
        localities=args.locality,
        code_types=args.code_type,
        tiers=args.tier,
        slugs=args.slug,
        since_commit=args.since_commit,
        include_checks=not args.no_checks,
    )
    if args.validate:
        problems = validate(manifest)
        if problems:
            for p in problems:
                print(f"schema: {p}", file=sys.stderr)
            return 1
    if args.summary:
        print(summary(manifest))
        return 0
    text = json.dumps(manifest, indent=1) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {manifest['count']} parents to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Anti-collision dedup oracle (campaign 7 of issue #6198).

Pre-filter candidate codes against the *board* **and** against *open PRs* by
the same fingerprint / WL-signature identity the gate uses, including the
local-Hadamard images a CSS code carries.  The gate only knows about
``codes/``; two PRs filed close together can each pass the gate while being
duplicates of one another (issue #4107, #5700).  This oracle closes that
gap by letting a campaign ask, before staging or filing:

    "is this candidate already on the board, or already in an open PR?"

It is deliberately a *filter*, not a verdict: it never runs the distance
refutation, never edits ``verify/``, and never claims a candidate is valid.
A candidate that clears the oracle still has to pass
``coordination.gate``.  The only thing the oracle adds over the gate is the
open-PR dimension and the ability to run it cheaply over a whole directory
before paying for a gate run.

Usage::

    # board only
    uv run --extra research python research/kit/dedup_oracle.py \\
        --candidates 'research/candidates/*/*.json'

    # board + open PRs (fetched via gh), cached under research/candidates/
    uv run --extra research python research/kit/dedup_oracle.py \\
        --candidates 'research/candidates/*/*.json' --open-prs

    # board + a directory of PR code files already on disk
    uv run --extra research python research/kit/dedup_oracle.py \\
        --candidates 'research/candidates/*/*.json' --pr-dir /tmp/pr_codes

The oracle is also importable::

    from dedup_oracle import identity_doc, combined_index, check
    ident, fails = identity_doc(doc)
    if ident is None:
        ...  # structural failure: fails lists the checks
    index = combined_index(include_board=True, include_open_prs=True)
    result = check(ident, index)   # {"exact": [...], "wl": [...]}
"""
import argparse
import base64
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for p in (_HERE, os.path.join(_ROOT, "verify")):
    if p not in sys.path:
        sys.path.insert(0, p)

import prescreen as PS  # noqa: E402
import qldpc_verify  # noqa: E402
import validate_candidate as VC  # noqa: E402

CACHE_PATH = os.path.join(_ROOT, "research", "candidates", ".pr_dedup_index.json")


def _as_entry(source, pr, name, n, k, d, fingerprints, signatures):
    return {
        "source": source,
        "pr": pr,
        "name": name,
        "n": n,
        "k": k,
        "d": d,
        "fingerprints": set(fingerprints) if fingerprints else set(),
        "signatures": set(signatures) if signatures else set(),
    }


def identity_doc(doc):
    """Compute the gate's identity sets for a packaged candidate document.

    Returns ``(ident, [])`` on success, where ``ident`` carries the candidate's
    own fingerprint/signature plus those of its local-Hadamard images (the same
    sets ``validate_candidate`` compares against the board).  Returns
    ``(None, failed_checks)`` when the document does not pass the structural
    half of the gate, so the caller can report *why* without paying for a
    distance refutation.
    """
    try:
        rep = qldpc_verify.verify(doc, refute=False)
    except Exception as e:  # pragma: no cover - defensive
        return None, [f"verify_error: {e}"]
    checks = rep.get("checks", [])
    structural_fail = [c["check"] for c in checks
                       if not c["ok"] and c["check"] != "distance_not_refuted"]
    if structural_fail:
        return None, structural_fail
    cand_fps, cand_sigs = VC._identity_sets(rep)
    return {
        "n": doc.get("n"),
        "k": doc.get("k"),
        "d": (doc.get("distance") or {}).get("d"),
        "fingerprint": rep.get("fingerprint"),
        "signature": (rep.get("signature") or {}).get("hash"),
        "fingerprints": cand_fps,
        "signatures": cand_sigs,
        "report": rep,
    }, []


def identity_matrices(HX, HZ):
    """Convenience: identity for raw check matrices (delegates to prescreen)."""
    ident = PS.identity(HX, HZ)
    return {
        "n": int(__import__("numpy").asarray(HX).shape[1]),
        "k": None,
        "d": None,
        "fingerprint": ident["fingerprint"],
        "signature": ident["signature"],
        "fingerprints": {ident["fingerprint"]},
        "signatures": {ident["signature"]},
    }


def index_from_docs(docs, source="doc", pr=None):
    """Build index entries from an iterable of packaged documents."""
    out = []
    for doc in docs:
        ident, fails = identity_doc(doc)
        if ident is None:
            continue
        out.append(_as_entry(
            source, pr,
            doc.get("name") or doc.get("slug") or "<unnamed>",
            doc.get("n"), doc.get("k"), (doc.get("distance") or {}).get("d"),
            ident["fingerprints"], ident["signatures"]))
    return out


def index_from_paths(paths, source="file", pr=None):
    """Build index entries from JSON files on disk."""
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        entries = index_from_docs([doc], source=source, pr=pr)
        # carry the originating path as the name when the doc has none
        for e in entries:
            if e["name"] == "<unnamed>":
                e["name"] = os.path.basename(p)
        out.extend(entries)
    return out


def _board_entries_as_index():
    out = []
    for b in PS.board_index():
        out.append(_as_entry(
            "board", None, b["name"], b["n"], b["k"], b["d"],
            b["fingerprints"], b["signatures"]))
    return out


def _gh_json(args):
    out = subprocess.check_output(["gh"] + list(args), text=True,
                                  stderr=subprocess.STDOUT)
    return json.loads(out)


def fetch_open_pr_index(*, limit=200, refresh=False, cache_path=CACHE_PATH):
    """Fetch code files from open PRs and index them.

    Results are cached on disk (sets serialized as sorted lists) so a campaign
    can re-run the oracle without re-hitting the GitHub API.  Pass
    ``refresh=True`` to force a re-fetch.
    """
    if (not refresh) and cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            out = []
            for e in cached.get("entries", []):
                out.append(_as_entry(
                    e.get("source", "pr"), e.get("pr"), e.get("name"),
                    e.get("n"), e.get("k"), e.get("d"),
                    e.get("fingerprints", []), e.get("signatures", [])))
            return out
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    try:
        prs = _gh_json(["pr", "list", "--state", "open",
                        "--limit", str(limit),
                        "--json", "number,headRefName,headRepository,headRepositoryOwner,files"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []

    entries = []
    for pr in prs:
        owner = (pr.get("headRepositoryOwner") or {}).get("login")
        repo = (pr.get("headRepository") or {}).get("name")
        branch = pr.get("headRefName")
        number = pr.get("number")
        if not (owner and repo and branch):
            continue
        for f in pr.get("files") or []:
            path = f.get("path", "")
            if not path.startswith("codes/") or not path.endswith(".json"):
                continue
            try:
                # --method GET: with a --field and no method, gh api POSTs,
                # and a POST to the contents endpoint is a 404 that the
                # except below would swallow, leaving the open-PR index empty
                res = _gh_json(["api", "--method", "GET",
                                f"repos/{owner}/{repo}/contents/{path}",
                                "--field", f"ref={branch}"])
                raw = base64.b64decode(res.get("content", ""), validate=False)
                doc = json.loads(raw.decode("utf-8"))
            except Exception:
                continue
            ident, fails = identity_doc(doc)
            if ident is None:
                continue
            entries.append(_as_entry(
                "pr", number, path.split("/")[-1],
                doc.get("n"), doc.get("k"), (doc.get("distance") or {}).get("d"),
                ident["fingerprints"], ident["signatures"]))

    if cache_path:
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            serial = {"entries": [
                {k: (sorted(v) if isinstance(v, set) else v)
                 for k, v in e.items() if k not in ("fingerprints", "signatures")}
                | {"fingerprints": sorted(e["fingerprints"]),
                   "signatures": sorted(e["signatures"])}
                for e in entries]}
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(serial, f)
        except OSError:
            pass
    return entries


def combined_index(*, include_board=True, include_open_prs=False,
                   pr_dir=None, extra_paths=None, open_pr_limit=200,
                   refresh=False):
    """Assemble one index from every requested source."""
    out = []
    if include_board:
        out.extend(_board_entries_as_index())
    if include_open_prs:
        out.extend(fetch_open_pr_index(limit=open_pr_limit, refresh=refresh))
    if pr_dir:
        for root, _, files in os.walk(pr_dir):
            for fn in files:
                if fn.endswith(".json"):
                    out.extend(index_from_paths([os.path.join(root, fn)],
                                                source="pr-dir"))
    if extra_paths:
        out.extend(index_from_paths(list(extra_paths), source="extra"))
    return out


def check(ident, index):
    """Compare a candidate identity against an index.

    Returns ``{"exact": [entry, ...], "wl": [entry, ...]}``.  ``exact``
    lists entries sharing a fingerprint (same code, possibly up to a
    Hadamard relabeling) -- the gate refuses these as duplicates.  ``wl``
    lists entries sharing the WL signature but not a fingerprint -- probable
    permutations, admitted with a label.
    """
    exact = [b for b in index if ident["fingerprints"] & b["fingerprints"]]
    wl = [b for b in index
          if (ident["signatures"] & b["signatures"])
          and not (ident["fingerprints"] & b["fingerprints"])]
    return {"exact": exact, "wl": wl}


def _summarize(results):
    n_exact = sum(1 for r in results if r["check"]["exact"])
    n_wl = sum(1 for r in results if r["check"]["wl"])
    return n_exact, n_wl


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--candidates", nargs="+", required=True,
                    help="Glob(s) for candidate JSON files")
    ap.add_argument("--board", action="store_true", default=True,
                    help="Include the board index (default: yes)")
    ap.add_argument("--no-board", dest="board", action="store_false")
    ap.add_argument("--open-prs", action="store_true",
                    help="Fetch and include open PRs via gh")
    ap.add_argument("--pr-dir", default=None,
                    help="Directory of PR code files already on disk")
    ap.add_argument("--extra-index", nargs="*", default=None,
                    help="Extra JSON code files to fold into the index")
    ap.add_argument("--open-pr-limit", type=int, default=200)
    ap.add_argument("--refresh", action="store_true",
                    help="Re-fetch open PRs even if a cache exists")
    ap.add_argument("--json-out", default=None,
                    help="Write full results to this JSON file")
    args = ap.parse_args(argv)

    import glob as _glob
    cand_paths = []
    for pat in args.candidates:
        cand_paths.extend(sorted(_glob.glob(pat, recursive=True)))
    cand_paths = [p for p in cand_paths if os.path.isfile(p)]

    index = combined_index(include_board=args.board,
                           include_open_prs=args.open_prs,
                           pr_dir=args.pr_dir,
                           extra_paths=args.extra_index,
                           open_pr_limit=args.open_pr_limit,
                           refresh=args.refresh)

    results = []
    for p in cand_paths:
        try:
            with open(p, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            results.append({"path": p, "error": str(e), "check": None})
            continue
        ident, fails = identity_doc(doc)
        if ident is None:
            results.append({"path": p, "structural_failures": fails,
                            "check": None})
            continue
        res = check(ident, index)
        results.append({
            "path": p,
            "name": doc.get("name"),
            "n": doc.get("n"), "k": doc.get("k"),
            "d": (doc.get("distance") or {}).get("d"),
            "exact_duplicates": [
                {"source": e["source"], "pr": e["pr"], "name": e["name"],
                 "n": e["n"], "k": e["k"], "d": e["d"]}
                for e in res["exact"]],
            "wl_equivalents": [
                {"source": e["source"], "pr": e["pr"], "name": e["name"],
                 "n": e["n"], "k": e["k"], "d": e["d"]}
                for e in res["wl"]],
            "check": {"exact": bool(res["exact"]), "wl": bool(res["wl"])},
        })

    n_exact, n_wl = _summarize([r for r in results if r.get("check")])
    print(f"indexed {len(index)} entries "
          f"(board+open-prs+extras); scanned {len(cand_paths)} candidates")
    print(f"  exact duplicates: {n_exact}")
    print(f"  WL equivalents:   {n_wl}")
    for r in results:
        if r.get("structural_failures"):
            print(f"  {r['path']}: STRUCTURAL FAIL {r['structural_failures']}")
        elif r.get("error"):
            print(f"  {r['path']}: ERROR {r['error']}")
        elif r["check"]["exact"] or r["check"]["wl"]:
            tag = "DUP" if r["check"]["exact"] else "WL"
            matches = r["exact_duplicates"] if r["check"]["exact"] else r["wl_equivalents"]
            print(f"  {r['path']}: {tag} -> "
                  + ", ".join(f"{m['source']}:{m['name']}" for m in matches))

    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)), exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"index_size": len(index), "results": results}, f,
                      indent=2, default=str)
    # non-zero only on usage error; collisions are reported, not fatal
    return 0


if __name__ == "__main__":
    sys.exit(main())

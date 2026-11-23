"""Upgrade exact certificates to proof_log where a checked refutation exists.

The batch behind issue #2728. For each exact certificate whose code is in
range, re-emit the question as pure CNF, refute it with kissat, check the
refutation with drat-trim, and record the result on the certificate.

Nothing here can strengthen a claim the solver path did not already make: an
entry is considered only when its certificate already says `d_exact`, the two
emitters must agree on every side, and a side counts as proved only when
drat-trim verifies. An entry whose proof does not verify or does not finish
keeps the certificate it had.

Nothing is committed but the certificate. The refutations run to hundreds of
megabytes and a committed blob is not auditable in CI, so the certificate
carries the formula's hash and the recipe to regenerate and re-check it, and
`replay_proofs.py` does exactly that on a schedule.

    python verify/proof_log_all.py --limit 20
    python verify/proof_log_all.py --max-n 144 --workers 4 --tlim 120
    python verify/proof_log_all.py --slugs 90-8-10 72-8-10 --append
"""

import argparse
import glob
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sat_certify import certify  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "certs")


def in_range(max_n, slugs=()):
    """Exact certificates whose code is at or under max_n, smallest first."""
    out = []
    for path in sorted(glob.glob(os.path.join(CERTS, "*.json"))):
        slug = os.path.splitext(os.path.basename(path))[0]
        if slugs and slug not in slugs:
            continue
        code = os.path.join(ROOT, "codes", slug + ".json")
        if not os.path.exists(code):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                cert = json.load(f)
            with open(code, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if not cert.get("d_exact") or doc["n"] > max_n:
            continue
        out.append((doc["n"], slug, path, code))
    out.sort()
    return out


def one(job):
    """Run the proof path for one entry and report what happened."""
    n, slug, cert_path, code_path, tlim = job
    with open(code_path, encoding="utf-8") as f:
        doc = json.load(f)
    work = tempfile.mkdtemp(prefix=f"proof-{slug}-")
    t0 = time.time()
    try:
        out = certify(doc, tlim=tlim, proof_dir=work, slug=slug)
    except Exception as e:  # noqa: BLE001
        return {"slug": slug, "n": n, "level": "error", "detail": str(e)[:300], "secs": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(work, ignore_errors=True)

    v = out.get("verification") or {}
    rec = {
        "slug": slug,
        "n": n,
        "level": v.get("level"),
        "secs": round(time.time() - t0, 1),
        "detail": v.get("note", "")[:300],
    }
    for side, blk in (out.get("sides") or {}).items():
        pr = blk.get("proof") or {}
        rec[f"{side}_cnf_clauses"] = (pr.get("cnf") or {}).get("clauses")
        rec[f"{side}_proof_bytes"] = (pr.get("proof") or {}).get("bytes")
        rec[f"{side}_trimmed_bytes"] = (pr.get("trimmed") or {}).get("bytes")
        rec[f"{side}_solve_secs"] = pr.get("solve_secs")
        rec[f"{side}_check_secs"] = pr.get("check_secs")
    if v.get("level") == "proof_log":
        with open(cert_path, encoding="utf-8") as f:
            cert = json.load(f)
        cert["verification"] = v
        with open(cert_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cert, f, indent=2, sort_keys=True)
            f.write("\n")
        rec["cnf_sha256"] = v.get("cnf_sha256")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-n", type=int, default=144)
    ap.add_argument("--limit", type=int, default=0, help="stop after this many entries (0 = all)")
    ap.add_argument("--slugs", nargs="*", default=(), help="run only these entries")
    ap.add_argument("--tlim", type=int, default=120)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--log", default=os.path.join(ROOT, "certs", "proof_log_batch.jsonl"))
    ap.add_argument(
        "--append", action="store_true", help="replace this run's entries in the log rather than rewriting it"
    )
    a = ap.parse_args(argv)

    todo = in_range(a.max_n, set(a.slugs))
    if a.limit:
        todo = todo[: a.limit]
    jobs = [(n, slug, cp, dp, a.tlim) for n, slug, cp, dp in todo]
    print(f"{len(jobs)} exact certificates at n <= {a.max_n}")

    kept = []
    if a.append and os.path.exists(a.log):
        mine = {slug for _, slug, _, _ in todo}
        with open(a.log, encoding="utf-8") as f:
            kept = [json.loads(line) for line in f if line.strip()]
        kept = [r for r in kept if r.get("slug") not in mine]

    counts, t0, results = {}, time.time(), []
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for i, rec in enumerate(pool.map(one, jobs), 1):
            counts[rec["level"]] = counts.get(rec["level"], 0) + 1
            results.append(rec)
            if i % 25 == 0 or i == len(jobs):
                print(f"  {i}/{len(jobs)}  {counts}  {round(time.time() - t0)}s")
    rows = sorted(kept + results, key=lambda r: (r.get("n", 0), r["slug"]))
    with open(a.log, "w", encoding="utf-8", newline="\n") as log:
        for rec in rows:
            log.write(json.dumps(rec, sort_keys=True) + "\n")
    print(json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

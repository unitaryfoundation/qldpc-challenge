"""Receipts of the post-merge replication of measured-rate points (issue
#1278).

At PR time the gate replicates a claim's cheapest point inside its budget and
defers the rest; verify/ler_replicate.py re-measures every point of every
entry weekly with a long budget and several seeds and records the outcome
here, one file per entry under receipts/ler/<slug>.json, committed to the
tree so the site can show each point as verified, failed, unverifiable, or
pending. A receipt binds to the claim it checked through a digest of the ler
block, the round count, and the committed circuits; a claim edited after its
receipt reads as pending again until the next run.
"""
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ler_tools as lt  # noqa: E402

RECEIPT_VERSION = "1"
RECEIPT_DIR = "receipts/ler"


def claim_digest(doc, circuits_dir):
    """sha256 over the ler block, rounds, and both committed .stim files."""
    h = hashlib.sha256()
    circ = doc.get("circuit") or {}
    h.update(json.dumps(circ.get("ler"), sort_keys=True).encode())
    h.update(str(circ.get("rounds")).encode())
    for fname in ("memory_x.stim", "memory_z.stim"):
        p = os.path.join(circuits_dir, fname)
        if os.path.exists(p):
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def receipt_path(root, slug):
    return os.path.join(root, RECEIPT_DIR, slug + ".json")


def make_receipt(slug, digest, report, *, head_sha=None, when=None):
    """A receipt from a mode-"all" ler_verify report."""
    points = {}
    for side, comp in (report.get("computed") or {}).items():
        points[side] = {p: {k: v for k, v in r.items() if k != "runs"}
                        | {"runs": r.get("runs", [])}
                        for p, r in (comp.get("points") or {}).items()}
    return {
        "receipt_version": RECEIPT_VERSION,
        "slug": slug,
        "claim_digest": digest,
        "measured_at": when or datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "head_sha": head_sha,
        "ok": bool(report.get("ok")),
        "points": points,
    }


def write_receipt(root, receipt):
    path = receipt_path(root, receipt["slug"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)
    return path


def load_receipt(root, slug):
    path = receipt_path(root, slug)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def point_status(receipt, digest, side, p, decoder=lt.DECODER_ID):
    """"verified", "failed", "unverifiable", "inadmissible", or "pending" for
    one point under ``decoder``, given the current claim digest (a stale
    receipt is pending). Receipts key a point by ler_tools.point_key, the rate
    alone for the reference decoder, so receipts written before the registry
    read unchanged."""
    if not receipt or receipt.get("claim_digest") != digest:
        return "pending"
    rec = ((receipt.get("points") or {}).get(side) or {}).get(lt.point_key(p, decoder))
    if not rec:
        return "pending"
    return rec.get("status", "pending")

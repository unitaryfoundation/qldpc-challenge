"""Build non-authoritative verification receipts for submission CI.

Receipts summarize facts already computed by the trusted verifier and the distance
refutation gate. They are CI artifacts, not board data: generating one never changes
whether a submission passes, and self-reported provenance is labelled as such.
"""
import hashlib
import json
import os
import subprocess


def _git(root, *args):
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()
    except Exception:
        return None


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def make_receipt(doc, path, verdict, *, gate, repo_root, pr_number=None,
                 pr_author=None, base_sha=None, head_sha=None):
    """Return a JSON-serializable receipt for one already-gated submission."""
    prov = doc.get("provenance") or {}
    candidate = verdict.get("candidate", {})
    gates = verdict.get("gates", {})
    novelty = gates.get("novelty", {})
    refute = gates.get("refute", {})
    receipt = {
        "receipt_version": "1",
        "submission": {
            "path": os.path.relpath(path, repo_root),
            "sha256": _sha256(path),
            "pull_request": pr_number,
            "pr_author": pr_author,
            "base_sha": base_sha or _git(repo_root, "rev-parse", "HEAD"),
            "head_sha": head_sha,
        },
        "trusted_validation": {
            "verifier_commit": base_sha or _git(repo_root, "rev-parse", "HEAD"),
            "validator_source_sha256": verdict.get("validator", {}).get(
                "source_sha256"),
            "validator_seed": verdict.get("validator", {}).get("seed"),
            "structural_result": "passed" if gates.get("verify", {}).get("ok")
                                 else "failed",
            "distance_gate": gate,
        },
        "computed": {
            "n": candidate.get("n"),
            "k": candidate.get("k"),
            "d": candidate.get("d"),
            "family": candidate.get("family"),
            "weight_class": candidate.get("weight_class"),
            "locality_class": candidate.get("locality_class"),
            "fingerprint": candidate.get("fingerprint"),
            "signature": candidate.get("signature"),
        },
        "deduplication": gates.get("dedup", {}),
        "frontier": {
            "board_advancing": novelty.get("board_advancing"),
            "cell": novelty.get("cell"),
            "dominated_by": novelty.get("dominated_by", []),
        },
        "provenance": {
            "authors": {
                "value": prov.get("authors", []),
                "status": "self_reported",
            },
            "contributors": {
                "value": prov.get("contributors", []),
                "status": "self_reported",
            },
            "model": {
                "value": prov.get("model"),
                "status": "self_reported",
            },
            "harness": {
                "value": prov.get("harness"),
                "status": "self_reported",
            },
            "novelty": {
                "value": prov.get("novelty"),
                "status": "self_reported",
            },
        },
        "routing": {
            "status": "eligible_under_current_checks"
            if verdict.get("passed") and not gate.get("refuted")
            else "maintainer_review",
            "reasons": list(verdict.get("labels", [])),
        },
    }
    return receipt


def write_receipt(receipt, output_dir, slug):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, slug + ".json")
    with open(path, "w") as f:
        json.dump(receipt, f, indent=2)
        f.write("\n")
    return path

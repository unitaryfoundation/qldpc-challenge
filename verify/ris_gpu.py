"""
GPU deep RIS refutation/witness search for board codes -- wrapper around the
standalone verify/ris_gpu.cu binary (build with `make ris`).

For each side of a CSS code this derives the opposite-type logical basis
exactly as qldpc_verify.py does (via gf2.py, the audited reference), hands
the packed matrices to the GPU binary, and then re-verifies any recovered
operator here on the CPU: in ker(H_check), anticommutes with a logical,
weight recounted. Only CPU-verified operators are reported. All weights are
upper bounds on distance; nothing here is a proof.

    make ris
    python verify/ris_gpu.py codes/674-128-87.json --trials 1000000000
    python verify/ris_gpu.py --campaign research/campaign.json

Writes <code>.witness.json alongside each input. The GPU binary needs an
NVIDIA GPU + CUDA; this wrapper itself is numpy + stdlib only.

A campaign is JSON with ``defaults`` and ``codes``; each code has ``code`` and
may override ``sides``, ``target``, ``trials``, ``seed``, ``k_sub``, and
``pair_depth``. Batch results are written to the manifest's ``output_dir``.
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2  # noqa: E402

MAGIC = b"RISGPU01"
BATCH_MAGIC = b"RISBATCH1"


def find_binary(explicit=None):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [explicit, os.environ.get("RIS_GPU_BIN"), os.path.join(root, "build", "ris_gpu")]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError("ris_gpu binary not found; build it with `make ris` or set RIS_GPU_BIN")


def checks_matrix(support_list, n):
    H = np.zeros((len(support_list), n), dtype=np.int8)
    for r, sup in enumerate(support_list):
        for q in sup:
            H[r, q] ^= 1
    return H


def pack_rows(M):
    """Bit-pack GF(2) rows LSB-first: column j -> word j//64, bit j%64.
    Must match the layout ris_gpu.cu reads.
    """
    M = np.asarray(M, dtype=np.uint8) % 2
    m, n = M.shape
    nw = (n + 63) // 64
    padded = np.zeros((m, nw * 64), dtype=np.uint8)
    padded[:, :n] = M
    powers = np.uint64(1) << np.arange(64, dtype=np.uint64)
    return (padded.reshape(m, nw, 64).astype(np.uint64) * powers).sum(axis=2, dtype=np.uint64)


def write_input(path, W_null, W_logical, n):
    packed_null = pack_rows(W_null)
    packed_logical = pack_rows(W_logical)
    nw = packed_null.shape[1]
    with open(path, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("<4i", n, packed_null.shape[0], packed_logical.shape[0], nw))
        f.write(packed_null.astype("<u8").tobytes())
        f.write(packed_logical.astype("<u8").tobytes())


def load_campaign(path):
    """Load and validate a JSON campaign manifest.

    The manifest is intentionally a small orchestration format.  Matrix
    packing remains the binary protocol owned by this module/CUDA tool.
    """
    with open(path) as f:
        manifest = json.load(f)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("codes"), list):
        raise ValueError("campaign manifest must be an object with a codes list")
    defaults = {"mode": "recover", "trials": 50_000_000, "seed": 1, "batch": 50_000, "pair_depth": 0}
    defaults.update(manifest.get("defaults", {}))
    if defaults["mode"] not in ("recover", "estimate"):
        raise ValueError("defaults.mode must be recover or estimate")
    requests = []
    for index, item in enumerate(manifest["codes"]):
        if not isinstance(item, dict) or not isinstance(item.get("code"), str):
            raise ValueError(f"codes[{index}] must contain a code path")
        resolved = dict(defaults)
        resolved.update(item)
        resolved["code"] = item["code"]
        resolved["id"] = item.get("id", resolved["code"])
        resolved["sides"] = item.get("sides", ["X", "Z"])
        if isinstance(resolved["sides"], str):
            resolved["sides"] = [s.strip().upper() for s in resolved["sides"].split(",")]
        else:
            resolved["sides"] = [str(s).upper() for s in resolved["sides"]]
        if not set(resolved["sides"]) <= {"X", "Z"} or not resolved["sides"]:
            raise ValueError(f"codes[{index}].sides must contain X and/or Z")
        for key in ("trials", "batch", "seed", "pair_depth"):
            if int(resolved[key]) < 0 or (key in ("trials", "batch") and int(resolved[key]) == 0):
                raise ValueError(f"codes[{index}].{key} is out of range")
            resolved[key] = int(resolved[key])
        if resolved.get("k_sub") is not None:
            resolved["k_sub"] = int(resolved["k_sub"])
        if resolved.get("target") is not None:
            resolved["target"] = int(resolved["target"])
        requests.append(resolved)
    return manifest, requests


def write_batch_input(path, requests):
    """Write the internal RISBATCH1 request stream consumed by CUDA."""
    with open(path, "wb") as f:
        f.write(BATCH_MAGIC)
        f.write(struct.pack("<2i", 1, len(requests)))
        for request in requests:
            packed_null = pack_rows(request["W_null"])
            packed_logical = pack_rows(request["W_logical"])
            n = int(request["n"])
            f.write(
                struct.pack(
                    "<9iQ",
                    int(request["request_id"]),
                    n,
                    packed_null.shape[0],
                    packed_logical.shape[0],
                    packed_null.shape[1],
                    int(request["trials"]),
                    int(request["batch"]),
                    int(request.get("k_sub") or 0),
                    int(request.get("target") if request.get("target") is not None else -1),
                    int(request["seed"]),
                )
            )
            f.write(struct.pack("<2i", 1 if request["mode"] == "recover" else 0, int(request.get("pair_depth", 0))))
            f.write(packed_null.astype("<u8").tobytes())
            f.write(packed_logical.astype("<u8").tobytes())


def resolve_campaign_requests(manifest_path):
    """Load code matrices and expand each code into one request per side."""
    manifest, entries = load_campaign(manifest_path)
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    requests = []
    request_id = 0
    for entry in entries:
        code_path = entry["code"] if os.path.isabs(entry["code"]) else os.path.join(manifest_dir, entry["code"])
        with open(code_path) as f:
            doc = json.load(f)
        n = doc["n"]
        HX = checks_matrix(doc["checks"]["X"], n)
        HZ = checks_matrix(doc["checks"]["Z"], n)
        for side in entry["sides"]:
            if side == "X":
                check, logical = HZ, gf2.logical_basis(HX, HZ)
            else:
                check, logical = HX, gf2.logical_basis(HZ, HX)
            request = dict(
                entry,
                code=code_path,
                request_id=request_id,
                side=side,
                n=n,
                W_null=gf2.kernel_basis(check),
                W_logical=logical,
                claimed=doc["distance"][side]["value"],
            )
            requests.append(request)
            request_id += 1
    return manifest, requests


def parse_output(text):
    out = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key] = val
    if "support" in out:
        out["support"] = [int(x) for x in out["support"].split(",") if x]
    for key in ("best_weight", "trials", "n", "k_sub", "k_null", "k_logical"):
        if key in out:
            out[key] = int(out[key])
    return out


def cpu_verify(support, n, H_check, L_opp):
    """The trust boundary: accept an operator only on CPU-checked evidence.

    Returns the recounted weight of the verified operator, or None. Malformed
    support lists (out-of-range or duplicate indices) are rejected like any
    failed verification rather than crashing the sweep.
    """
    if not support or len(set(support)) != len(support) or not all(isinstance(q, int) and 0 <= q < n for q in support):
        return None
    v = np.zeros(n, dtype=np.int8)
    v[support] = 1
    if not gf2.commutes(v, H_check):
        return None
    if not bool(((gf2._as_gf2(L_opp) @ v) % 2).any()):
        return None
    return int(v.sum())


def run_side(side, H_check, L_opp, claimed, args, binary):
    with tempfile.NamedTemporaryFile(suffix=".risgpu", delete=False) as tmp:
        write_input(tmp.name, gf2.kernel_basis(H_check), L_opp, H_check.shape[1])
        cmd = [binary, tmp.name, "--mode", args.mode, "--trials", str(args.trials), "--seed", str(args.seed)]
        if args.k_sub is not None:
            cmd += ["--k-sub", str(args.k_sub)]
        if args.pair_depth:
            cmd += ["--pair-depth", str(args.pair_depth)]
        if args.target is not None:
            cmd += ["--target", str(args.target)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=args.proc_timeout)
        finally:
            os.unlink(tmp.name)
    res = parse_output(proc.stdout)
    entry = {
        "claimed": claimed,
        "gpu_best_weight": res.get("best_weight"),
        "trials": res.get("trials"),
        "witness_weight": None,
        "operator_support": None,
        "cpu_verified": False,
    }
    support = res.get("support")
    if support:
        weight = cpu_verify(support, H_check.shape[1], H_check, L_opp)
        if weight is not None:
            entry["witness_weight"] = weight
            entry["operator_support"] = support
            entry["cpu_verified"] = True
        else:
            print(f"  [{side}] GPU operator FAILED CPU verification -- discarded", file=sys.stderr)
    print(
        f"  [{side}] claimed {claimed}, GPU best {res.get('best_weight')}, "
        f"cpu-verified witness "
        f"{entry['witness_weight'] if entry['cpu_verified'] else 'none'}"
    )
    return entry


def run_campaign(manifest_path, binary):
    manifest, requests = resolve_campaign_requests(manifest_path)
    output_dir = manifest.get("output_dir", "research/campaign-receipts")
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(os.path.abspath(manifest_path)), output_dir)
    os.makedirs(output_dir, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".risbatch", delete=False) as tmp:
        batch_path = tmp.name
    try:
        write_batch_input(batch_path, requests)
        proc = subprocess.run(
            [binary, "--batch-input", batch_path],
            capture_output=True,
            text=True,
            timeout=int(manifest.get("proc_timeout", 7200)),
        )
    finally:
        os.unlink(batch_path)
    results = {}
    current = None
    for line in proc.stdout.splitlines():
        if line.startswith("request_id="):
            current = int(line.split("=", 1)[1])
            results[current] = {}
        elif current is not None and "=" in line:
            key, value = line.split("=", 1)
            results[current][key] = value
    receipt = {
        "receipt_version": "1",
        "tool": "ris_gpu",
        "manifest": os.path.abspath(manifest_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "requests": [],
    }
    failed = proc.returncode != 0
    for request in requests:
        raw = results.get(request["request_id"], {})
        if not raw:
            failed = True
        entry = {
            "request_id": request["request_id"],
            "id": request["id"],
            "code": request["code"],
            "side": request["side"],
            "claimed": request["claimed"],
            "settings": {
                k: request.get(k) for k in ("mode", "trials", "batch", "seed", "k_sub", "target", "pair_depth")
            },
            "gpu_best_weight": int(raw["best_weight"]) if raw.get("best_weight") else None,
            "trials": int(raw["trials"]) if raw.get("trials") else 0,
            "stopped_early": (
                raw.get("stopped_early") == "1" or (raw.get("trials") and int(raw["trials"]) < request["trials"])
            ),
            "cpu_verified": False,
            "witness_weight": None,
            "operator_support": None,
        }
        support = [int(x) for x in raw["support"].split(",") if x] if raw.get("support") else None
        if support:
            with open(request["code"]) as f:
                doc = json.load(f)
            n = doc["n"]
            HX = checks_matrix(doc["checks"]["X"], n)
            HZ = checks_matrix(doc["checks"]["Z"], n)
            check = HZ if request["side"] == "X" else HX
            opp = gf2.logical_basis(HX, HZ) if request["side"] == "X" else gf2.logical_basis(HZ, HX)
            weight = cpu_verify(support, n, check, opp)
            if weight is None or (entry["gpu_best_weight"] is not None and weight != entry["gpu_best_weight"]):
                failed = True
            else:
                entry.update(cpu_verified=True, witness_weight=weight, operator_support=support)
                safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(request["id"])).strip("._") or str(request["request_id"])
                witness_path = os.path.join(output_dir, f"{safe_id}.{request['side']}.witness.json")
                with open(witness_path, "w") as f:
                    json.dump(
                        {
                            "code": request["code"],
                            "tool": "ris_gpu",
                            "mode": request["mode"],
                            "trials": entry["trials"],
                            "seed": request["seed"],
                            request["side"]: entry,
                        },
                        f,
                        indent=1,
                    )
        receipt["requests"].append(entry)
    receipt["ok"] = not failed
    receipt_path = os.path.join(output_dir, manifest.get("receipt", "campaign-receipt.json"))
    with open(receipt_path, "w") as f:
        json.dump(receipt, f, indent=2)
    print(f"  -> {receipt_path}")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    return 0 if receipt["ok"] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("code_json", nargs="*", help="board code JSON file(s)")
    ap.add_argument("--campaign", help="JSON campaign manifest for batch mode")
    ap.add_argument("--trials", type=int, default=50_000_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--k-sub",
        type=int,
        default=None,
        help="sketch rows (default: binary's default; in "
        "--pair-depth mode the binary defaults to the "
        "full kernel basis)",
    )
    ap.add_argument(
        "--pair-depth",
        type=int,
        default=0,
        help=">0: deep kernel (full-basis RREF + XOR pairs of "
        "the P lightest rows per trial); stronger per "
        "trial at large n",
    )
    ap.add_argument("--mode", choices=("recover", "estimate"), default="recover")
    ap.add_argument("--target", type=int, default=None, help="early-stop once a weight < target is committed")
    ap.add_argument("--sides", default="X,Z")
    ap.add_argument("--binary", default=None, help="path to the ris_gpu binary (default: build/ris_gpu)")
    ap.add_argument("--proc-timeout", type=int, default=7200, help="kill a wedged GPU binary after this many seconds")
    args = ap.parse_args()
    binary = find_binary(args.binary)
    if args.campaign:
        return run_campaign(args.campaign, binary)
    if not args.code_json:
        ap.error("provide code_json or --campaign")
    sides = [s.strip().upper() for s in args.sides.split(",") if s.strip()]

    for path in args.code_json:
        with open(path) as f:
            doc = json.load(f)
        n = doc["n"]
        HX = checks_matrix(doc["checks"]["X"], n)
        HZ = checks_matrix(doc["checks"]["Z"], n)
        dist = doc["distance"]
        print(f"{path}: [[{n},{doc['k']},{dist['d']}]] mode={args.mode} trials={args.trials}")
        out = {"code": path, "tool": "ris_gpu", "mode": args.mode, "trials": args.trials, "seed": args.seed}
        # An X-type logical lives in ker(H_Z) and must anticommute with a
        # Z-type logical; mirror for Z.
        if "X" in sides:
            out["X"] = run_side("X", HZ, gf2.logical_basis(HX, HZ), dist["X"]["value"], args, binary)
        if "Z" in sides:
            out["Z"] = run_side("Z", HX, gf2.logical_basis(HZ, HX), dist["Z"]["value"], args, binary)
        res_path = path.rsplit(".json", 1)[0] + ".witness.json"
        with open(res_path, "w") as f:
            json.dump(out, f, indent=1)
        print(f"  -> {res_path}")


if __name__ == "__main__":
    main()

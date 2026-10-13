"""Rebuild the cyclic CSS checks and directly validate saved logicals."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "verify"), str(ROOT / "research/kit")]
from gf2 import rank
from qldpc_verify import verify
from surrogate import validate_logical


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix(doc, side):
    result = np.zeros((len(doc["checks"][side]), doc["n"]), dtype=np.int8)
    for row, support in enumerate(doc["checks"][side]):
        result[row, support] = 1
    return result


def check_witness(hx, hz, side, weight, support):
    ok, detail = validate_logical(hx, hz, side, weight, support)
    assert ok, (side, weight, detail)


def main():
    recipe = json.loads((HERE / "construction.json").read_text())
    code_path = ROOT / "codes/682-172-76.json"
    assert digest(code_path) == recipe["submitted_code_sha256"]
    for name, expected in recipe["evidence_sha256"].items():
        assert digest(HERE / name) == expected

    code = json.loads(code_path.read_text())
    initial = json.loads((HERE / "initial-bound.json").read_text())
    audited = json.loads((HERE / "pair-audited-input.json").read_text())
    assert verify(code)["ok"] and verify(initial)["ok"]
    assert verify(audited)["ok"]
    m = recipe["circulant_size"]
    a, b = recipe["a"], recipe["b"]
    rows_x = [sorted([(i + q) % m for q in a]
                     + [m + (i + q) % m for q in b]) for i in range(m)]
    rows_z = [sorted([(i - q) % m for q in b]
                     + [m + (i - q) % m for q in a]) for i in range(m)]
    assert code["checks"] == {"X": rows_x, "Z": rows_z}
    assert initial["checks"] == code["checks"]
    assert audited["checks"] == code["checks"]
    hx, hz = matrix(code, "X"), matrix(code, "Z")
    assert [rank(hx), rank(hz)] == [255, 255]
    assert code["n"] - rank(hx) - rank(hz) == code["k"] == 172

    count = 0
    for doc in (initial, code):
        for side in ("X", "Z"):
            hit = doc["distance"][side]
            check_witness(hx, hz, side, hit["value"], hit["witness"])
            count += 1
    for name in ("fold1000-witness.json", "structural10000-witness.json"):
        raw = json.loads((HERE / name).read_text())
        for side, hit in raw["witnesses"].items():
            check_witness(hx, hz, side, hit["weight"], hit["support"])
            count += 1
    for name in ("local-100000-raw.json", "local-1000000-raw.json"):
        raw = json.loads((HERE / name).read_text())
        check_witness(hx, hz, raw["side"], raw["weight"], raw["support"])
        count += 1
    for name in ("repeat-100000-raw.json", "repeat-1000000-raw.json"):
        raw = json.loads((HERE / name).read_text())
        check_witness(hx, hz, raw["side"], raw["weight"], raw["support"])
        count += 1
    raw = json.loads((HERE / "pair-candidate-witness.json").read_text())
    check_witness(hx, hz, raw["side"], raw["weight"], raw["support"])
    count += 1
    peer = json.loads((ROOT / "codes/682-172-50.json").read_text())
    peer_x, peer_z = matrix(peer, "X"), matrix(peer, "Z")
    raw = json.loads((HERE / "pair-peer-witness.json").read_text())
    check_witness(peer_x, peer_z, raw["side"], raw["weight"], raw["support"])
    count += 1
    print(json.dumps({"matrices_match_construction": True,
                      "ranks": [255, 255], "witnesses_validated": count,
                      "distance": "d <= 76; no exact-distance certificate"}))


if __name__ == "__main__":
    main()

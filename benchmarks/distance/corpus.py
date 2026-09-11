"""Freeze benchmark inputs without selecting them by distance-search outcomes."""

import argparse
import io
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from common import HERE, ROOT, atomic_json, matrix_hash
from scipy.io import mmread

# isort: split
# common initializes the repository paths before these imports.
import gf2
from bb import build_bb
from css import compute_k, verify_css
from group_algebra import block, metacyclic
from products import hypergraph_product

SOURCES = json.loads((HERE / "sources.json").read_text())

BOARD = [
    "72-12-6",
    "144-12-12",
    "300-4-27",
    "450-8-16",
    "550-110-18",
    "700-6-32",
    "700-140-22",
    "700-222-28",
    "674-128-80",
    "682-172-79",
    "576-294-12",
    "300-60-14",
    "630-126-20",
    "682-20-22",
]
TANNER = ["144_2_13", "432_8_33", "684_2_29"]


def fetch(source, relative, cache):
    """Cache bytes from a pinned public GitHub revision."""
    spec = SOURCES[source]
    repository = spec["url"].removeprefix("https://github.com/")
    destination = cache / source / spec["commit"] / relative
    if not destination.exists():
        url = f"https://raw.githubusercontent.com/{repository}/{spec['commit']}/{urllib.parse.quote(relative)}"
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return destination.read_bytes()


def supports_matrix(supports, n):
    """Expand the repository's sparse check representation."""
    out = np.zeros((len(supports), n), dtype=np.int8)
    for row, support in enumerate(supports):
        out[row, support] = 1
    return out


def zsz(parameters, polynomials):
    """Equation (1)/(13), arXiv:2607.27644v1; use the kit's group operations."""
    l1, l2, twist = parameters
    group, _ = metacyclic(l1, l2, twist)
    matrices = [
        block(group, [x * l2 + y for x, y in polynomial], side)
        for polynomial, side in zip(polynomials, ("L", "L", "R", "R"), strict=True)
    ]
    a, b, c, d = matrices
    zero = np.zeros_like(a)
    return (
        np.block([[a, zero, b, zero, c.T], [zero, a, zero, b, d.T]]),
        np.block([[c, d, zero, zero, a.T], [zero, zero, c, d, b.T]]),
    )


def fresh_classical(columns, rng):
    """Three disjoint socket permutations give column degree 3 and row degree 6."""
    rows = columns // 2
    for _ in range(10000):
        matrix = np.zeros((rows, columns), dtype=np.int8)
        for _ in range(3):
            assigned = rng.permutation(np.repeat(np.arange(rows), 2))
            matrix[assigned, np.arange(columns)] += 1
        if matrix.max() == 1:
            return matrix
    raise RuntimeError("Could not construct a simple degree-(3,6) Tanner graph")


def entries(cache):
    """Yield fixed board, literature, and unfiltered construction examples."""
    for name in BOARD:
        relative = f"codes/{name}.json"
        doc = json.loads(
            subprocess.check_output(["git", "show", f"{SOURCES['repository_base']}:{relative}"], cwd=ROOT, text=True)
        )
        reference = {side: doc["distance"][side]["witness"] for side in ("X", "Z")}
        yield (
            f"board-{name}",
            supports_matrix(doc["checks"]["X"], doc["n"]),
            supports_matrix(doc["checks"]["Z"], doc["n"]),
            {
                "group": "board",
                "family": doc.get("family", doc["name"]),
                "source": relative,
                "source_commit": SOURCES["repository_base"],
                "claimed_distance": doc["distance"]["d"],
                "reference": reference,
                "expected_n": doc["n"],
                "expected_k": doc["k"],
            },
        )
    # A published failed candidate supplies a real inflated-claim regression,
    # unlike an unavailable local staging artifact from the issue comment.
    bad_a = [0, 1, 3, 18, 33, 47, 63, 70, 193, 216, 253, 254, 273, 276, 285, 288]
    bad_b = [0, 3, 9, 15, 55, 60, 72, 90, 135, 150, 165, 195, 216, 300, 325, 330]
    bad_z = [
        1,
        8,
        13,
        47,
        68,
        70,
        93,
        100,
        116,
        128,
        160,
        208,
        215,
        220,
        238,
        275,
        277,
        298,
        300,
        335,
        362,
        377,
        385,
        400,
        500,
        515,
        592,
        607,
    ]
    bad_x = sorted(345 + (-q) % 345 if q < 345 else (-(q - 345)) % 345 for q in bad_z)
    yield (
        "regression-690-182",
        *build_bb(345, 1, [(q, 0) for q in bad_a], [(q, 0) for q in bad_b]),
        {
            "group": "regression",
            "family": "generalized-bicycle",
            "source": "notes/682-172-79.md, Dead ends",
            "source_commit": SOURCES["repository_base"],
            "expected_n": 690,
            "expected_k": 182,
            "claimed_distance": 77,
            "reference": {"X": bad_x, "Z": bad_z},
            "A": bad_a,
            "B": bad_b,
        },
    )
    for name in TANNER:
        matrices = []
        for side in ("X", "Z"):
            data = fetch("codedistance", f"examples/tanner_codes/H{side}_{name}.mtx", cache)
            matrix = mmread(io.BytesIO(data))
            matrices.append(np.asarray(matrix.toarray() if hasattr(matrix, "toarray") else matrix, dtype=np.int8) % 2)
        n, k, target = map(int, name.split("_"))
        yield (
            f"tanner-{name}",
            *matrices,
            {
                "group": "literature",
                "family": "quantum-tanner",
                "source": "codedistance",
                "expected_n": n,
                "expected_k": k,
                "paper_target": target,
            },
        )
    for n, k, target in ((780, 156, 22), (975, 195, 24)):
        directory = f"processor_codes/mitten/[[{n},{k},{target}]]"
        matrices = [
            np.load(io.BytesIO(fetch("yarn", f"{directory}/H{side}.npy", cache)), allow_pickle=False)
            for side in ("x", "z")
        ]
        yield (
            f"mitten-{n}-{k}",
            *matrices,
            {
                "group": "literature",
                "family": "mitten",
                "source": f"yarn:{directory}",
                "expected_n": n,
                "expected_k": k,
                "paper_target": target,
            },
        )
    zsz_specs = [
        (
            775,
            155,
            22,
            [31, 5, 2],
            [
                [[0, 0], [26, 2], [18, 3]],
                [[0, 0], [13, 2], [7, 4]],
                [[0, 0], [1, 1], [28, 4]],
                [[0, 0], [0, 1], [22, 2]],
            ],
        ),
        (
            840,
            168,
            24,
            [28, 6, 11],
            [
                [[0, 0], [0, 1], [5, 2]],
                [[0, 0], [2, 3], [19, 3]],
                [[0, 0], [24, 1], [2, 2]],
                [[0, 0], [26, 2], [27, 3]],
            ],
        ),
    ]
    for n, k, target, parameters, polynomials in zsz_specs:
        yield (
            f"zsz-{n}-{k}",
            *zsz(parameters, polynomials),
            {
                "group": "literature",
                "family": "zsz-lp",
                "source": "arxiv:2607.27644v1, Tables 3 and 8",
                "parameters": parameters,
                "polynomials": polynomials,
                "expected_n": n,
                "expected_k": k,
                "paper_target": target,
            },
        )
    for length, m, a, b, k, target in (
        (21, 18, [3, 10, 17], [5, 3, 19], 16, 34),
        (12, 36, [7, 23, 21], [1, 3, 2], 4, 40),
    ):
        at, bt = [[a[0], 0], [0, a[1]], [0, a[2]]], [[0, b[0]], [b[1], 0], [b[2], 0]]
        yield (
            f"bb-{2 * length * m}-{k}",
            *build_bb(length, m, at, bt),
            {
                "group": "literature",
                "family": "bivariate-bicycle",
                "source": "codedistance:examples/bivariate_bicycle.py",
                "l": length,
                "m": m,
                "A": at,
                "B": bt,
                "expected_n": 2 * length * m,
                "expected_k": k,
                "paper_target": target,
            },
        )
    for length, m in ((18, 20), (20, 21), (20, 25)):
        yield (
            f"toric-{2 * length * m}",
            *build_bb(length, m, [(0, 0), (1, 0)], [(0, 0), (0, 1)]),
            {
                "group": "control",
                "family": "rectangular-toric",
                "l": length,
                "m": m,
                "expected_n": 2 * length * m,
                "expected_k": 2,
                "analytic_target": min(length, m),
            },
        )
    for length, m, seed in ((24, 16, 101601), (24, 18, 101602), (24, 20, 101603)):
        rng = np.random.default_rng(seed)
        at = [[int(q // m), int(q % m)] for q in rng.choice(length * m, 4, replace=False)]
        bt = [[int(q // m), int(q % m)] for q in rng.choice(length * m, 4, replace=False)]
        yield (
            f"fresh-bb-{2 * length * m}",
            *build_bb(length, m, at, bt),
            {
                "group": "fresh",
                "family": "bivariate-bicycle",
                "seed": seed,
                "l": length,
                "m": m,
                "A": at,
                "B": bt,
                "expected_n": 2 * length * m,
            },
        )
    for columns, seed in ((24, 101611), (26, 101612), (28, 101613)):
        rng = np.random.default_rng(seed)
        first, second = fresh_classical(columns, rng), fresh_classical(columns, rng)
        yield (
            f"fresh-hgp-{columns * columns * 5 // 4}",
            *hypergraph_product(first, second),
            {
                "group": "fresh",
                "family": "hypergraph-product",
                "seed": seed,
                "classical_columns": columns,
                "classical_rows": columns // 2,
                "expected_n": columns * columns * 5 // 4,
            },
        )


def prepare(output, cache):
    """Validate structure and existing reference witnesses, then freeze matrices."""
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "sources": SOURCES,
        "cases": [],
        "excluded": [
            {
                "case": "staged-666-8-26",
                "reason": "Matrices unavailable; issue witness has 26 indices but is labeled weight 24.",
            }
        ],
    }
    seen = set()
    for name, x_matrix, z_matrix, metadata in entries(cache):
        hx, hz = np.asarray(x_matrix, dtype=np.int8), np.asarray(z_matrix, dtype=np.int8)
        if hx.ndim != 2 or hz.ndim != 2 or hx.shape[1] != hz.shape[1]:
            raise ValueError(f"{name}: incompatible matrix shapes")
        if not np.isin(hx, [0, 1]).all() or not np.isin(hz, [0, 1]).all() or not verify_css(hx, hz):
            raise ValueError(f"{name}: invalid binary CSS matrices")
        n, k = hx.shape[1], compute_k(hx, hz)
        if n != metadata["expected_n"] or k != metadata.get("expected_k", k) or k <= 0:
            raise ValueError(f"{name}: unexpected parameters n={n}, k={k}")
        digest = matrix_hash(hx, hz)
        if digest in seen:
            raise ValueError(f"{name}: duplicate matrix pair")
        seen.add(digest)
        for side, support in metadata.get("reference", {}).items():
            if len(support) != len(set(support)) or any(q < 0 or q >= n for q in support):
                raise ValueError(f"{name}: malformed reference witness")
            vector = np.zeros(n, dtype=np.int8)
            vector[support] = 1
            own, opposite = (hx, hz) if side == "X" else (hz, hx)
            if not support or not gf2.commutes(vector, opposite) or gf2.in_rowspace(vector, own):
                raise ValueError(f"{name}: invalid {side} reference witness")
        file = output / f"{name}.npz"
        np.savez_compressed(file, hx=hx, hz=hz)
        record = {
            "id": name,
            "n": n,
            "k": k,
            "rate": k / n,
            "matrix_sha256": digest,
            "file": file.name,
            "rank_x": gf2.rank(hx),
            "rank_z": gf2.rank(hz),
            "shape_x": list(hx.shape),
            "shape_z": list(hz.shape),
            "max_row_weight": int(max(hx.sum(1).max(), hz.sum(1).max())),
            "max_column_weight": int(max(hx.sum(0).max(), hz.sum(0).max())),
            **metadata,
        }
        manifest["cases"].append(record)
        atomic_json(output / "manifest.json", manifest)
        print(f"{name}: n={n}, k={k}, reference={'reference' in metadata}", flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=HERE / "cache" / "corpus")
    parser.add_argument("--cache", type=Path, default=HERE / "cache" / "sources")
    args = parser.parse_args()
    prepare(args.output, args.cache)

r"""Exhaustively enumerate small CSS codes up to qubit permutation and X/Z duality.

Run the default census (n <= 6, k >= 1, exact d >= 3) with:

    uv run --extra research python research/kit/census_css.py

Select a parameter range and save JSONL with:

    uv run --extra research python research/kit/census_css.py \
        --n-min 4 --n-max 6 --k-min 1 --k-max 2 --d-min 3 --d-max 5 \
        --output census.jsonl

The enumerator currently caps n at 6 because the full-code permutation
canonicalization grows factorially. The enumeration works on check row spaces,
so generator-basis changes are already quotiented out. Exact minimum distance is established through the
repository's SAT certifier; timed-out cases are emitted as unresolved and make
the run's summary incomplete.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import os
import sys
from functools import cache
from typing import TextIO

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", "..", "verify"))

from css import compute_k, verify_css  # noqa: E402
from submit import make_submission  # noqa: E402

MAX_N = 6


def _rref_subspaces(n: int, rank: int | None = None):
    """Yield each subspace of GF(2)^n once as its unique RREF row masks."""
    if n < 0:
        raise ValueError("n must be nonnegative")
    ranks = range(n + 1) if rank is None else (rank,)
    for r in ranks:
        if r < 0 or r > n:
            continue
        if r == 0:
            yield ()
            continue
        for pivots in itertools.combinations(range(n), r):
            pivot_set = set(pivots)
            free_cells = [
                (row, col) for row, pivot in enumerate(pivots) for col in range(pivot + 1, n) if col not in pivot_set
            ]
            for values in itertools.product((0, 1), repeat=len(free_cells)):
                rows = [1 << pivot for pivot in pivots]
                for (row, col), value in zip(free_cells, values):
                    if value:
                        rows[row] |= 1 << col
                yield tuple(rows)


def _rref_masks(rows: tuple[int, ...], n: int) -> tuple[int, ...]:
    """Return the unique RREF basis for row masks in the given column order."""
    work = list(rows)
    pivot_row = 0
    for col in range(n):
        pivot = next(
            (row for row in range(pivot_row, len(work)) if (work[row] >> col) & 1),
            None,
        )
        if pivot is None:
            continue
        work[pivot_row], work[pivot] = work[pivot], work[pivot_row]
        for row in range(len(work)):
            if row != pivot_row and ((work[row] >> col) & 1):
                work[row] ^= work[pivot_row]
        pivot_row += 1
        if pivot_row == len(work):
            break
    return tuple(work[:pivot_row])


def _permute_mask(mask: int, image: tuple[int, ...]) -> int:
    """Apply a qubit permutation where ``image[old_qubit]`` is its new index."""
    out = 0
    while mask:
        bit = mask & -mask
        old = bit.bit_length() - 1
        out |= 1 << image[old]
        mask ^= bit
    return out


def _pack_rref(rows: tuple[int, ...], n: int) -> int:
    """Pack a canonical basis into an integer with the rank in its high bits."""
    payload = sum(row << (n * i) for i, row in enumerate(rows))
    return (len(rows) << (n * n)) | payload


def _unpack_rref(packed: int, n: int) -> tuple[int, ...]:
    rank = packed >> (n * n)
    mask = (1 << (n * n)) - 1
    payload = packed & mask
    return tuple((payload >> (n * i)) & ((1 << n) - 1) for i in range(rank))


def _permutation_actions(spaces: list[tuple[int, ...]], n: int):
    """Precompute each row space's RREF after every qubit permutation."""
    permutations = tuple(itertools.permutations(range(n)))
    result = {}
    for rows in spaces:
        actions = []
        for image in permutations:
            permuted = tuple(_permute_mask(row, image) for row in rows)
            actions.append(_pack_rref(_rref_masks(permuted, n), n))
        result[rows] = tuple(actions)
    return result


def _canonical_pair_key(x_actions: tuple[int, ...], z_actions: tuple[int, ...]) -> tuple[int, int]:
    """Canonicalize under simultaneous qubit permutation and global X/Z swap."""
    best_x, best_z = sorted((x_actions[0], z_actions[0]))
    for x_code, z_code in zip(x_actions[1:], z_actions[1:]):
        candidate_x, candidate_z = sorted((x_code, z_code))
        best_x, best_z = min((best_x, best_z), (candidate_x, candidate_z))
    return best_x, best_z


def _orthogonal(x_rows: tuple[int, ...], z_rows: tuple[int, ...]) -> bool:
    return all((x & z).bit_count() % 2 == 0 for x in x_rows for z in z_rows)


def iter_css_classes(
    n: int,
    *,
    k_min: int = 1,
    k_max: int | None = None,
):
    """Yield distinct CSS code classes ``(HX_rows, HZ_rows, k)`` for one n.

    Equivalence consists of generator-row changes (removed by row-space form),
    physical-qubit permutations, and the global X/Z exchange. Codes are emitted
    as canonical row-mask bases. The iterator does not filter by distance.
    """
    if n < 1 or n > MAX_N:
        raise ValueError(f"n must be between 1 and {MAX_N}")
    if k_min < 0:
        raise ValueError("k_min must be nonnegative")
    if k_max is not None and k_max < k_min:
        raise ValueError("k_max must be greater than or equal to k_min")

    max_k = n if k_max is None else min(n, k_max)
    by_rank = [list(_rref_subspaces(n, r)) for r in range(n + 1)]
    spaces = [space for rank_spaces in by_rank for space in rank_spaces]
    actions = _permutation_actions(spaces, n)
    seen = set()

    for x_rank, x_spaces in enumerate(by_rank):
        for z_rank, z_spaces in enumerate(by_rank[: n - x_rank + 1]):
            k = n - x_rank - z_rank
            if k < k_min or k > max_k:
                continue
            for x_rows in x_spaces:
                x_actions = actions[x_rows]
                for z_rows in z_spaces:
                    if not _orthogonal(x_rows, z_rows):
                        continue
                    key = _canonical_pair_key(x_actions, actions[z_rows])
                    if key in seen:
                        continue
                    seen.add(key)
                    yield _unpack_rref(key[0], n), _unpack_rref(key[1], n), k


def _matrix_from_masks(rows: tuple[int, ...], n: int) -> np.ndarray:
    matrix = np.zeros((len(rows), n), dtype=np.int8)
    for row, bits in enumerate(rows):
        for col in range(n):
            matrix[row, col] = (bits >> col) & 1
    return matrix


def _supports(rows: tuple[int, ...], n: int) -> list[list[int]]:
    return [[col for col in range(n) if (row >> col) & 1] for row in rows]


@cache
def _load_sat_certifier():
    path = os.path.join(_HERE, "..", "..", "verify", "sat_certify.py")
    spec = importlib.util.spec_from_file_location("_qldpc_census_sat_certify", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load trusted SAT certifier at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_css_distance(HX, HZ, *, tlim: float = 600.0) -> dict:
    """Return an exact minimum distance using the repository's SAT certifier.

    Initial and refuting logical witnesses are retained in the returned result.
    The trusted certifier is rerun with each SAT witness's weight until it proves
    that no lighter logical exists. A timeout is returned as unresolved.
    """
    try:
        sat_certify = _load_sat_certifier()
    except ImportError as exc:
        raise RuntimeError(
            "exact census distance requires the research dependencies; run with "
            "`uv run --extra research python research/kit/census_css.py`"
        ) from exc

    doc = make_submission(
        HX,
        HZ,
        name="small-CSS-census",
        construction="Exhaustive CSS row-space enumeration",
        authors=["census"],
        trials=1,
        seed=0,
    )
    while True:
        claimed_d = int(doc["distance"]["d"])
        verdict = sat_certify.certify(doc, tlim=tlim)
        if verdict.get("d_exact"):
            return {
                "exact": True,
                "d": claimed_d,
                "distance": doc["distance"],
                "certification": verdict,
            }

        refuted = False
        for side, result in verdict.get("sides", {}).items():
            if result.get("status") != "SAT":
                continue
            witness = result.get("witness")
            if not witness:
                raise RuntimeError(f"SAT certifier returned no {side} refuting witness")
            new_value = len(witness)
            current_value = int(doc["distance"][side]["value"])
            if new_value >= claimed_d or new_value >= current_value:
                raise RuntimeError(
                    f"SAT certifier returned a non-improving {side} witness of weight {new_value} for d={claimed_d}"
                )
            doc["distance"][side]["value"] = new_value
            doc["distance"][side]["witness"] = witness
            doc["distance"]["d"] = min(
                int(doc["distance"]["X"]["value"]),
                int(doc["distance"]["Z"]["value"]),
            )
            refuted = True

        if refuted:
            continue
        return {
            "exact": False,
            "d": claimed_d,
            "distance": doc["distance"],
            "certification": verdict,
        }


def _code_record(n: int, k: int, x_rows: tuple[int, ...], z_rows: tuple[int, ...], result: dict):
    return {
        "record_type": "code",
        "n": n,
        "k": k,
        "d": result["d"],
        "checks": {"X": _supports(x_rows, n), "Z": _supports(z_rows, n)},
        "distance_witnesses": {
            side: {
                "value": result["distance"][side]["value"],
                "witness": result["distance"][side]["witness"],
            }
            for side in ("X", "Z")
        },
        "distance_certification": result["certification"],
    }


def _write_jsonl(stream: TextIO, record: dict) -> None:
    stream.write(json.dumps(record, sort_keys=True) + "\n")
    stream.flush()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Exhaustively enumerate small CSS code classes and exact distances.")
    parser.add_argument(
        "--n-min",
        type=int,
        default=1,
        help="minimum physical-qubit count (default: 1)",
    )
    parser.add_argument(
        "--n-max",
        type=int,
        default=6,
        help="maximum physical-qubit count (default: 6; max supported: 6)",
    )
    parser.add_argument("--k-min", type=int, default=1, help="minimum encoded-qubit count (default: 1)")
    parser.add_argument("--k-max", type=int, default=None, help="maximum encoded-qubit count (default: n-max)")
    parser.add_argument("--d-min", type=int, default=3, help="minimum exact distance (default: 3)")
    parser.add_argument("--d-max", type=int, default=None, help="maximum exact distance (default: unbounded)")
    parser.add_argument(
        "--tlim",
        type=float,
        default=600.0,
        help="SAT certifier time limit per solve in seconds (default: 600)",
    )
    parser.add_argument("--output", help="JSONL output path (default: stdout)")
    args = parser.parse_args(argv)
    if args.n_min < 1 or args.n_max < args.n_min or args.n_max > MAX_N:
        parser.error(f"require 1 <= n-min <= n-max <= {MAX_N}")
    if args.k_min < 1 or (args.k_max is not None and args.k_max < args.k_min):
        parser.error("require 1 <= k-min <= k-max")
    if args.d_min < 1 or (args.d_max is not None and args.d_max < args.d_min):
        parser.error("require 1 <= d-min <= d-max")
    if args.tlim <= 0:
        parser.error("tlim must be positive")
    return args


def run_census(args, stream: TextIO) -> dict:
    """Run the requested exhaustive range, streaming matches and unresolved cases."""
    params = {
        "n": [args.n_min, args.n_max],
        "k": [args.k_min, args.k_max],
        "d": [args.d_min, args.d_max],
    }
    _write_jsonl(
        stream,
        {
            "record_type": "census",
            "parameters": params,
            "equivalence": ["check-row-basis", "qubit-permutation", "global-XZ-swap"],
            "distance_method": "verify/sat_certify.py",
        },
    )

    classes_seen = 0
    distance_certified = 0
    matches = 0
    unresolved = 0
    for n in range(args.n_min, args.n_max + 1):
        k_max = n if args.k_max is None else min(n, args.k_max)
        for x_rows, z_rows, k in iter_css_classes(n, k_min=args.k_min, k_max=k_max):
            classes_seen += 1
            HX = _matrix_from_masks(x_rows, n)
            HZ = _matrix_from_masks(z_rows, n)
            if not verify_css(HX, HZ) or compute_k(HX, HZ) != k:
                raise RuntimeError("enumerator produced a non-CSS pair or inconsistent k")
            result = exact_css_distance(HX, HZ, tlim=args.tlim)
            if not result["exact"]:
                unresolved += 1
                _write_jsonl(
                    stream,
                    {
                        "record_type": "unresolved",
                        "n": n,
                        "k": k,
                        "checks": {"X": _supports(x_rows, n), "Z": _supports(z_rows, n)},
                        "distance_result": result,
                    },
                )
                continue
            distance_certified += 1
            d = result["d"]
            if d < args.d_min or (args.d_max is not None and d > args.d_max):
                continue
            matches += 1
            _write_jsonl(stream, _code_record(n, k, x_rows, z_rows, result))

    summary = {
        "record_type": "summary",
        "complete": unresolved == 0,
        "classes_seen": classes_seen,
        "distance_certified": distance_certified,
        "matches": matches,
        "unresolved": unresolved,
    }
    _write_jsonl(stream, summary)
    return summary


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as stream:
            summary = run_census(args, stream)
    else:
        summary = run_census(args, sys.stdout)
    return 0 if summary["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Replay the published CSS RIS ladder using the repository's unchanged API.

Build the optional accelerator with `make fast` first. Each trials argument
is spent on each CSS side, not split across the two sides.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    here = Path(__file__).resolve().parent
    repo = here.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", type=Path, default=repo / "codes" / (here.name + ".json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sys.path[:0] = [str(repo / "research/kit"), str(repo / "verify")]
    import numpy as np
    from surrogate import distance_rand_witness
    from submit import save_submission
    from coordination import unique_path
    import gf2_fast  # Fail explicitly instead of silently changing backend.

    doc = json.loads(args.code.read_text())
    ladder = json.loads((here / "ris-ladder.json").read_text())
    checks_sha = hashlib.sha256(json.dumps(doc["checks"], sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    assert checks_sha == ladder["checks_sha256"], "different check basis"
    matrices = {}
    for side in ("X", "Z"):
        matrix = np.zeros((len(doc["checks"][side]), doc["n"]), dtype=np.int8)
        for row, support in zip(matrix, doc["checks"][side]):
            row[support] = 1
        matrices[side] = matrix
    for index, rung in enumerate(ladder["rungs"]):
        start = time.process_time()
        result = distance_rand_witness(matrices["X"], matrices["Z"],
            trials=rung["trials_per_css_side"], seed=rung["seed"],
            backend="fast", threads=1, pair_depth=16)
        receipt = dict(seed=rung["seed"], trials_per_css_side=rung["trials_per_css_side"],
            raw_reading=int(result.weight), side=result.side,
            support=list(result.support), rejected=result.rejected,
            checks_sha256=checks_sha, cpu_seconds=time.process_time() - start)
        # Preserve every witness before interpreting or checking the result.
        (args.output / f"rung-{index}.json").write_text(json.dumps(receipt, indent=2) + "\n")
        assert not result.rejected and result.side in ("X", "Z") and result.support
        updated = copy.deepcopy(doc)
        updated["distance"][result.side] = dict(value=int(result.weight),
            confidence="upper_bound", witness=list(result.support))
        updated["distance"]["d"] = min(updated["distance"][s]["value"] for s in ("X", "Z"))
        destination = unique_path(str(args.output / f"candidate-{index}.json"), updated)
        save_submission(updated, destination)
        print(json.dumps(receipt), flush=True)
        if int(result.weight) < doc["distance"]["d"]:
            raise RuntimeError("saved a refutation below the submitted distance")


if __name__ == "__main__":
    main()

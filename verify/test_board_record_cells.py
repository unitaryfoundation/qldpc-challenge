"""board_record_slugs compares a row only with the rows that can dominate it (issue #5578).

The relation is unchanged: dominated on (n, k, d, w) by a code of the same
type whose locality and weight classes are stricter or equal. Only the pairs
compared changed, so the result is checked against the original quadratic
form on random boards.
"""
import json
import os
import random

import gate_changed as G


def _reference(code_root):
    rows = []
    for name in sorted(os.listdir(os.path.join(code_root, "codes"))):
        d = json.load(open(os.path.join(code_root, "codes", name)))
        w = max((len(s) for s in G.generator_supports(d)), default=0)
        rows.append((name[:-5], d["n"], d["k"], d["distance"]["d"], w,
                     G._weight_rank(w), G._locality_rank(d), d.get("code_type", "CSS")))
    rec = set()
    for i, a in enumerate(rows):
        dominated = any(
            j != i and b[7] == a[7] and b[5] <= a[5] and b[6] <= a[6]
            and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3] and b[4] <= a[4]
            and (b[1] < a[1] or b[2] > a[2] or b[3] > a[3] or b[4] < a[4])
            for j, b in enumerate(rows))
        if not dominated:
            rec.add(a[0])
    return rec


def test_the_record_set_matches_the_quadratic_form_on_random_boards(tmp_path):
    rng = random.Random(5578)
    for trial in range(6):
        root = tmp_path / f"board{trial}"
        (root / "codes").mkdir(parents=True)
        for i in range(40):
            n = rng.randrange(10, 40)
            w = rng.choice([2, 3, 4, 6, 8])
            doc = {"n": n, "k": rng.randrange(1, 8), "distance": {"d": rng.randrange(1, 7)},
                   "code_type": rng.choice(["CSS", "CSS", "stabilizer"]),
                   "checks": {"X": [list(range(w))], "Z": [list(range(w))]}}
            if doc["code_type"] == "stabilizer":
                doc["checks"] = {"S": [{"X": list(range(w)), "Z": []}]}
            if rng.random() < 0.4:
                doc["locality"] = {"coordinates": [[q, 0] for q in range(n)], "layers": 1}
            (root / "codes" / f"r{i}-{n}-{doc['k']}-{doc['distance']['d']}.json").write_text(json.dumps(doc))
        assert G.board_record_slugs(str(root)) == _reference(str(root))

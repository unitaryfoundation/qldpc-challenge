"""The committed GAP SmallGroup tables must be groups and rebuild their board entries (#3378).

Run: uv run --extra research pytest research/test_group_tables.py
"""
import glob
import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(HERE, "kit"), os.path.join(ROOT, "verify")]

import rebuild  # noqa: E402
from group_algebra import build_2bga, small_group  # noqa: E402
from qldpc_verify import verify  # noqa: E402

TABLES = sorted(glob.glob(os.path.join(HERE, "kit", "groups", "smallgroup_*.json")))

# slug -> (order, gap_id, a, b) exactly as the entry's note states them
ENTRIES = {
    "128-20-14": (64, 61, [7, 9, 11, 30, 32, 34, 47, 59], [3, 6, 23, 27, 41, 46, 47, 56]),
    "128-21-8": (64, 120, [6, 24, 37, 60], [5, 33, 44, 51]),
    "128-13-10": (64, 182, [2, 6, 17, 23], [6, 16, 37, 59]),
}


@pytest.mark.parametrize("path", TABLES, ids=os.path.basename)
def test_committed_table_is_a_group_with_the_identity_first(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    n = doc["order"]
    mul = np.asarray(doc["table"], dtype=np.int64)
    assert os.path.basename(path) == f"smallgroup_{n}_{doc['gap_id']}.json"
    assert doc["gap_version"] and doc["smallgrp_version"]
    assert mul.shape == (n, n) and len(doc["elements"]) == n
    ar = np.arange(n)
    assert (mul[0] == ar).all() and (mul[:, 0] == ar).all()
    assert all(len(set(r)) == n for r in mul) and all(len(set(c)) == n for c in mul.T)
    assert (mul[mul[:, :, None], ar[None, None, :]] == mul[ar[:, None, None], mul[None, :, :]]).all()
    assert (small_group(n, doc["gap_id"]) == mul).all()


@pytest.mark.parametrize("slug", sorted(ENTRIES))
def test_the_notes_supports_rebuild_the_board_entry(slug):
    order, gap_id, a, b = ENTRIES[slug]
    HX, HZ = build_2bga(small_group(order, gap_id), a, b)
    with open(os.path.join(ROOT, "codes", f"{slug}.json"), encoding="utf-8") as f:
        doc = json.load(f)
    assert rebuild.fingerprint_of(HX, HZ) == verify(doc)["fingerprint"]


def test_the_recipe_form_runs_through_rebuild():
    order, gap_id, a, b = ENTRIES["128-20-14"]
    HX, HZ = rebuild.rebuild("group_algebra.build_2bga_small_group",
                             {"order": order, "gap_id": gap_id, "a": a, "b": b})
    assert HX.shape == (64, 128) and HZ.shape == (64, 128)


def test_a_missing_table_names_the_exporter():
    with pytest.raises(FileNotFoundError, match="cayley_table.g"):
        small_group(64, 1)

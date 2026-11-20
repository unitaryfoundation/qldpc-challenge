"""Tests for the weekly whole-board refutation driver (verify/refute_board.py).

SHARD  The K shards partition the board, every entry in exactly one, and the
       board is ordered largest n first so a binding budget drops small entries.
SEED   An entry's search seed depends on the run seed and its path only, so one
       run seed reproduces an entry's search from any shard or order.
BUDGET Once the wall-clock budget is spent no new entry is opened; the report
       lists the unreached entries and the verdict is a failure (issue #2896),
       never a quiet partial pass.
CLOSED A refuter error or a refutation fails the run, as before.
SUMMARY The cross-shard summary passes only when the expected number of reports
       are present and each is complete with nothing refuted or errored.

Run: uv run python verify/test_refute_board.py  (or pytest)
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refute_board as RB

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def _board(tmp, slugs, with_distance=True):
    """Write a fake codes/ directory; the refuter is stubbed, so the documents only need the fields the driver reads."""
    os.makedirs(os.path.join(tmp, "codes"), exist_ok=True)
    for slug in slugs:
        doc = {"n": int(slug.split("-")[0]), "k": 1}
        if with_distance:
            doc["distance"] = {"d": int(slug.split("-")[2])}
        with open(os.path.join(tmp, "codes", slug + ".json"), "w") as f:
            json.dump(doc, f)
    return RB.board_paths(tmp)


class _Clock:
    """Fake wall clock that advances a fixed step per read."""

    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def test_order_and_shards():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["10-2-3", "672-20-32", "144-12-12", "672-18-30", "9-1-3"])
        names = [os.path.basename(p) for p in paths]
        check(
            "largest n first, ties by name",
            names == ["672-18-30.json", "672-20-32.json", "144-12-12.json", "10-2-3.json", "9-1-3.json"],
        )
        for k in range(1, 8):
            shards = [RB.shard_paths(paths, f"{i}/{k}") for i in range(k)]
            flat = sorted(p for s in shards for p in s)
            check(f"{k} shards partition the board", flat == sorted(paths) and len(flat) == len(paths))
            check(f"{k} shards balanced", max(len(s) for s in shards) - min(len(s) for s in shards) <= 1)
        check("shard 0/2 holds entries 0, 2, 4", RB.shard_paths(paths, "0/2") == paths[0::2])
        check("no shard means the whole board", RB.shard_paths(paths, None) == paths)
        for bad in ("2/2", "-1/3", "1", "a/b", "0/0"):
            try:
                RB.shard_paths(paths, bad)
                check(f"rejects shard {bad!r}", False)
            except ValueError:
                check(f"rejects shard {bad!r}", True)


def test_scope_records_or_all():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["672-20-32", "144-12-12", "10-2-3"])
        seen = []

        def records(root):
            seen.append(root)
            return {"672-20-32", "10-2-3"}

        kept = RB.scope_paths(paths, "records", tmp, records=records)
        check(
            "records scope keeps the named slugs in board order",
            [os.path.basename(p) for p in kept] == ["672-20-32.json", "10-2-3.json"] and seen == [tmp],
        )
        check(
            "all scope keeps everything and asks nothing",
            RB.scope_paths(paths, "all", tmp, records=records) == paths and seen == [tmp],
        )
        try:
            RB.scope_paths(paths, "frontier", tmp, records=records)
            check("rejects an unknown scope", False)
        except ValueError:
            check("rejects an unknown scope", True)
        check(
            "the default record function runs on the given root (these stubs have no checks, so no records)",
            RB.scope_paths(paths, "records", tmp) == [],
        )


def test_file_seed_is_path_and_run_seed_only():
    s1 = RB.file_seed(7, "codes/10-2-3.json")
    check("same inputs, same seed", s1 == RB.file_seed(7, "codes/10-2-3.json"))
    check("run seed changes it", s1 != RB.file_seed(8, "codes/10-2-3.json"))
    check("path changes it", s1 != RB.file_seed(7, "codes/10-2-3-b.json"))
    check("fits the refuter's 31-bit seed", 0 <= s1 < 2**31)


def test_budget_stops_and_fails_loudly():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["30-2-3", "20-2-3", "10-2-3", "8-2-2"])
        calls = []

        def stub(doc, seed):
            calls.append(doc["n"])
            return False, None, None, 100

        # the clock is read once at start and once per entry, 10 s apart: the
        # first entry opens at 10 s elapsed, the second would open at 20 s >= 15
        rep = RB.refute_paths(paths, 5, max_seconds=15, root=tmp, refute=stub, clock=_Clock(10.0), out=lambda s: None)
        check("stopped at the budget", rep["stopped_by"] == "budget" and not rep["complete"])
        check("largest entries were checked first", calls == [30] and rep["checked"] == 1)
        check(
            "unreached lists the rest in order",
            rep["unreached"] == ["codes/20-2-3.json", "codes/10-2-3.json", "codes/8-2-2.json"],
        )
        code, line = RB.verdict(rep)
        check("incomplete coverage is a failure", code == 1 and line.startswith("FAIL: incomplete coverage"))
        check("summary line carries the counts", RB.summary_line(rep).startswith("1/4 codes checked;"))

        rep = RB.refute_paths(paths, 5, max_seconds=None, root=tmp, refute=stub, out=lambda s: None)
        check("no budget reaches every entry", rep["complete"] and rep["checked"] == 4 and rep["unreached"] == [])
        check("complete clean run passes", RB.verdict(rep) == (0, "PASS: no over-claim found this run."))


def test_signal_mid_entry_is_reported():
    with tempfile.TemporaryDirectory() as tmp:
        paths = _board(tmp, ["30-2-3", "20-2-3", "10-2-3"])

        def stub(doc, seed):
            if doc["n"] == 20:
                raise RB._Stopped("SIGTERM")
            return False, None, None, 100

        rep = RB.refute_paths(paths, 5, root=tmp, refute=stub, out=lambda s: None)
        check(
            "the interrupted entry and its successors are unreached",
            rep["stopped_by"] == "SIGTERM"
            and rep["checked"] == 1
            and rep["unreached"] == ["codes/20-2-3.json", "codes/10-2-3.json"],
        )
        check("a signalled run fails", RB.verdict(rep)[0] == 1)


def test_refuted_and_errored_fail_closed():
    with tempfile.TemporaryDirectory() as tmp:
        _board(tmp, ["30-2-3", "20-2-3", "10-2-3"])
        paths = _board(tmp, ["5-1-0"], with_distance=False)

        def stub(doc, seed):
            if doc["n"] == 30:
                return True, 2, {"X": [0, 1]}, 100
            if doc["n"] == 20:
                raise RuntimeError("boom")
            return False, None, None, 100

        lines = []
        rep = RB.refute_paths(paths, 5, root=tmp, refute=stub, out=lines.append)
        check(
            "refutation recorded with claimed and found weights",
            rep["refuted"] == [["codes/30-2-3.json", 2, 3, {"X": [0, 1]}]],
        )
        check("error recorded, fails closed", rep["errored"] == [["codes/20-2-3.json", "RuntimeError: boom"]])
        check(
            "entry without a distance claim is skipped, not checked",
            rep["skipped"] == ["codes/5-1-0.json"] and rep["checked"] == 2,
        )
        check(
            "log lines keep the REFUTED/ERROR/ok prefixes",
            [ln.split()[0] for ln in lines] == ["REFUTED", "ERROR", "ok"],
        )
        check(
            "complete but dirty run fails",
            RB.verdict(rep) == (1, "FAIL: distance claims need review (see REFUTED/ERROR above)."),
        )


def test_summarize():
    def rep(shard, complete=True, refuted=(), errored=(), unreached=()):
        return {
            "shard": shard,
            "seed": 1,
            "total": 10,
            "checked": 10 - len(unreached),
            "skipped": [],
            "refuted": list(refuted),
            "errored": list(errored),
            "unreached": list(unreached),
            "stopped_by": None if complete else "budget",
            "complete": complete,
            "seconds": 600.0,
        }

    with tempfile.TemporaryDirectory() as tmp:

        def write(i, r):
            p = os.path.join(tmp, f"refute-shard-{i}.json")
            json.dump(r, open(p, "w"))
            return p

        write(0, rep("0/2"))
        write(1, rep("1/2"))
        pattern = os.path.join(tmp, "refute-shard-*.json")
        out = []
        check("two clean complete shards pass", RB.summarize([pattern], expect=2, out=out.append) == 0)
        check(
            "table lists both shards and a total row",
            out[-1].count("| complete |") == 2 and "| all | | 20/20 |" in out[-1],
        )
        check("a missing shard report fails", RB.summarize([pattern], expect=3, out=lambda s: None) == 1)
        write(1, rep("1/2", complete=False, unreached=["codes/10-2-3.json"]))
        check("an incomplete shard fails", RB.summarize([pattern], expect=2, out=lambda s: None) == 1)
        write(1, rep("1/2", refuted=[["codes/30-2-3.json", 2, 3, {"X": [0]}]]))
        out = []
        check(
            "a refutation fails and is named",
            RB.summarize([pattern], expect=2, out=out.append) == 1 and "REFUTED codes/30-2-3.json" in out[-1],
        )
        check(
            "no reports at all fails",
            RB.summarize([os.path.join(tmp, "nothing-*.json")], expect=2, out=lambda s: None) == 1,
        )


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and name != "test_main":
            print(name)
            fn()
    print(f"\n{len(_fail)} failure(s)")
    return 1 if _fail else 0


def test_main():
    """Pytest entry point; the suite body lives in main()."""
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())

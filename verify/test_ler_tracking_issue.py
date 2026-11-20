"""Tests for the LER replication tracking-issue body (verify/ler_tracking_issue.py, issue #2820).

ROWS    Every failed or unverifiable point of a current receipt appears once with
        its slug, basis, rate, claimed and replica rates, and measured_at; verified
        points do not.
CLAIM   A point the budget could not measure at all has no claimed rate in the
        receipt; the claimed rate is read from the entry instead.
STALE   A receipt whose digest no longer matches the entry, or whose entry is
        gone, contributes no rows and is counted in the footer.
EMPTY   With nothing to report the body is the marker, the explanation, and a
        zero-count footer, and the summary line says points=0.
CLI     --out writes the body and prints only the summary line.

Run: uv run python verify/test_ler_tracking_issue.py  (or pytest)
"""

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ler_receipts as lr
import ler_tracking_issue as T

_fail = []


def check(name, cond):
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}")
    if not cond:
        _fail.append(name)


def _entry(root, slug, points):
    """Write a measured-rate entry with committed circuits; returns its claim digest."""
    doc = {
        "n": 10,
        "k": 2,
        "circuit": {
            "rounds": 3,
            "ler": {
                "X": [{"p": p, "shots": s, "failures": f, "seed": 1} for p, s, f in points],
                "Z": [{"p": p, "shots": s, "failures": f, "seed": 2} for p, s, f in points],
            },
        },
    }
    os.makedirs(os.path.join(root, "codes"), exist_ok=True)
    with open(os.path.join(root, "codes", slug + ".json"), "w") as fh:
        json.dump(doc, fh)
    cdir = os.path.join(root, "circuits", slug)
    os.makedirs(cdir, exist_ok=True)
    for fname in ("memory_x.stim", "memory_z.stim"):
        with open(os.path.join(cdir, fname), "w") as fh:
            fh.write(f"# {slug} {fname}\n")
    return lr.claim_digest(doc, cdir)


def _receipt(root, slug, digest, points, when="2026-10-12T10:30:00+00:00"):
    rec = {
        "receipt_version": "1",
        "slug": slug,
        "claim_digest": digest,
        "measured_at": when,
        "head_sha": "abc",
        "points": points,
        "ok": all(r.get("status") == "verified" for side in points.values() for r in side.values()),
    }
    lr.write_receipt(root, rec)


def _fixture(root):
    d1 = _entry(root, "10-2-2", [(0.002, 10000, 200), (0.001, 20000, 100)])
    _receipt(
        root,
        "10-2-2",
        d1,
        {
            "X": {
                "0.002": {
                    "status": "failed",
                    "p": 0.002,
                    "claimed_p_shot": 0.02,
                    "replica_p_shot": 0.031,
                    "replica_shots": 8000,
                    "replica_failures": 248,
                    "sigma": 0.0019,
                    "detectable_factor": 1.4,
                    "runs": [],
                },
                "0.001": {
                    "status": "verified",
                    "p": 0.001,
                    "claimed_p_shot": 0.005,
                    "replica_p_shot": 0.0051,
                    "replica_shots": 30000,
                    "replica_failures": 153,
                    "sigma": 0.0004,
                    "detectable_factor": 1.3,
                    "runs": [],
                },
            },
            "Z": {
                "0.002": {
                    "status": "verified",
                    "p": 0.002,
                    "claimed_p_shot": 0.02,
                    "replica_p_shot": 0.0198,
                    "replica_shots": 8000,
                    "replica_failures": 158,
                    "sigma": 0.0019,
                    "detectable_factor": 1.4,
                    "runs": [],
                },
                "0.001": {
                    "status": "unverifiable",
                    "replica_shots": 0,
                    "replica_failures": 0,
                    "runs": [],
                    "detectable_factor": None,
                },
            },
        },
    )
    d2 = _entry(root, "12-2-3", [(0.003, 5000, 50)])
    _receipt(
        root,
        "12-2-3",
        "0" * 64,
        {  # stale: claim edited after the measurement
            "X": {
                "0.003": {
                    "status": "failed",
                    "claimed_p_shot": 0.01,
                    "replica_p_shot": 0.02,
                    "replica_shots": 100,
                    "replica_failures": 2,
                    "detectable_factor": 2.0,
                    "runs": [],
                }
            }
        },
    )
    _receipt(
        root,
        "99-9-9",
        "1" * 64,
        {  # stale: entry removed
            "Z": {
                "0.001": {
                    "status": "unverifiable",
                    "replica_shots": 0,
                    "replica_failures": 0,
                    "runs": [],
                    "detectable_factor": None,
                }
            }
        },
    )
    return d1, d2


def test_rows_and_stale():
    with tempfile.TemporaryDirectory() as root:
        _fixture(root)
        rows, stale, receipts = T.collect(root)
        check("three receipts read", receipts == 3)
        check(
            "two reported points, failed first",
            [(r["slug"], r["basis"], r["p"], r["status"]) for r in rows]
            == [("10-2-2", "X", "0.002", "failed"), ("10-2-2", "Z", "0.001", "unverifiable")],
        )
        check(
            "failed row carries claimed and replica rates and measured_at",
            rows[0]["claimed_p_shot"] == 0.02
            and rows[0]["replica_p_shot"] == 0.031
            and rows[0]["measured_at"] == "2026-10-12T10:30:00+00:00",
        )
        check(
            "unmeasured point takes its claimed rate from the entry",
            rows[1]["claimed_p_shot"] == 100 / 20000 and rows[1]["replica_p_shot"] is None,
        )
        check(
            "stale receipts named with their reason",
            stale == [("12-2-3", "claim edited after the measurement"), ("99-9-9", "entry removed")],
        )
        text = T.body(rows, stale, receipts)
        check("body starts with the marker", text.startswith(T.MARKER + "\n"))
        check(
            "table has one line per reported point",
            text.count("| `10-2-2` |") == 2 and "| X | 0.002 | failed | 0.02 | 0.031 | 8000 (248) | 1.4 |" in text,
        )
        check("verified points and stale receipts are not rows", "0.0198" not in text and "| `12-2-3` |" not in text)
        check(
            "footer counts",
            "2 point(s) (1 failed, 1 unverifiable) across 1 entry, from 3 receipt(s)." in text
            and "2 receipt(s) left out as stale" in text,
        )
        check("summary line", T.summary(rows, stale, receipts) == "points=2 failed=1 unverifiable=1 stale=2 receipts=3")


def test_empty_board():
    with tempfile.TemporaryDirectory() as root:
        rows, stale, receipts = T.collect(root)
        check("nothing collected", (rows, stale, receipts) == ([], [], 0))
        text = T.body(rows, stale, receipts)
        check(
            "empty body has marker and zero footer",
            text.startswith(T.MARKER)
            and "0 point(s) (0 failed, 0 unverifiable) across 0 entries, from 0 receipt(s)." in text
            and "|" not in text.split("\n", 1)[1].replace("`", ""),
        )
        check(
            "empty summary", T.summary(rows, stale, receipts) == "points=0 failed=0 unverifiable=0 stale=0 receipts=0"
        )
        d = _entry(root, "10-2-2", [(0.002, 10000, 200)])
        _receipt(
            root,
            "10-2-2",
            d,
            {
                "X": {
                    "0.002": {
                        "status": "verified",
                        "claimed_p_shot": 0.02,
                        "replica_p_shot": 0.02,
                        "replica_shots": 8000,
                        "replica_failures": 160,
                        "detectable_factor": 1.4,
                        "runs": [],
                    }
                }
            },
        )
        rows, stale, receipts = T.collect(root)
        check("all-verified receipt reports nothing", rows == [] and stale == [] and receipts == 1)


def test_cli():
    with tempfile.TemporaryDirectory() as root:
        _fixture(root)
        out_path = os.path.join(root, "body.md")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = T.main(["--root", root, "--out", out_path])
        check(
            "--out prints only the summary line",
            code == 0 and buf.getvalue() == "points=2 failed=1 unverifiable=1 stale=2 receipts=3\n",
        )
        check("--out wrote the body", open(out_path).read().startswith(T.MARKER))
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = T.main(["--root", root])
        check("without --out the body goes to stdout", code == 0 and buf.getvalue().startswith(T.MARKER))


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

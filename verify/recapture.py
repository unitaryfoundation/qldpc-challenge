"""Keep every logical a refutation search finds, for a recapture census (issue #2897).

The weekly sweep (``refute_board.py``) re-runs the bounded RIS search over the
board with a fresh seed each week so that, in the words of its docstring,
"over time the board accumulates search coverage". Until now that coverage
materialized only when a run happened to find something lighter than the
claim: ``ris_min_logical``'s ``consider`` keeps a strictly lighter best and
drops every other logical it produced, so the recapture data that weeks of
independent-seed runs generate (which logical did run k find, and did run
k+1 find it again) was never written down. Search depth stayed prose.

This module is the sweep-side record of that data, and nothing else:

* :class:`Capture` is handed to ``heuristic_distance.refute_check`` and
  receives, from inside the search's own ``consider``, every nontrivial
  logical at weight <= the claimed distance, deduplicated by vector. The
  search's result is unchanged by it: the capture reads what ``consider``
  already computed and never writes ``best``.
* :func:`entry_record` turns one entry's capture into a JSON record: run and
  file seed, trials, wall time, battery, and per side every logical as an
  operator id (the vector) and a class id (its coset modulo the stabilizer
  row space of that side), each with its weight.
* :func:`append_record` appends one line per entry to a JSONL file as the
  sweep goes, so a cancelled run keeps what it completed. That is also the
  per-entry coverage record issue #2896 found missing.

What it is not. The record is never a gate input: ``verify/`` reads nothing
back from it, no entry carries it, and no pass/fail decision consults it.
It is a "we looked and found this" artifact, which is exactly the shape
``refutation_cache.py`` refuses to trust, and the same threat model applies
unchanged. The offline estimator over these records lives in
``research/audits/recapture.py``; whether anything it computes is ever shown
is a decision for after it has been calibrated.

Two ids per logical, deliberately. The issue asked for one canonical id per
logical class modulo the stabilizer row space, so that the same class found
in two presentations counts once. That is the right unit for "is this class
known", and it is recorded as ``cls``. It is the wrong unit for a census of
minimum-weight logicals: a k = 1 code has one nontrivial class per side
however many weight-d operators present it (the Steane code's seven
weight-3 X logicals are one class), and the number of weight-d operators is
what a failure-mechanism count or a d-only comparison needs. So the vector
itself is recorded too, as ``op``. The estimator reports either unit; the
calibration in ``research/audits/test_recapture.py`` uses both.
"""
import datetime
import hashlib
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gf2  # noqa: E402
import heuristic_distance as H  # noqa: E402

RECORD_VERSION = 1
# Distinct operators kept per side per entry. A code whose minimum weight the
# search reaches on most trials can present thousands of weight-d operators
# (the gross code showed 1,758 weight-12 X operators in one 10 s run); past
# the cap new ones are counted under ``overflow`` and not kept, and the
# estimator marks that weight class censored.
DEFAULT_CAP = 1000
# Hex digits of an id: 48 bits, so a collision among the ten thousand or so
# operators one entry can accumulate has odds around one in ten million.
ID_HEX = 12


def _digest(v):
    return hashlib.sha256(np.packbits(np.asarray(v, dtype=np.int8) % 2).tobytes()).hexdigest()[:ID_HEX]


def operator_id(v):
    """Id of the logical operator ``v`` itself: two vectors differ, two ids differ."""
    return _digest(v)


class Canonicalizer:
    """Coset representative of a logical modulo a stabilizer row space.

    Reduces a vector against the RREF of ``H_row`` (the side's own checks:
    ``HX`` for an X logical, ``HZ`` for a Z logical, ``(A | B)`` for a Pauli
    logical), so two presentations of one logical class reduce to the same
    vector and the same id.
    """

    def __init__(self, H_row):
        self.R, self.piv = gf2.rref(H_row)

    def representative(self, v):
        v = np.asarray(v, dtype=np.int8).copy()
        for i, c in enumerate(self.piv):
            if v[c]:
                v ^= self.R[i]
        return v

    def class_id(self, v):
        return _digest(self.representative(v))


def canonicalizers(doc):
    """One :class:`Canonicalizer` per side the search reports for ``doc``."""
    n = int(doc["n"])
    if H._is_stabilizer(doc):
        A, B = H.stabilizer_matrices(doc)
        return {"P": Canonicalizer(np.concatenate([A, B], axis=1))}
    return {"X": Canonicalizer(H._matrix(doc["checks"]["X"], n)),
            "Z": Canonicalizer(H._matrix(doc["checks"]["Z"], n))}


class SideSink:
    """What one side's search found at weight <= ``threshold``, by vector."""

    def __init__(self, threshold, cap=DEFAULT_CAP):
        self.threshold = int(threshold)
        self.cap = int(cap)
        self.found = {}          # vector bytes -> weight
        self.hits = 0            # every time the search produced a kept-or-counted logical
        self.overflow = 0        # distinct vectors seen past the cap

    def add(self, rows, weights):
        """Record the rows ``consider`` found at weight <= threshold."""
        rows = np.ascontiguousarray(rows, dtype=np.int8)
        for row, w in zip(rows, weights):
            self.hits += 1
            key = row.tobytes()
            if key in self.found:
                continue
            if len(self.found) >= self.cap:
                self.overflow += 1
                continue
            self.found[key] = int(w)

    def vectors(self):
        """``(vector, weight)`` pairs, in insertion order."""
        return [(np.frombuffer(k, dtype=np.int8), w) for k, w in self.found.items()]


class Capture:
    """Everything a refutation search found at weight <= ``threshold``, per side.

    Pass one to ``heuristic_distance.refute_check(doc, ..., capture=cap)``;
    the search fills ``sides`` and sets ``result`` to its own ``estimate``
    report, so the record knows which battery ran.
    """

    def __init__(self, threshold, cap=DEFAULT_CAP):
        self.threshold = int(threshold)
        self.cap = int(cap)
        self.sides = {}
        self.result = None

    def side(self, name):
        if name not in self.sides:
            self.sides[name] = SideSink(self.threshold, self.cap)
        return self.sides[name]

    def add_vector(self, name, v, w):
        """Record one validated logical (the fold pass reports one per side)."""
        w = int(w)
        if 0 < w <= self.threshold:
            self.side(name).add(np.asarray(v, dtype=np.int8)[None, :], [w])

    def captured(self):
        return sum(len(s.found) for s in self.sides.values())


def battery_of(capture, max_seconds=10.0):
    """Which search ran: the stratum the estimator groups runs by.

    ``key`` drops the per-entry counts the method string carries (the number
    of orbit partitions can vary with the seed), so one entry's runs under
    one battery share a key.
    """
    res = capture.result or {}
    method = str(res.get("method") or "ris")
    bare = re.sub(r"\(.*?\)", "", method)
    return {"method": method,
            "key": f"{bare}/{'fast' if 'gf2_fast' in method else 'py'}/{max_seconds:g}s",
            "trials": res.get("trials"), "max_seconds": max_seconds,
            "accelerated": "gf2_fast" in method,
            "fold_partitions": res.get("fold_partitions", 0)}


def entry_record(doc, slug, *, run_seed, file_seed, capture, seconds, refuted,
                 d_found, trials, battery):
    """One entry's record for one run: what was searched and what was found.

    Each side's logicals are stored as three parallel lists, ``w``, ``op``,
    and ``cls``, sorted by weight then operator id; a list of objects would
    double the size of a record that can hold a thousand entries per side.
    """
    canon = canonicalizers(doc)
    sides = {}
    for name, sink in capture.sides.items():
        rows = []
        for v, w in sink.vectors():
            rows.append((int(w), operator_id(v),
                         canon[name].class_id(v) if name in canon else None))
        rows.sort(key=lambda r: (r[0], r[1]))
        sides[name] = {"captured": len(rows), "overflow": sink.overflow, "hits": sink.hits,
                       "w": [r[0] for r in rows], "op": [r[1] for r in rows],
                       "cls": [r[2] for r in rows]}
    return {"record_version": RECORD_VERSION, "slug": slug,
            "run_seed": int(run_seed), "file_seed": int(file_seed),
            "claimed_d": int(doc["distance"]["d"]), "threshold": capture.threshold,
            "cap": capture.cap, "trials": trials, "seconds": round(float(seconds), 2),
            "battery": battery, "refuted": bool(refuted), "d_found": d_found,
            "sides": sides,
            "recorded_at": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds")}


def append_record(path, rec):
    """Append ``rec`` as one JSON line and flush it to disk; return ``path``."""
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return path

"""Observe unmodified Python/Numba search routines in persistent CPU workers."""

import importlib
import json
import os
import time
from pathlib import Path

import common  # noqa: F401 -- initialize repository import paths
import gf2
import heuristic_distance
import numpy as np

_BARRIER = None
_STOP = None
_QD = None


class SearchFinished(Exception):
    """A benchmark deadline or observed target ends the current search."""


class Recorder:
    """Durably save improving witnesses before returning timing information."""

    def __init__(self, path, seconds, target=None, stop=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x")
        self.seconds, self.target, self.stop = seconds, target, stop
        self.start = time.perf_counter()
        self.cpu_start = time.process_time()
        self.trials = 0
        self.best = None
        self.events = []

    def observe(self, weight, support, trials):
        """Count completed trials, persisting every improving returned support."""
        self.trials += int(trials)
        elapsed = time.perf_counter() - self.start
        support = [int(q) for q in support]
        if support and (self.best is None or weight < self.best):
            event = {
                "seconds": elapsed,
                "weight": int(weight),
                "support": support,
                "trials": self.trials,
                "within_budget": elapsed <= self.seconds,
            }
            self.stream.write(json.dumps(event) + "\n")
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.events.append(event)
            self.best = int(weight)
        reached = support and self.target is not None and weight <= self.target and elapsed <= self.seconds
        if reached and self.stop is not None:
            self.stop.set()
        return reached or elapsed >= self.seconds or (self.stop is not None and self.stop.is_set())

    def finish(self):
        """Close evidence before reporting a run complete."""
        self.stream.close()
        return {
            "search_seconds": time.perf_counter() - self.start,
            "cpu_seconds": time.process_time() - self.cpu_start,
            "trials": self.trials,
            "events": self.events,
            "raw_file": str(self.path),
            "status": "completed",
        }


def initialize(barrier, stop, load_qdist):
    """Import/JIT once per worker, outside timed search runs."""
    global _BARRIER, _STOP, _QD  # noqa: PLW0603 -- initialized once in each spawned process
    _BARRIER, _STOP = barrier, stop
    if load_qdist:
        _QD = importlib.import_module("codedistance.distance")


def ready(_worker):
    """Wait for all worker imports before beginning a benchmark."""
    _BARRIER.wait(timeout=120)
    return True


def search(job):
    """Run one independent population or RIS shard with a common start barrier."""
    own, opposite, logicals = job["own"], job["opposite"], job["logicals"]
    setup_start = time.perf_counter()
    kernel = gf2.kernel_basis(opposite) if job["method"] == "numpy" else None
    setup_seconds = time.perf_counter() - setup_start
    _BARRIER.wait(timeout=120)
    recorder = Recorder(job["path"], job["seconds"], job["target"], _STOP)
    try:
        if job["method"] == "numpy":
            # The public routine normally computes these once. Reuse them
            # across observation batches without changing its search loop.
            original_kernel, original_logicals = gf2.kernel_basis, gf2.logical_basis
            gf2.kernel_basis = lambda _h: kernel
            gf2.logical_basis = lambda _a, _b: logicals
            try:
                batch, number = 1, 0
                while True:
                    before = time.perf_counter()
                    weight, vector = heuristic_distance.ris_min_logical(
                        own, opposite, trials=batch, seed=job["seed"] + number * 1000003, pair_depth=8
                    )
                    support = np.flatnonzero(vector).tolist() if vector is not None else []
                    if recorder.observe(weight, support, batch):
                        break
                    duration = time.perf_counter() - before
                    batch = max(1, min(32, int(batch * 0.05 / max(duration, 1e-6))))
                    number += 1
            finally:
                gf2.kernel_basis, gf2.logical_basis = original_kernel, original_logicals
        else:
            original = _QD.permMinRowsK

            def observed(*args):
                result = original(*args)
                weight, rows = result[:2]
                if recorder.observe(int(weight), np.flatnonzero(rows[0]), 1):
                    raise SearchFinished
                return result

            _QD.permMinRowsK = observed
            try:
                # 100 candidates per generation, matching the default 10k/100
                # schedule. More generations permit a deadline-controlled run
                # without restarting or changing the population size.
                params = {
                    "method": "QDistEvol" if job["method"] == "qdistevol" else "QDistRndMW",
                    "iterCount": 1000000,
                    "genCount": 10000,
                    "offspring": 10,
                }
                _QD.QDistEvol(opposite, logicals, tB=1, params=params, seed=job["seed"])
            except SearchFinished:
                pass
            finally:
                _QD.permMinRowsK = original
    finally:
        result = recorder.finish()
    result["setup_seconds"] = setup_seconds
    result["worker_seed"] = job["seed"]
    return result

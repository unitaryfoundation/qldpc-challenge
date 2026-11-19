"""Measured logical error rate for the circuit tier.

The circuit tier certifies d_circ, a floor. Two schedules with the same d_circ
can differ substantially in measured logical error rate, because the number of
minimum-weight fault paths enters the rate as a prefactor that distance cannot
see. This module measures that rate for a committed memory circuit, under the
same canonical noise recipe the circuit tier already pins (circuit_tools
P_REF), so one circuit artifact serves both claims.

The measurement: sample the circuit's detector error model with stim's seeded
sampler, decode each shot with a decoder from the registry below, and count
shots where the predicted observable flips disagree with the actual ones. The
reference decoder is BP+OSD exactly as decode/distance.py pins it (minimum-sum
BP, scaling 0.625, osd_cs at order 10, 30 iterations), with the DEM's own
per-mechanism probabilities as the channel prior; it is the decoder every
headline rate on the board is read with. The registry (issue #5804) adds a
BP+LSD variant, plain minimum-sum BP, and minimum-weight perfect matching, each
pinned to one implementation and parameter set and named on every point, so
an entry can carry one curve per decoder and the site shows them side by side
without ever comparing a rate under one decoder with a rate under another.

Matching needs a graphlike model. pymatching accepts an undecomposed DEM
without complaint and silently drops every mechanism that touches more than
two detectors (on the d=5 seed it kept 572 of 1687), then returns confident
numbers for a different, easier channel, so the mwpm entry runs on stim's
decomposed model (decompose_errors=True) and is admitted only when stim can
decompose every mechanism; a circuit it cannot decompose has no mwpm rate.
Note the systematic offset between the two models: BP+OSD decodes hyperedges
that decomposed matching splits, and measures about 1.5x better on the d=5
seed, which is one reason the curves are labeled and kept apart.

Reproducibility has one honest boundary. The stim sampler is deterministic for
a given seed and stim version, and the decoder is deterministic on one
platform, but BP is float arithmetic, so bit-identical failure counts across
architectures are not guaranteed (the circuit tier's .dem comparison hit
exactly this with FMA contraction). Claims are therefore verified
STATISTICALLY: an independent re-sample must agree with the claimed rate to
within sampling error, which is also the only fair test between honest
parties. See ler_verify.py.

Needs ldpc (the `research` extra); import errors surface at call time so the
rest of verify/ stays importable without it.
"""

import math

import numpy as np

try:
    import stim
except ImportError:          # surfaced by callers that actually need it
    stim = None

DECODER_ID = "bposd-cs-10"   # the reference decoder: the board's headline
                             # rate and the frontier star read this one, and
                             # every other id in DECODERS is an additional,
                             # labeled curve (issue #5804)
# The decoder registry: the ids a circuit.ler point may name (the schema's
# enum mirrors this dict), each pinned to one implementation and parameter
# set, the implementation versions being the dependency pins in uv.lock.
# Rates measured with different decoders are never compared with each other.
# Adding or changing an entry is a verify/ change with its own review.
# "model" says which detector error model the decoder runs on: the
# undecomposed one the circuit tier commits (hook mechanisms fire more than
# two detectors and survive), or stim's decomposed one, which a matching
# decoder needs and which only exists when every mechanism splits into
# components of at most two detectors.
DECODERS = {
    "bposd-cs-10": {
        "implementation": "ldpc 2.4.1 BpOsdDecoder",
        "parameters": ("minimum-sum BP, scaling 0.625, 30 iterations, OSD-CS order 10, "
                       "channel prior the DEM's own mechanism probabilities"),
        "model": "undecomposed",
    },
    "bplsd-cs-10": {
        "implementation": "ldpc 2.4.1 BpLsdDecoder",
        "parameters": ("minimum-sum BP, scaling 0.625, 30 iterations, LSD-CS order 10 "
                       "(localized statistics decoding), channel prior the DEM's probabilities"),
        "model": "undecomposed",
    },
    "bp-ms-30": {
        "implementation": "ldpc 2.4.1 BpDecoder",
        "parameters": ("minimum-sum BP alone, scaling 0.625, 30 iterations, channel prior the "
                       "DEM's probabilities; a shot whose output disagrees with the observables "
                       "fails, converged or not"),
        "model": "undecomposed",
    },
    "mwpm": {
        "implementation": "pymatching 2.4.0 Matching",
        "parameters": ("minimum-weight perfect matching on stim's decomposed detector error "
                       "model (decompose_errors=True), edge weights from the decomposed "
                       "probabilities; admitted only when every mechanism decomposes"),
        "model": "decomposed",
    },
}
MIN_SHOTS = 10_000           # absolute floor on sample size
MIN_FAILURES = 100           # the real floor: the tier exists to compare
                             # prefactors between schedules with equal d_circ,
                             # and those differ by 1.2-2x. 100 failures puts
                             # ~10% sigma on the claim, so a factor-1.5
                             # difference is resolvable; a shot floor alone
                             # certifies an order of magnitude, not a
                             # comparison. Good circuits pay more shots for
                             # the same floor, which is the honest price of
                             # claiming a smaller rate.
Z95 = 1.959963984540054      # two-sided 95% normal quantile, for ci95


def dem_probs(dem):
    """Per-mechanism probabilities of a DEM, in file (column) order."""
    return [inst.args_copy()[0] for inst in dem.flattened()
            if inst.type == "error"]


def _osd_order(H, want):
    """OSD order clamped to the redundancy k = n - rank(H); see issue #1616."""
    A = np.asarray(H, dtype=np.uint8).copy() % 2
    rank, rows = 0, A.shape[0]
    for col in range(A.shape[1]):
        piv = next((r for r in range(rank, rows) if A[r, col]), None)
        if piv is None:
            continue
        A[[rank, piv]] = A[[piv, rank]]
        hit = np.nonzero(A[:, col])[0]
        A[hit[hit != rank]] ^= A[rank]
        rank += 1
    return max(0, min(want, A.shape[1] - rank))



def make_decoder(H, probs, decoder=DECODER_ID):
    """Build a registry decoder over H_dem with the given channel prior.

    Returns an object with ``decode(syndrome) -> fault vector`` for the
    decoders that run on the undecomposed model; the reference decoder
    mirrors decode/distance.py's pin exactly, only the prior differs, because
    here the DEM supplies true per-mechanism probabilities where the
    code-capacity search had to guess a uniform rate. ``mwpm`` is not built
    here: matching runs on the decomposed model, see Predictor.
    """
    spec = DECODERS.get(decoder)
    if spec is None:
        raise ValueError(f"unknown decoder {decoder!r}; the registry has "
                         f"{', '.join(DECODERS)}")
    if spec["model"] != "undecomposed":
        raise ValueError(f"{decoder} runs on the decomposed model; build it "
                         f"with Predictor(dem, decoder, circuit)")
    from scipy.sparse import csr_matrix
    Hm = np.asarray(H, dtype=np.uint8)
    common = dict(error_channel=list(map(float, probs)), max_iter=30,
                  bp_method="minimum_sum", ms_scaling_factor=0.625)
    if decoder == "bposd-cs-10":
        from ldpc import BpOsdDecoder
        # ldpc 2.4.1 does not validate osd_order against the redundancy
        # k = n - rank(H): osd_setup writes osd_candidate[i] = 1 for i < osd_order
        # into an array of size k, so an order above k corrupts the heap. Clamping
        # is a no-op wherever k >= 10 and leaves failure counts unchanged (#1616).
        return BpOsdDecoder(csr_matrix(Hm), osd_method="osd_cs",
                            osd_order=_osd_order(Hm, 10), **common)
    if decoder == "bplsd-cs-10":
        from ldpc import BpLsdDecoder
        return BpLsdDecoder(csr_matrix(Hm), lsd_method="lsd_cs",
                            lsd_order=_osd_order(Hm, 10), **common)
    if decoder == "bp-ms-30":
        from ldpc import BpDecoder
        return BpDecoder(csr_matrix(Hm), **common)
    raise ValueError(f"{decoder} is in the registry but has no builder")


def decomposed_dem(circuit):
    """Return stim's decomposed model of a circuit, the one matching runs on.

    Raises when a mechanism has no decomposition into at most two detectors.
    """
    return circuit.detector_error_model(decompose_errors=True,
                                        flatten_loops=True)


def decoder_admits(decoder, circuit=None):
    """Say whether ``decoder`` may run on ``circuit``, as (admitted, reason).

    Every undecomposed-model decoder is admitted on every circuit. A
    decomposed-model decoder needs the circuit and stim's decomposition of
    every mechanism; a circuit stim cannot decompose carries no such rate.
    """
    spec = DECODERS.get(decoder)
    if spec is None:
        return False, f"unknown decoder {decoder!r}"
    if spec["model"] == "undecomposed":
        return True, ""
    if circuit is None:
        return False, f"{decoder} needs the committed circuit to derive the decomposed model"
    try:
        import pymatching  # noqa: F401
    except ImportError:
        return False, "pymatching is not installed (the `research` extra)"
    try:
        decomposed_dem(circuit)
    except Exception as e:  # stim raises ValueError on an undecomposable mechanism
        return False, (f"{decoder} is not admitted on this circuit: stim cannot "
                       f"decompose every mechanism into at most two detectors "
                       f"({str(e).splitlines()[0][:120]})")
    return True, ""


class Predictor:
    """What the measurement needs from a decoder: predicted observable flips.

    Built once per process (decoder construction is the fixed cost the
    benchmark separates out). ``predict(dets)`` takes shots x detectors and
    returns shots x observables, both uint8. For the undecomposed-model
    decoders the prediction is (L @ e_hat) mod 2 of the returned fault vector,
    exactly the arithmetic the reference decoder always used; for ``mwpm`` it
    is pymatching's own observable prediction on the decomposed model of the
    same circuit, whose detectors and observables are the same objects in the
    same order, so the sampled syndromes carry over unchanged.
    """

    def __init__(self, dem, decoder=DECODER_ID, circuit=None):
        spec = DECODERS.get(decoder)
        if spec is None:
            raise ValueError(f"unknown decoder {decoder!r}; the registry has "
                             f"{', '.join(DECODERS)}")
        self.decoder = decoder
        self.observables = dem.num_observables
        if spec["model"] == "decomposed":
            ok, why = decoder_admits(decoder, circuit)
            if not ok:
                raise ValueError(why)
            import pymatching
            self._matching = pymatching.Matching.from_detector_error_model(
                decomposed_dem(circuit))
            self._dec, self._L = None, None
        else:
            from circuit_tools import dem_matrices
            H, L = dem_matrices(dem)
            self._matching = None
            self._dec, self._L = make_decoder(H, dem_probs(dem), decoder), L

    def predict(self, dets):
        dets = np.asarray(dets, dtype=np.uint8)
        if dets.ndim == 1:
            dets = dets.reshape(1, -1)
        if self._matching is not None:
            if dets.shape[0] == 0:
                return np.zeros((0, self.observables), dtype=np.uint8)
            return np.asarray(self._matching.decode_batch(dets),
                              dtype=np.uint8).reshape(dets.shape[0], -1)
        out = np.empty((dets.shape[0], self._L.shape[0]), dtype=np.uint8)
        for i in range(dets.shape[0]):
            e_hat = self._dec.decode(dets[i])
            out[i] = (self._L @ e_hat) % 2
        return out


def _failures(pred, obs):
    """Count the shots whose predicted observable flips differ from the sampled ones."""
    return int(np.count_nonzero(np.any(pred != obs, axis=1)))


_WORKER = {}


def _worker_init(dem_text, decoder, circuit_text):
    """Build one predictor per worker process and keep it for every chunk."""
    import stim as _stim
    dem = _stim.DetectorErrorModel(dem_text)
    circuit = _stim.Circuit(circuit_text) if circuit_text is not None else None
    _WORKER["pred"] = Predictor(dem, decoder, circuit)


def _decode_chunk(args):
    """Count failures in one chunk of shots.

    Order-independent, so chunking cannot change the total.
    """
    dets, obs = args
    return _failures(_WORKER["pred"].predict(dets), np.asarray(obs, dtype=np.uint8))


def measure_failures(dem, shots, seed, max_seconds=None, workers=None,
                     decoder=DECODER_ID, circuit=None):
    """Count the sampled logical failures of a DEM under a registry decoder.

    A shot fails when the decoder's predicted observable flips disagree with
    the sampled ones on any observable. Returns (failures, shots_done);
    shots/seed fully determine the sample for a given stim version, and
    shots_done == shots whenever `max_seconds` does not truncate. The sample
    is drawn from ``dem`` (the committed, undecomposed model) whichever
    decoder runs, so two decoders on one circuit see the same shots; a
    decomposed-model decoder additionally needs ``circuit``, the circuit the
    DEM was derived from, to build its own model.

    Shots are independent, so decoding distributes across processes. Sampling
    stays in the parent under the given seed and only the decode loop is
    split, which keeps an untruncated run bit-identical to the serial one:
    each shot's verdict depends on its own syndrome alone, and the total is a
    sum, so neither chunk size nor completion order can move it.

    Under `max_seconds` the result is timing-dependent, in the parallel path
    because the set of finished chunks depends on wall clock, and in the
    serial path because the loop stops at whichever shot the deadline lands
    on. That was already true before this was parallel, and it is why a claim
    is only admitted when its budget is not truncating.

    `workers` defaults to one per available core, capped by the chunk count.
    Pass 1 to force the serial path, which the tests use as the reference.
    """
    import os
    import time

    dets, obs, _ = dem.compile_sampler(seed=seed).sample(shots=shots)
    dets = dets.astype(np.uint8)
    obs = obs.astype(np.uint8)
    deadline = (time.monotonic() + max_seconds) if max_seconds else None
    circuit_text = str(circuit) if circuit is not None else None

    def serial():
        pred = Predictor(dem, decoder, circuit)
        failures = 0
        step = 1000
        for i in range(0, shots, step):
            failures += _failures(pred.predict(dets[i:i + step]), obs[i:i + step])
            if deadline and time.monotonic() > deadline:
                return failures, min(i + step, shots)
        return failures, shots

    if workers is None:
        workers = max(1, (os.cpu_count() or 1))
    # Chunks are sized so every worker gets several, which keeps a slow chunk
    # from deciding the wall time, and so a truncated run stops on a chunk
    # boundary rather than mid-flight.
    target_chunks = max(1, workers * 4)
    chunk = max(1, -(-shots // target_chunks))
    if workers == 1 or shots <= chunk:
        return serial()

    import multiprocessing as mp
    pieces = [(dets[i:i + chunk], obs[i:i + chunk])
              for i in range(0, shots, chunk)]
    # Threads are useless here: the decoder holds the GIL through decode
    # (measured at 1.03x on four threads), so parallelism has to be processes.
    # Prefer fork, which needs no __main__ guard in the caller; a library that
    # crashes when imported from an unguarded script is worse than a slow one,
    # so any failure to build the pool falls back to the serial loop rather
    # than propagating.
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        ctx = mp.get_context("spawn")
    try:
        with ctx.Pool(processes=min(workers, len(pieces)),
                      initializer=_worker_init,
                      initargs=(str(dem), decoder, circuit_text)) as pool:
            failures, done = 0, 0
            for got, piece in zip(pool.imap(_decode_chunk, pieces), pieces):
                failures += got
                done += piece[0].shape[0]
                if deadline and time.monotonic() > deadline:
                    pool.terminate()
                    break
            return failures, done
    except (OSError, RuntimeError, ValueError, ImportError):
        return serial()


def point_key(p, decoder=DECODER_ID):
    """Return the key a point's replication record is filed under.

    In a verifier report and a receipt alike: the rate alone for the reference
    decoder (the form every receipt on disk already uses) and rate@decoder
    for the others.
    """
    return str(p) if decoder == DECODER_ID else f"{p}@{decoder}"


def wilson_ci(failures, shots, z=Z95):
    """Wilson score interval for a binomial rate; the ci95 the schema stores."""
    if shots <= 0:
        return (0.0, 1.0)
    p = failures / shots
    denom = 1.0 + z * z / shots
    center = (p + z * z / (2 * shots)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / shots
                                   + z * z / (4 * shots * shots))
    return (max(0.0, center - half), min(1.0, center + half))


def per_round(p_shot, rounds):
    """Per-round logical error rate from a per-shot rate.

    Uses the standard parity-aware conversion: a logical flip toggles, so an
    even number of per-round flips cancels, and
    p_shot = (1 - (1 - 2 p_round)^rounds) / 2. Inverting gives the value
    reported on the board. Clamped at the p_shot = 1/2 saturation point.
    """
    if rounds <= 0:
        raise ValueError("rounds must be positive")
    p = min(float(p_shot), 0.5)
    return 0.5 * (1.0 - (1.0 - 2.0 * p) ** (1.0 / rounds))


def ler_block(dem, rounds, shots, seed, p_ref, decoder=DECODER_ID, circuit=None):
    """Measure a schema-shaped per-basis `ler` entry from scratch.

    The submitter-side generator and the test fixture builder: runs the
    measurement under ``decoder`` and packages exactly the fields
    ler_verify.py re-checks.
    """
    failures, _ = measure_failures(dem, shots, seed, decoder=decoder, circuit=circuit)
    p_shot = failures / shots
    lo, hi = wilson_ci(failures, shots)
    return {
        "p": p_ref,
        "shots": shots,
        "failures": failures,
        "seed": seed,
        "decoder": decoder,
        "ler_per_round": round(per_round(p_shot, rounds), 9),
        "ci95": [round(per_round(lo, rounds), 9),
                 round(per_round(hi, rounds), 9)],
    }

"""Measured logical error rate for the circuit tier.

The circuit tier certifies d_circ, a floor. Two schedules with the same d_circ
can differ substantially in measured logical error rate, because the number of
minimum-weight fault paths enters the rate as a prefactor that distance cannot
see. This module measures that rate for a committed memory circuit, under the
same canonical noise recipe the circuit tier already pins (circuit_tools
P_REF), so one circuit artifact serves both claims.

The measurement: sample the circuit's detector error model with stim's seeded
sampler, decode each shot with the pinned decoder, and count shots where the
predicted observable flips disagree with the actual ones. The pinned decoder
is BP+OSD exactly as decode/distance.py pins it (minimum-sum BP, scaling
0.625, osd_cs at order 10, 30 iterations), with the DEM's own per-mechanism
probabilities as the channel prior. MWPM is deliberately NOT the pin, for a
sharper reason than decomposability in the abstract: pymatching accepts an
undecomposed DEM without complaint and silently drops every mechanism that
touches more than two detectors (on the d=5 seed it kept 572 of 1687), then
returns confident numbers for a different, easier channel. Do not "check" a
board ler value with pymatching; on these codes it is not decoding the same
problem. Note also the systematic offset this pin implies: BP+OSD decodes
hyperedges that decomposed MWPM splits, and measures ~1.5x better on the d=5
seed, so board values read ~1.5x below the MWPM numbers familiar from the
literature.

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

DECODER_ID = "bposd-cs-10"   # the one pinned decoder; an enum in the schema
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


def make_decoder(H, probs):
    """The pinned BP+OSD decoder over H_dem with the DEM's own channel prior.

    Mirrors decode/distance.py's pin exactly; only the prior differs, because
    here the DEM supplies true per-mechanism probabilities where the
    code-capacity search had to guess a uniform rate.
    """
    from ldpc import BpOsdDecoder
    from scipy.sparse import csr_matrix
    return BpOsdDecoder(csr_matrix(np.asarray(H, dtype=np.uint8)),
                        error_channel=list(map(float, probs)),
                        max_iter=30, bp_method="minimum_sum",
                        ms_scaling_factor=0.625, osd_method="osd_cs",
                        osd_order=10)


def measure_failures(dem, shots, seed, max_seconds=None):
    """Sampled logical failures of a DEM under the pinned decoder.

    A shot fails when the decoder's predicted observable flips (L @ e_hat over
    GF(2)) disagree with the sampled ones on any observable. Returns
    (failures, shots_done); shots/seed fully determine the sample for a given
    stim version, and shots_done == shots whenever `max_seconds` does not
    truncate (the deadline is checked every 1000 shots, so a caller with a
    wall budget gets a partial but honest sample instead of an overrun).
    """
    import time
    from circuit_tools import dem_matrices
    H, L = dem_matrices(dem)
    dec = make_decoder(H, dem_probs(dem))
    dets, obs, _ = dem.compile_sampler(seed=seed).sample(shots=shots)
    dets = dets.astype(np.uint8)
    deadline = (time.monotonic() + max_seconds) if max_seconds else None
    failures = 0
    for i in range(shots):
        e_hat = dec.decode(dets[i])
        if np.any((L @ e_hat) % 2 != obs[i]):
            failures += 1
        if deadline and i % 1000 == 999 and time.monotonic() > deadline:
            return failures, i + 1
    return failures, shots


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


def ler_block(dem, rounds, shots, seed, p_ref):
    """A schema-shaped per-basis `ler` entry, measured from scratch.

    The submitter-side generator and the test fixture builder: runs the pinned
    measurement and packages exactly the fields ler_verify.py re-checks.
    """
    failures, _ = measure_failures(dem, shots, seed)
    p_shot = failures / shots
    lo, hi = wilson_ci(failures, shots)
    return {
        "p": p_ref,
        "shots": shots,
        "failures": failures,
        "seed": seed,
        "decoder": DECODER_ID,
        "ler_per_round": round(per_round(p_shot, rounds), 9),
        "ci95": [round(per_round(lo, rounds), 9),
                 round(per_round(hi, rounds), 9)],
    }

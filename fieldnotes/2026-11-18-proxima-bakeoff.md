---
title: "Campaign 3 of the circuit-filling plan: a proximity ranking of two-block schedules does not separate the generator's candidates at the resolution our tools reach (issue #6242)"
date: 2026-11-18
author: "@vprusso"
topics: [circuits, scheduling, proximity, bivariate-bicycle, negative-results, audit]
---

Issue #6242 lays out a circuit-filling plan whose third campaign is a gating
experiment: rank the generator's syndrome-extraction schedules the way Proxima
(arXiv:2611.19715) does, by the proximity of faults to an undetectable logical
fault set, run that against the generator's own RIS screen on ten bivariate
bicycle entries that already carry a circuit tier, and invest in a full port
only if the proximity pick beats the RIS pick on at least seven of them. This
note records the experiment as run on 2026-11-18, the three scorers tried, and
why the gate could not be read. The per-entry record is
research/audits/proxima_bakeoff-2026-11-18.json; the tools are
research/kit/proximity.py and research/kit/proxima_bakeoff.py, with
research/test_proximity.py covering the exact search on a hand-built model.

## Setup

For each entry the pool is the interleaved two-block schedule family the
generator itself draws from (research/circuit_autogen.py,
two_block_candidates at the committed round count, flagged as the generator
files them), eight schedules for the first three entries and four for the
rest; five entries were ranked in full, a sixth was stopped after one
candidate, and four were not run (the table says which and why). Each schedule is scored twice: by the generator's two-round RIS screen
(the first schedule whose screen finds nothing below d is what
research/circuit_backfill.py would file), and by a proximity profile at the
committed round count. The proximity profile follows the paper's definitions:
the proximity of a fault u is the smallest number of further faults that
complete u to a fault set no detector sees and that flips a logical, so
d_circ = 1 + min over u of prox(u); the completion is searched inside a
neighborhood Q of the detector error model's fault graph, which keeps
prox_Q(u) >= prox(u); and schedules are ranked by the smallest value over a
seed set, then its mean, higher first. The seed set is anchored on the
readout witness, the final-readout flips along the code's own logical of the
opposite type (research/circuit_autogen.readout_witness), a weight-d
undetected logical fault set every schedule of one code shares, so every
candidate is scored on the same seeds.

## Three scorers

1. Exact subset enumeration in a 16-fault neighborhood around each readout
   seed, in order of weight. On 60-8-6 and 72-12-6 every candidate scored
   (5, 5.0): the only completion a 16-fault neighborhood holds is the
   witness's own, so the cap d - 1 is attained by every seed and nothing is
   separated. Growing the neighborhood is not an option for this search: the
   number of subsets of weight at most d - 1 in a 48-fault neighborhood is in
   the billions for d = 12.

2. Exact search as a 0-1 integer program (HiGHS through scipy.optimize.milp;
   one row per detector with an integer slack carrying the parity, A f - 2y = s,
   one row per observable with a binary flip indicator, at least one flipped).
   On 60-8-6, neighborhoods of 250 and 400 faults built from the witness and
   whole breadth-first layers of detector-adjacent faults, hook-like seeds
   (the faults firing the most detectors, nine each): the solver hit a 20 s
   limit on all six seeds tried at both sizes and returned nothing. The toy
   model in research/test_proximity.py solves in milliseconds; the
   circuit-sized problem does not.

3. Completions from the pinned decoder. The decoder of verify/ler_tools.py
   (BP+OSD, osd_cs order 10) is built on the model with the sum of the
   observables appended as one perfect check and a flat prior, and asked to
   decode the syndrome of the seed with that row flipped; the correction f it
   returns satisfies H f = H u and flips an odd number of logicals, so u + f is
   an undetected logical fault set and |f| bounds prox(u) from above. Sixteen
   hook-like seeds per basis for the first three entries, eight for the rest,
   one decode each (about 1.4 s per decode under load). The table is the
   result: on every candidate of every entry ranked, every seed came back at
   the cap.

| entry | rounds | pool | hook seeds per basis | distinct profile keys (p_min, p_mean, tie-break) | RIS pick | proximity pick | seconds |
|---|---|---|---|---|---|---|---|
| 60-8-6 | 6 | 8 | 16 | (5, 5.0, -16) | 0 | 0 | 428.2 |
| 72-12-6 | 6 | 8 | 16 | (5, 5.0, -16) | 0 | 0 | 660.4 |
| 56-8-8 | 8 | 8 | 16 | (7, 7.0, -16) | 0 | 0 | 1491.1 |
| 60-6-10 | 10 | 4 | 8 | (9, 9.0, -8) | 0 | 0 | 812.9 |
| 72-10-10 | 10 | 4 | 8 | (9, 9.0, -8) | 0 | 0 | 1356.3 |
| 80-8-12 | 12 | 4 | 8 | (11, 11.0, -8), first candidate only | stopped | stopped | 1269.9 for one candidate |

The remaining four entries (90-12-12, 108-8-14, 144-12-12, 144-8-16-b) were
not run: at 21 minutes per candidate for 80-8-12, the 144-qubit models would
have cost hours each for a profile the smaller entries had already shown to
be flat.

The RIS pick and the proximity pick coincide on every entry ranked, because the
proximity ranking is flat and the tie-break (fewest seeds at the minimum,
which is also flat) falls back to pool order, the same order the RIS screen
takes its first acceptable schedule from. The plan's gate asks whether the
proximity pick beats the RIS pick on at least seven of ten; with identical
picks it cannot be met, and no LER was measured where the picks coincide. A
first attempt that did measure LER priced it: the committed schedule of
60-8-6 alone took about 15 minutes per (basis, rate) point at 10,000 and
20,000 shots with 18 decoder workers, roughly two hours per entry for two
arms.

## What the flat profile does and does not say

It does not say the schedules are equally good. Proxima reports logical
error rates that differ by factors of two to five among valid schedules of
one code at equal or nearly equal d_circ, and the two-round RIS screens in the
record (the per-basis bounds in the table's source) already differ from
candidate to candidate. It says that whatever separates these schedules is
not visible as a completion of weight below d - 1 inside the neighborhoods
and under the completions our tools can certify: the exact searches are
either too small to contain a shortcut or too large to finish, and the
decoder's completions never fall below the cap. Two causes are plausible and
not separated here. The seeds may be wrong: the readout witness lives in the
final round, and a hook fault that stands in for two data faults of a
minimum-weight logical shows a shorter completion only when that logical runs
through the qubits the hook reaches in the round the hook occurs; mid-round
anchors, which need the round-r detector layout rather than the closure
detectors, were not built. Or the decoder is the wrong oracle: BP+OSD with a
flat prior returns a low-weight correction, not the minimum-weight one, and
on these models it may be returning the witness-sized completion every time.

The models are rich in propagated faults, so seeds are not the shortage: the
Z memory of 60-8-6 has 13,470 mechanisms, of which 3,510 fire six detectors,
1,560 seven, 1,350 eight, and 1,110 nine, against 2,010 that fire three (a
single data error) and 60 that fire one.

## What a real run needs

An exact coset search at the scale of a memory circuit's detector error
model: the lightest f with H f = s and L f odd for a given syndrome s. That is
the kernel machinery verify/gf2_fast.cpp already has for the homogeneous
problem (dem_rand_witness: information sets over H, random restarts, a
projection cap), with a particular solution added, so it is a bounded
extension of the accelerator rather than a new tool; Proxima's own code was
not released with the paper's first version. With it, the profile over
mid-round hook seeds becomes the paper's quantity at the paper's scale, and
the bake-off above can be rerun as written. Until then the proximity ranking
is not an input the circuit-filling campaigns can use, and campaign 4 stays
on the RIS-screened families.

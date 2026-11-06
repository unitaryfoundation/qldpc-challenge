# cc-stabilizer-parents-2026-11-05: symplectic single-step moves on the board's stabilizer entries with n <= 40 (issue #4478, direction 1)

## What was asked

Whether code-calculus v0.1's three productive moves (C-DELETE-CHECK, E-PUNCTURE,
E-PEEL) reach stabilizer-board frontier points when applied once to the
board's own stabilizer entries, which the library cannot load (none is CSS up
to a local Clifford). Definition:
`research/campaigns/cc-stabilizer-parents-2026-11-05/campaign.json`. Budget:
20,000 candidates screened at 1,000 Pauli-weight RIS trials, 2 wall-clock
hours.

## What was spent

900 candidates screened of the 20,000 declared, 0.22 wall-clock hours of the 2 declared; the run took 13 minutes; no stopping condition fired: the budget was not reached and the run ended with the parent list.

## What ran

`research/campaigns/cc-stabilizer-parents-2026-11-05/manifest.json` carries the
snapshot. `run.py` beside it is the whole procedure: one screen depth (1,000
trials, seed 7), no ladder, the trusted gate at seed 11 on every nondominated
child with screened d >= 3, at most 400 gate calls.

## What was tried

One experiment per (parent, move), 54 parents, 73 experiments; the
summary's rows carry the screen depth and the verdict. Verdicts: not_run 55, passed 10, duplicate 8.

## What came of it

248 children with screened d >= 3 were put through the gate; the cap of 400 was not reached. 240 passed and 8 were refused as exact duplicates of board entries. Of the 240, 176 are board-advancing on the stabilizer board and 64 are dominated. The 176 advancing children are 8 distinct (n, k, d, w) points from 8 parents (puncturing a cyclic parent at each of its qubits gives one point many times over, since the probe deduplicates exact displays and not permutations), 172 of them punctures and 4 peels, and the largest screened distance is 4. 574 further children were nondominated at the screen but read d <= 2 and were not gated.

The best 8 points by kd^2/n:

| child (upper bound at 1,000 trials) | w | copies | move | parent | kd^2/n |
|---|---:|---:|---|---|---:|
| [[26,7,4]] | 8 | 26 | E-PUNCTURE | 27-3-7 | 4.31 |
| [[27,7,4]] | 8 | 27 | E-PUNCTURE | 28-4-6 | 4.15 |
| [[11,5,3]] | 8 | 4 | E-PUNCTURE | 12-4-4 | 4.09 |
| [[15,4,3]] | 5 | 4 | E-PEEL | 16-4-4-s | 2.40 |
| [[19,5,3]] | 6 | 19 | E-PUNCTURE | 20-3-5 | 2.37 |
| [[32,6,3]] | 7 | 32 | E-PUNCTURE | 33-2-8 | 1.69 |
| [[26,4,3]] | 5 | 26 | E-PUNCTURE | 27-2-6 | 1.38 |
| [[38,4,3]] | 5 | 38 | E-PUNCTURE | 39-2-7 | 0.95 |

## Negative results

- stabilizer parents are outside code-calculus v0.1's state model: 0 of the board's 226 stabilizer entries are CSS up to a local Clifford (the verifier refuses such submissions as CSS codes in disguise), so the library's CodeState cannot load any of them; the moves here are symplectic analogs written for this probe
- C-DELETE-CHECK on stabilizer parents with n <= 40: no board-advancing child at d >= 3: 1259 moves enumerated, 70 children nondominated at the screen but at d <= 2 (not gated, by design), 0 children with d >= 3 passed the gate, none of them nondominated on the stabilizer board

## What a reader should take from it

The moves transfer to symplectic form; the stabilizer board is sparse enough
that punctures of small parents land nondominated at most n it has not seen;
the CSS board holds better codes at every one of those (n, k), and the boards
rank apart by rule. Nothing was filed. The durable finding is that direction 1
of issue #4478 needs a symplectic CodeState before the library's planner,
ledger, or exporter can touch a stabilizer parent. The reading is
`fieldnotes/2026-11-05-code-calculus-v0p1-directions-1-and-6.md`.

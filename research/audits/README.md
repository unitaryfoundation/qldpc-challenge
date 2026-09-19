# audits: re-measuring the leaders before trying to beat them

The boards rank witness-backed distance **upper bounds**. A frontier is
therefore a set of claims, and the board's own history says some of them are
inflated: `[[882,18,30]]` was revised to 29 (PR #1165), `[[684,12,81]]` to 66
(issue #896), and `[[396,10,39]]` to 37 (issue #899). Spending a campaign
against a bar that is one or two units soft is wasted budget, so the first step
of a campaign is to re-measure the bar on fresh seeds.

`leader_audit.py` is the harness for that:

```
# is this leader's number real? escalating ladder, fresh seeds each rung
uv run --frozen python research/audits/leader_audit.py ladder \
    codes/360-12-24.json \
    --ladder 1000000:101,102,103,104 5000000:201,202,203 20000000:301,302,303

# triage a whole cell's leaders at one budget
uv run --frozen python research/audits/leader_audit.py screen \
    --trials 2000000 --seeds 51 codes/672-20-32.json codes/922-18-31.json
```

It exits 2 if any claim is refuted, so it can gate a script.

## What it does

* Loads a board entry straight from `codes/`, so the object measured is the one
  the verifier ranks (including any reduction or layout the entry carries).
* Recomputes `k` and CSS commutation from the raw check matrix rather than
  trusting the entry's own fields.
* Runs random-information-set search on both Pauli sides jointly, using the
  bit-packed `verify/gf2_fast` accelerator when built (`make fast`) and the
  pure-NumPy `research/kit/surrogate.py` path otherwise.
* Re-validates every witness in pure Python against the raw sparse matrices:
  support size equals the weight, `H_opp v = 0` over GF(2), and `v` outside the
  row space of `H_own`. A bug in the accelerator cannot put an unbacked number
  in the log.

## Reading the output

| verdict | meaning |
|---|---|
| `refuted` | a logical lighter than the claim was exhibited. The claim is over-stated and `d <= ` the reading. A distance revision is a valid submission on its own. |
| `holds` | the search reached exactly the claimed weight and found nothing lighter. Evidence, not proof. |
| `inconclusive` | the search did not even reach the claim (or found nothing above it in one direction). Says nothing about the code. |

**`inconclusive` is the trap.** For dense low-rate entries RIS can sit several
units *above* the claim at a budget that fully refutes a structured one -- e.g.
`[[684,20,72]]` reads 84 at 2M trials against a claim of 72, while its
sibling `[[684,12,66]]` was refuted 81 -> 66 by the same tool at 8M.
A reading above the claim is never corroboration: only a reading *at* or
*below* it carries information. Match the budget to the rate, as issue #899
argues.

## Limits

These are upper-bound searches. `holds` never upgrades a claim to the exact
(`d=`) tier -- that needs `verify/certify.py`, whose measured envelope is
`d <= 13, k <= 12`. The syndrome-decoder cross-check in `decode/distance.py` is
a genuinely different mechanism but is dominated by RIS at these budgets
(issue #1148); it is corroboration when it agrees, and not evidence when it is
weaker.

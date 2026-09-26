---
title: "Escalation-gate A/B on a BB pool: half the trials, same verdicts; the judgment model kills, the arithmetic carries"
date: 2026-09-23
author: "@mathysrennela"
model: "glm-5.3-flash"
topics: [escalation-gate, jev, budgeting, ab-campaign, bivariate-bicycle]
status: active
related:
  - 2026-07-01-confirmation-is-the-bottleneck.md
  - 2026-09-20-screening-traps-at-n-900.md
---

## TL;DR

First A/B of the rung-escalation gate (`research/kit/escalation.py`,
`research/AUTORESEARCH.md` §3b) against the fixed-ladder baseline, on a
six-candidate BB pool under an identical 522,000-trial-per-candidate cap:

1. **Same conclusions, 49.6% fewer trials** (1,580,000 vs 3,132,000). All
   three above-bar candidates survived with identical best bounds (10, 8, 4);
   all three below-bar ladders were stopped at 4,000–6,000 trials instead of
   522,000 each.
2. **The baseline spent almost everything on settled facts**: all six of its
   ladders were flat from rung 1 (`settled_at_rung=0` on every candidate), so
   99.6% of baseline trials ran after the final bound was already witnessed.
   The savings came exclusively from early kills; live-ladder spend was
   identical by design.
3. **The judgment model (jev-1.13) killed confidently and certified never.**
   2/2 abandon verdicts (confidence 0.89–0.90) were correct; 12/12 promote
   verdicts stayed below the 0.60 trust bar (max 0.59) and fenced to holds
   that the harness's settle rule carried. One Jev hold sat on a *provably*
   dead ladder; the harness's proven-below-bar fence overrode it. On this
   evidence the model is a conservative kill-switch, not a certification
   engine — the safe failure mode for this repo's false-positive-averse
   discipline.
4. Three process incidents (stale-evidence judging, a brief-schema gap, a
   dropped journal writer) were all caught, and the decision journal was
   fully reconstructed from on-disk briefs + verdicts. The lesson: **every
   judgment input being a file is what made the loss recoverable.**

## 1. Protocol

Both arms screen the same pool (`sample_bb`, 200 draws, `l,m in [3,7]`,
weight 3, seed 11, `n in [30,130]`; 800-trial screen) and take the same six
survivors, spread across the ranking (top 2, median pair, bottom 2). The
campaign bar is the survivors' median efficiency, 2.5 — a synthetic,
campaign-internal target shared by both arms, **not** a board bar. Ladder
depths (2,000 / 20,000 / 100,000 / 400,000 trials) and the per-candidate cap
(522,000) are identical in both arms.

*Baseline arm*: the fixed ladder of `2026-09-20` — chase every survivor
through the full schedule, stop only at the cap.

*Gate arm*: one rung at a time. At each rung boundary `rung_brief` computes
the facts deterministically (best bound, flat fresh-seed rungs, efficiency vs
the bar, budget) and formats the `jev_decide` request; the harness's judgment
step calls the model with that exact payload; `apply_verdict` enforces the
policy in code; `append_journal` records brief, verdict, and decision.

The fences, in order of authority: hold is the default; abandon requires the
best bound below the bar AND >= 2 flat fresh-seed rungs AND no frontier flag;
promote requires remaining budget to cover the next rung; confidence < 0.60,
or a missing/malformed/escaped verdict, holds. Two harness rules were added
during the campaign, both journaled as harness authority rather than model
verdict: the *settle rule* (3 identical fresh readings => the bound is
stable, advance depth) and the *proven-abandon rule* (best bound already
below the d needed for the bar, and an upper bound can only fall => the bar
is unreachable by arithmetic; abandon even over a Jev hold).

Driver: `research/campaigns/ab_escalation_gate.py`
(`init|base|gate-next|gate-apply|report`).

## 2. Results

| candidate | screen | best bound (both arms) | eff | vs bar 2.5 | base trials | gate trials | gate disposition |
|---|---:|---:|---:|---|---:|---:|---|
| [[84,4]] | 10 | <=10 | 4.7619 | above (+2.26) | 522,000 | 522,000 | exhausted (carried) |
| [[60,4]] | 8 | <=8 | 4.2667 | above (+1.77) | 522,000 | 522,000 | exhausted (carried) |
| [[48,8]] | 4 | <=4 | 2.6667 | above (+0.17) | 522,000 | 522,000 | exhausted (carried) |
| [[42,6]] | 4 | <=4 | 2.2857 | below (−0.21) | 522,000 | **6,000** | abandoned (harness-proven) |
| [[72,24]] | 2 | <=2 | 1.3333 | below (−1.17) | 522,000 | **4,000** | abandoned (Jev 0.90) |
| [[36,8]] | 2 | <=2 | 0.8889 | below (−1.61) | 522,000 | **4,000** | abandoned (Jev 0.89) |

Totals: 3,132,000 vs 1,580,000 trials (−49.6%), identical survivor set and
identical best bounds. No screen inflation occurred anywhere on this pool:
the 800-trial screen reading equaled the final bound on all six candidates.

## 3. What the judgment layer did

16 model verdicts across the campaign:

| verdict | count | confidence | outcome |
|---|---|---|---|
| abandon-ladder | 2 | 0.89–0.90 | both honored, both at the fence minimum (2 flat fresh rungs) |
| promote-next-rung | 12 | 0.40–0.59 | none crossed the 0.60 trust bar; all fenced to hold, all carried by the settle rule at flat >= 3 |
| hold-deepen | 2 | 0.64–0.70 | honored; the 0.70 hold ([42,6] at flat 3) claimed deeper trials might rescue it, contradicting the upper-bound direction — the proven-below-bar fence abandoned the ladder instead |
| (no verdict sought) | 3 | — | budget exhausted; hold by default, no model call spent on a predetermined outcome |

Two calibration observations. Confidence tracked arithmetic clarity: the two
provably-dead ladders drew the highest confidences of the campaign, while
settled-but-live ladders never drew a confident promote. And the failure
asymmetry ran the right way: the one under-kill ([42,6] held at flat 2, where
the fence already permitted abandon) cost 2,000 extra trials, while
over-killing is structurally fenced. A conservative kill-switch is exactly
the profile this repo wants from a judgment layer; the arithmetic
(`efficiency`, upper-bound direction, flat-rung counts) did all the carrying.

## 4. Process incidents

1. **Stale-evidence judging.** Two verdicts were first issued from a
   reconstructed summary instead of the brief file; caught on cross-check,
   both re-judged from the files. Both re-judgments returned the same action
   (one confidence moved 0.65 -> 0.64), so the outcome was unchanged — but
   the rule now stands: the judgment step reads the brief file, never a
   summary. Had the stale evidence differed, the journal would have recorded
   a verdict the real brief never supported.
2. **Brief-schema gap.** The first `rung_brief` facts omitted `n` and `k`,
   so the first six briefs could not be judged on their own terms. Fixed and
   pinned in `research/test_escalation.py`; the six stale-format briefs were
   excluded from the journal reconstruction. Recovery cost one extra
   2,000-trial rung per ladder; the readings were reused, not wasted.
3. **Dropped journal writer.** A mid-campaign patch to the driver's decision
   chain silently removed the `append_journal` call (the adjacent comment
   still claimed journaling). Caught by the end-of-run audit; all 19 journal
   rows were reconstructed from on-disk briefs + verdicts and flagged
   `reconstructed`. Nothing was lost because everything was a file — the
   brief/verdict/journal discipline is the backup.

## What this does not claim

- The bar (2.5) is a campaign-internal target chosen to split the survivor
  set. Nothing here advances or tests a board cell.
- Six candidates, one pool, one seed, NumPy backend: −49.6% is one draw, not
  a distribution. No replication yet.
- **The gate's hardest case is untested.** This pool showed zero screen
  inflation, so the `2026-09-20` failure mode — a screen reading that
  collapses under depth — never occurred. What was tested is the easy case:
  ladders flat and dead from rung 1. Killing a ladder that *looks* above the
  bar and isn't remains to be measured.
- The kill-switch characterization rests on 16 verdicts in one campaign.
- No code here is a find: no candidate was packaged or validated. The gate
  changes where trial budget goes, never what can be claimed.

## Reproduction

- Gate: `research/kit/escalation.py` (`rung_brief`, `apply_verdict`,
  `append_journal`; the fences live in `apply_verdict`). Tests:
  `research/test_escalation.py`.
- Driver: `research/campaigns/ab_escalation_gate.py`. `init` screens the pool
  and freezes survivors + bar; `base` runs the fixed-ladder arm; `gate-next`
  runs one rung per pending candidate and writes briefs; `gate-apply` reads
  one verdict JSON per brief (`{selected, confidence, escaped}`), enforces it
  through the fences, and journals; `report` prints the comparison.
- The judgment step is external by design: the kit stays offline and
  deterministic, and `gate-apply` consumes whatever verdicts the harness's
  judgment model produced from the briefs' `jev_request` payloads.
- Per-run state, briefs, verdicts, and the decision journal are local staging
  output (gitignored by design, not evidence); the tables above are the
  record, and the driver regenerates the mechanics.

---
title: "Trial-depth floors: the distance-inflation failure mode that repeats every campaign"
date: 2026-07-01
topics: [calibration, distance-estimation, discipline]
---

Every inflated distance claim across the first months of campaigns died the
same way: a high surrogate d at low trials that collapsed as trials rose.
[[392,6,32]]→26; [[294,8,20]]→19 *after passing an 8k-trial gate*;
[[400,8,50]]→44; [[336,12,36]]→24; overall **5 of 7 staged n≥300 candidates
were refuted at 2M trials/side**. Support-5 2BGA (weight-9plus) inflates
8–30% even at 30–60k-trial depth.

The discipline that fixed it:

- Screen at low trials, but confirm on a **rising ladder** (e.g.
  2k→8k→60k→1M trials) and keep only candidates whose d is *flat* across the
  ladder — a value still descending is not a value.
- For n≥300, treat **~1M+ trials/side as the packaging floor**. With the
  `gf2_fast` extension (`make fast`, ~30–170× over pure Python) that is
  minutes, so there is no excuse to skip it.
- Package claimed d = **the lightest logical you yourself witnessed** in deep
  self-refutation, never "the best value I failed to refute" — leave the gate
  nothing left to find.
- Distance floors/records established in low-trial eras are suspect (one
  d≥14 "floor" fell at 200k trials). Re-refute an old claim before building
  on it.

See also: the 2026-07-14 large-n calibration fieldnote — at n≈1000 even
"flat across 4k→16k" is not convergence, and the CI refuter's depth cannot
catch inflation there.

*Ported 2026-07-23 from `research/AUTORESEARCH.md`, "Field notes from past
campaigns (2026-06 → 2026-07)", where this experience was originally
accumulated.*

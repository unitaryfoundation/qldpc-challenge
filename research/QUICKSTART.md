# autoresearch quickstart

The minimal loop and the rules you may not break. Everything else is in
[`AUTORESEARCH.md`](AUTORESEARCH.md), the detailed manual; load the section you
need when you need it rather than all of it up front.

## Two rules

**No code is a "find" until `verify/validate_candidate.py` returns
`passed: true` for it.** The surrogate ranks candidates cheaply; it never
claims one. Never write your own distance check and never edit anything under
`verify/` — CI pins its hashes. If you think the gate is wrong, stop and tell
the human.

**A found low-weight logical is the most expensive data we produce — never
lose it.** Persist every candidate through `submit.make_submission` and
`submit.save_submission`, which embed the witness. An ad-hoc `python -c` that
prints a distance and exits throws away the part that cost the compute.

Unattended runs stage candidates in `research/candidates/` and stop there: no
writes to `codes/`, no commits, no PRs. A human decides what lands.

## The loop

```
  pick a direction ─▶ build (HX,HZ) ─▶ estimate distance ─▶ package ─▶ VALIDATE ─▶ stage
```

```bash
./qldpc recent --family <your family>    # what already landed, and what failed
./qldpc targets                          # which track cells are open
```

```python
import sys; sys.path[:0] = ["research/kit", "verify"]
from bb import build_bb
from surrogate import distance_rand
from submit import make_submission, save_submission

HX, HZ = build_bb(6, 6, [(3, 0), (0, 1), (0, 2)], [(0, 3), (1, 0), (2, 0)])
d = distance_rand(HX, HZ, trials=600)        # an upper bound, never a proof
doc = make_submission(HX, HZ, name=f"[[72,12,{d}]] my BB code",
                      construction="Bivariate bicycle on Z_6 x Z_6.",
                      authors=["your-handle"], family="bivariate-bicycle",
                      confidence="upper_bound")
save_submission(doc, "research/candidates/72-12-6.json")
```

```bash
uv run python verify/validate_candidate.py research/candidates/72-12-6.json
```

Exit 0 and `passed: true`, or it is not a find. The gate is the expensive step,
so screen widely and spend it only on survivors.

Sweep a whole family with `search.py` instead of one code at a time. Repeat
until the budget is spent, then report the survivors with their honest labels:
`upper_bound`, "advances this board cell", novelty unverified.

## Where the detail lives

| You need | Read |
|---|---|
| constructors, group algebras, coset codes | `AUTORESEARCH.md` §1 |
| the surrogate and its failure modes | §2 |
| sweeping a family, the escalation gate | §3 |
| packaging, layouts, the 2d-local tracks | §4 |
| exact confirmation for a standout | §6 |
| what the gate catches and why | Pitfalls |
| what a finished candidate looks like | Definition of done |
| every module in `research/kit` | Module reference |

Submitting on a contributor's behalf is a different workflow with different
permissions: see [`../CONTRIBUTING.md`](../CONTRIBUTING.md) and
[`../AGENTS.md`](../AGENTS.md).

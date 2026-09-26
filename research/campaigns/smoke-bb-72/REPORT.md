# smoke-bb-72 — the campaign object drives the real loop, and finds nothing

## What was asked

Maximize `kd^2/n` over bivariate bicycle codes with n in [60, 80], check weight
at most 6 and distance at least 4, stopping at a score of 6, one survivor, or
four screened candidates. The definition is
`research/campaigns/smoke-bb-72/campaign.json`.

This campaign exists to be run in a test. It is not a search: it builds one
known code and puts it through the loop, so that "a campaign definition drives
the existing loop" is something CI checks rather than something a document
claims.

## What was spent

One of four screened candidates. Stopped by `target_reached`: the objective hit
6 against a target of 6.

## What was tried

One experiment, family `bivariate-bicycle`, seed 0: the known Z_6 x Z_6
trinomial pair, screened at 200 RIS trials on the NumPy backend.

## Survivors

None. The code screened at `[[72,12,6]]` and was packaged, and the gate refused
it as an exact duplicate of the board entry `codes/72-12-6.json`. That is the
correct answer and the reason this example is worth shipping: the run had a
candidate in hand, and the campaign recorded a negative result rather than a
find, because the gate said so.

## Negative results

`[[72,12,6]]` is already on the board. Nothing in this direction is open at
n = 72 with weight 6.

## Follow-up

None. A real campaign on this family would widen n and drop the known
parameters from the sweep; see `research/campaigns/w8-2dlocal-n700-1000/` for
the shape of one.

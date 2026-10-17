# Reproduce the CSS [[117,13,6]] finite certificate

`check.py` is an independent checker using only the Python 3 standard library. It does not import the repository's verifier, the original construction script, NumPy arrays, or a saved proof. It reads the candidate without modifying it. From the repository root, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 repro/117-13-6/check.py \
  --output /tmp/css117-proof.json
```

The default input is `codes/117-13-6.json`, resolved relative to the checker's installed location, independently of the current working directory. An explicit positional input path is also accepted. A failed check exits with an exception and does not write a success receipt.

## Construction and binding

Over `R=F2[x]/(x^9-1)`, take

```
A = [[1, 1,  1],
     [1, x, x^3]]
B = [[1, 1,  1],
     [1, x, x^4]].
```

The polynomial matrices are `HX=[A tensor I3 | I2 tensor B^T]` and `HZ=[I3 tensor B | A^T tensor I2]`. In HX, a monomial `x^s` expands to the 9-by-9 permutation `P_s[t,u]=[u=t+s mod9]`; HZ uses `P_-s` for the reciprocal transpose. This produces two 54-by-117 binary matrices, each of rank 52. The recorded presentation removes zero-based X rows 44,53 and Z rows 35,53, leaving two independent 52-row bases of the same spaces.

The checker reconstructs these matrices directly with integer bit operations. It binds each supplied check space by exact original, supplied, and stacked ranks 52, then verifies commutation. The expected actual resources are `n117/k13`, maximum check weight 5, maximum total degree 6, 104 checks and 520 incidences. It verifies both the supplied Tanner graph and the decomposition induced by canonical reduced rowspaces are a single 117-qubit component. Row ordering may differ: group binding does not rely on document hashes or entrywise equality.

## Exhaustive distance certificate

For each pure CSS side, use the actual opposite checks to compute column syndromes. The empty, singleton and two-element supports give exactly `1+117+C(117,2)=6904` distinct syndromes. Any nonzero kernel support of weight at most four would split into two different supports of size at most two and violate this injectivity.

The checker then enumerates all `C(117,3)=260130` triples and matches their syndromes against that complete table. Every weight-five kernel vector has a 3+2 split and is therefore found. Each side gives 540 matches: exactly 54 distinct weight-five supports, each found ten times. They equal the reconstructed original check supports. Every one is independently reduced to an explicit combination of the supplied checks, and those coefficients are saved in the receipt. Thus no weight-at-most-five pure logical exists.

The candidate's X and Z weight-six witnesses have zero opposite syndrome and increase their own check rank from 52 to 53, so they are nontrivial logicals. A nontrivial mixed CSS logical has at least one nontrivial pure component, whose support is contained in its support. The two pure lower bounds therefore also exclude mixed logicals of weight below six. Together these checks prove **this instance has dX=dZ=d=6**.

## Evidence scope

`receipt.json` is the actual successful run against the original received candidate, SHA256 `c7409cbfbd15bf5d3287ed660a6e0bd4ecb0620f6f868a6e29f5975dcc3703fc`. It includes the complete boundary coefficients and both supplied logical supports. `validation.json` records a portable-layout replay and negative controls. `manifest.json` pins the checker, documentation, receipts and the prior independent audit used as provenance. The prior audit is not a runtime dependency.

The candidate's distance fields remain `upper_bound`; this standalone local finite proof does not change the official schema tier or replace the trusted validation gate. Official gate and promotion receipts belong to the repository's normal workflow. The claim applies to the displayed finite instance, not arbitrary lift sizes, a new code family, a world record, or a circuit-level performance result.

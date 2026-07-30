# Why weight penalization is fairer than raw $K = kd^2/n$

**Claim.** For ranking qLDPC codes on the board, the graph-normalized figure of
merit

$$K_G = \frac{k\,d^2}{n \cdot T_{\text{graph}}}, \qquad T_{\text{graph}} = 2\,w_{\max}$$

is a fairer headline than the raw $K = kd^2/n$. It keeps $K$'s information
content but removes the structural bias that rewards codes for buying distance
with heavy stabilizers.

## The problem with raw `K`

Raw `K` only sees $[n,k,d]$. It is blind to *how* a code achieves its distance.
A code that reaches distance $d$ with heavy checks looks strictly better than
one that reaches the same $d$ with light checks — even though the heavy code
needs deeper syndrome extraction, more idling decoherence, and worse hook-error
propagation. On our board this is not hypothetical (analysis restricted to the
promoted codes, `w_max <= 16`):

- `[[254,44,24]]` (weight-16) sits at raw-`K` rank **5** (K = 99.8).
- `[[390,82,30]]` (weight-16) tops raw `K` at **189.2**, rank **1**.

Raw `K` therefore ranks the heaviest promoted code near the top, which is
exactly the failure mode the evaluation notes warn against. (The weight-32
`[[390,82,40]]` is excluded here because it has not been promoted to the board
yet; it would only sharpen the point.)

## Why `K_G` fixes it

`T_graph` is the architecture-independent scheduling depth: by König's theorem
the chromatic index of a bipartite Tanner graph equals its max degree, so the
minimum number of concurrent gate rounds is exactly $2\,w_{\max}$ (X then Z).
Dividing by it is a *structural* correction, not a hand-tuned penalty — it
falls out of the graph, not from an opinion about weights.

On the board this demotes the heavy code precisely where it should (analysis
set: `w_max <= 16`, so the heaviest promoted code is `[[254,44,24]]`, w=16):

| metric | `[[254,44,24]]` (w=16) rank | mean w_max in top-20 |
|--------|------------------------------|----------------------|
| `K`    | 5                            | 10.8                 |
| `K_G`  | 10                           | 10.8                 |

`K_G` still ranks the 390-family highly (it genuinely has strong parameters),
and `[[390,82,30]]` (w=16) leads both raw `K` and `K_G` — the correct verdict,
since it delivers the strongest parameters among the promoted codes without
resorting to the not-yet-promoted weight-32 construction.

### Top 20 by raw `K` (w_max <= 16)

| # | code | w | K |
|---|------|---|-----|
| 1 | `[[390,82,30]]` weight-16 generalized bicycle code | 16 | 189.231 |
| 2 | `[[390,82,27]]` cyclic GB divisor code on Z_195 | 16 | 153.277 |
| 3 | `[[390,68,28]]` cyclic GB divisor code on Z_195 (weight-13) | 13 | 136.697 |
| 4 | `[[254,58,21]]` cyclic GB divisor code on Z_127 (weight-16) | 16 | 100.701 |
| 5 | `[[254,44,24]]` | 16 | 99.780 |
| 6 | `[[372,130,16]]` pair-partition CPM CSS | 12 | 89.462 |
| 7 | `[[254,44,21]]` | 12 | 76.394 |
| 8 | `[[276,98,14]]` pair-partition CPM CSS | 12 | 69.594 |
| 9 | `[[258,32,22]]` weight-10 cyclic GB, N=129 | 10 | 60.031 |
| 10 | `[[530,216,12]]` pair-partition CPM CSS | 10 | 58.687 |
| 11 | `[[590,240,12]]` pair-partition CPM CSS | 10 | 58.576 |
| 12 | `[[472,122,14]]` pair-partition CPM CSS | 8 | 50.661 |
| 13 | `[[488,126,14]]` pair-partition CPM CSS | 8 | 50.607 |
| 14 | `[[568,146,14]]` pair-partition CPM CSS | 8 | 50.380 |
| 15 | `[[210,24,20]]` weight-10 cyclic GB, N=105 | 10 | 45.714 |
| 16 | `[[126,18,14]]` weight-10 cyclic GB, N=63 | 10 | 28.000 |
| 17 | `[[240,16,20]]` coset 2BGA (ATB Table VI) | 8 | 26.667 |
| 18 | `[[336,20,21]]` coset 2BGA (weight-8) | 8 | 26.250 |
| 19 | `[[336,26,18]]` | 8 | 25.071 |
| 20 | `[[210,26,14]]` GB divisor-trick code on Z_105 | 8 | 24.267 |

### Top 20 by `K_G` (w_max <= 16)

| # | code | w | K_G |
|---|------|---|-------|
| 1 | `[[390,82,30]]` weight-16 generalized bicycle code | 16 | 5.913 |
| 2 | `[[390,68,28]]` cyclic GB divisor code on Z_195 (weight-13) | 13 | 5.258 |
| 3 | `[[390,82,27]]` cyclic GB divisor code on Z_195 | 16 | 4.790 |
| 4 | `[[372,130,16]]` pair-partition CPM CSS | 12 | 3.728 |
| 5 | `[[254,44,21]]` | 12 | 3.183 |
| 6 | `[[472,122,14]]` pair-partition CPM CSS | 8 | 3.166 |
| 7 | `[[488,126,14]]` pair-partition CPM CSS | 8 | 3.163 |
| 8 | `[[568,146,14]]` pair-partition CPM CSS | 8 | 3.149 |
| 9 | `[[254,58,21]]` cyclic GB divisor code on Z_127 (weight-16) | 16 | 3.147 |
| 10 | `[[254,44,24]]` | 16 | 3.118 |
| 11 | `[[258,32,22]]` weight-10 cyclic GB, N=129 | 10 | 3.002 |
| 12 | `[[530,216,12]]` pair-partition CPM CSS | 10 | 2.934 |
| 13 | `[[590,240,12]]` pair-partition CPM CSS | 10 | 2.929 |
| 14 | `[[276,98,14]]` pair-partition CPM CSS | 12 | 2.900 |
| 15 | `[[210,24,20]]` weight-10 cyclic GB, N=105 | 10 | 2.286 |
| 16 | `[[240,16,20]]` coset 2BGA (ATB Table VI) | 8 | 1.667 |
| 17 | `[[336,20,21]]` coset 2BGA (weight-8) | 8 | 1.641 |
| 18 | `[[360,12,24]]` twisted-torus BB code | 6 | 1.600 |
| 19 | `[[336,26,18]]` | 8 | 1.567 |
| 20 | `[[210,26,14]]` GB divisor-trick code on Z_105 | 8 | 1.517 |

The two tables share 19 of 20 entries, but the *ordering* changes: the
weight-16 `[[254,44,24]]` drops from raw-`K` rank 5 to `K_G` rank 10, while the
lighter `[[390,68,28]]` (w=13) and the weight-8 pair-partition codes rise. That
is exactly the demotion of heavy-check codes the metric is designed to produce.

## Honest limitations (so the argument holds up)

- `K_G` is governed by the **worst-case** max weight; a single heavy boundary
  check drags it down even if the rest of the code is light.
- It is **blind to hook-error geometry**: two codes with identical
  $T_{\text{graph}}$ can have very different effective distance depending on
  how faults propagate. It corrects the *weight* bias, not the *circuit* bias.
- It is a **filter/ranking aid, not a verdict.** The verifier gate and
  circuit-level simulation remain the source of truth.

**Recommendation.** Keep `K` as the displayed headline (it's the literature
standard and the sortable column), but use `K_G` as the tiebreaker and the
primary lens when arguing that a high-`K` code "cheated" with heavy checks.
When the not-yet-promoted weight-32 codes are eventually considered, `K_G`'s
demotion of them becomes even more pronounced — which is the whole point.

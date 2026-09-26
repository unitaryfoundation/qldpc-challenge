---
title: Permutation inequivalence of two 674-qubit bicycle constructions
date: 2026-09-24
author: "@vprusso"
topics: [generalized-bicycle, code-equivalence, cyclic-ideals]
---

The two explicit [[674,170]] CSS constructions below are inequivalent to one another and to both compared [[674,170]] board matrix pairs under arbitrary physical qubit permutations, including permutations composed with a uniform global Hadamard. The board comparisons are [674-170-64](../codes/674-170-64.json) and [674-170-76](../codes/674-170-76.json); both compared JSON snapshots actually contain distance upper bounds of 64. The result concerns their matrices, independently of any distance estimate or stale filename. It establishes neither inequivalence under arbitrary local Clifford transformations nor novelty against the literature.

## The two matrix pairs

Work in F_2[x]/(x^337+1). For a support A, define a(x)=sum_{i in A}x^i and C(a)[r,c]=a_{(c-r) mod 337}. Both codes have

```
HX = [C(a) | C(b)]
HZ = [C(b)^T | C(a)^T].
```

Construction 036-f2 has b(x)=a(x^4), with

```
A = [30, 33, 40, 113, 125, 141, 163, 193, 220, 221, 240, 241, 247, 249, 254, 335].
```

Construction 067-f2 also has b(x)=a(x^4), with

```
A = [24, 27, 81, 100, 131, 145, 149, 164, 177, 182, 183, 192, 204, 269, 277, 306].
```

Exponents are reduced modulo 337. In each case the left and right projections of row(HX) are the same cyclic ideal, and both projections are injective. Direct GF(2) rank checks give

| Matrix pair | rank(HX) | rank(HX left) | rank(HX right) | Corresponding three HZ ranks |
| --- | ---: | ---: | ---: | --- |
| 036-f2 | 252 | 252 | 252 | 252, 252, 252 |
| 067-f2 | 252 | 252 | 252 | 252, 252, 252 |
| Board 674-170-64 | 252 | 252 | 252 | 252, 252, 252 |
| Board 674-170-76 | 252 | 252 | 252 | 252, 252, 252 |

Equality of the full rank with each projected rank proves injectivity. Both full row sets are invariant under the simultaneous shift of the two blocks of 337 coordinates. The integer 337 is prime.

## Why the multiplier test is sufficient here

**Lemma.** Let p be an odd prime and C a linear code on two p-coordinate blocks. Suppose the simultaneous shift s=(T,T), with T a p-cycle, preserves C, both block projections of C are injective, and dim(C)>1. Then P=⟨s⟩ is a Sylow p-subgroup of the coordinate-permutation group Aut(C).

**Proof.** The p-part of (2p)! is p². If P were not Sylow, it would lie in an order-p² subgroup Q of Aut(C). Every group of order p² is abelian, so Q centralizes s. The centralizer of s in S_(2p) is (C_p×C_p) semidirect S_2. The image of Q in S_2 is trivial because p is odd; hence Q=C_p×C_p and includes the one-block shift (T,1). For any (u,v) in C, subtraction gives (Tu,v)−(u,v)=(Tu−u,0) in C. Injectivity of the second projection forces Tu=u. Thus all possible first blocks are constant vectors; injectivity of the first projection then gives dim(C)≤1, a contradiction.

Now suppose a coordinate permutation f maps two codes satisfying the lemma to each other. Their simultaneous-shift subgroups are Sylow, so Sylow conjugacy supplies an automorphism h of the target with hf normalizing P. Therefore an equivalence exists in the normalizer whenever any permutation equivalence exists. This does not assert that P is normal or that every equivalence normalizes it.

A permutation normalizing P permutes its two orbits and conjugates s to s^u for a single u in F_p^*. Its action is exactly

```
(block,t) -> (pi(block), u*t+c_block),
```

where pi may swap the blocks and the offsets are independent. Thus only a common exponent multiplier, independent cyclic shifts, and a block swap need be considered. The underlying Sylow-conjugacy reduction also appears in Guenda and Gulliver, *On the equivalence of cyclic and quasi-cyclic codes over finite fields* (2017), [Lemma 4.2 and Proposition 4.3(i), pp. 267–268](https://dergipark.org.tr/tr/download/article-file/323327).

## An invariant of the row spaces

For each code let g=gcd(a,b,x^337+1). The individual gcds of a and b with x^337+1 agree with g, so both projection ideals are ⟨g⟩. Cyclic shifts leave these ideals unchanged. A common exponent multiplier u sends their generator to gcd(g(x^u),x^337+1); a block swap has no further effect because the two ideals agree.

Encode a polynomial by the nonnegative integer whose bit i is its x^i coefficient. Enumerating all 336 nonzero multipliers yields the following minima and orbit sizes:

| Matrix pair | g | Canonical projection-ideal generator | Distinct images |
| --- | ---: | ---: | ---: |
| 036-f2 | 39055717386231510123236041 | 39055717386231510123236041 | 16 |
| 067-f2 | 65083167261774274452856359 | 40596226193011322631504845 | 16 |
| Board 674-170-64 | 76678917870283549950206349 | 39019755261139131293320123 | 16 |
| Board 674-170-76 | 71899348617285251479121621 | 39019755261139131293320123 | 16 |

Each construction's 16-element set is disjoint from the other construction's set and from the common orbit of the two board controls. Thus all five stated comparisons exclude a normalizing equivalence and therefore exclude every coordinate-permutation equivalence. Equality of the two board controls' ideal orbits is not a proof that those controls are equivalent. The invariant is the projection ideal of the entire row space; a mismatch between sparse generating supports alone would not prove an inequivalence claim.

For CSS codes a qubit permutation preserves Pauli type, so it must map the pure-X stabilizer space row(HX) to the target pure-X space. Their inequivalence therefore excludes equivalence of the complete CSS stabilizers.

Finally, swapping the two blocks and reversing both cyclic coordinates maps the entire HX row set onto HZ in each of these bicycle codes. Consequently an equivalence composed with global H would also give a permutation equivalence between the X row spaces, already excluded. Equivalently, reversal replaces the projection generator by its reciprocal, and the multiplier u=-1 is included in the enumeration.

All rank assertions were checked with unchanged `verify/gf2.py`; an independent polynomial-GCD computation with SymPy reproduced the complete multiplier orbits, their disjointness, and the X/Z reversal relation. No distance routine was used. This finite comparison does not decide equivalence under arbitrary local Clifford transformations or establish literature-wide novelty.

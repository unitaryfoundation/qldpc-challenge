---
title: Stabilizer parity separates a 674-qubit bicycle code from the Frobenius subclass
date: 2026-09-24
author: "@vprusso"
topics: [generalized-bicycle, code-equivalence, stabilizer-parity]
---

The explicit binary [[674,168]] CSS matrix pair below is not equivalent to any ordinary 674-qubit univariate bicycle (UB) code under a tensor product of arbitrary single-qubit Clifford gates followed by a qubit permutation. It has an odd-weight stabilizer, whereas every stabilizer of a Frobenius UB code has even weight. This distinction uses a known stabilizer-weight parity invariant, not a new equivalence method.

Here UB means GB(f,f^(2^ell)) over F_2[x]/(x^337+1), as defined by [Rabeti and Mahdavifar, Section III, arXiv:2605.14173v1](https://arxiv.org/abs/2605.14173v1). The result does not distinguish this example from every previously studied generalized-bicycle code, establish literature-wide novelty, or show better distance, decoding, or hardware performance.

## Exact matrix pair

Work over F_2[x]/(x^337+1), and define a and b by the supports

```text
A = [0, 1, 11, 34, 46, 48, 77, 80, 135, 201, 206, 226, 255, 266, 315, 333]
B = [0, 4, 15, 88, 118, 145, 150, 205, 210, 232, 251, 266, 303, 312, 323]
```

Set C(a)[r,c]=a[(c-r) mod 337], HX=[C(a)|C(b)], and HZ=[C(b)^T|C(a)^T]. Circulant commutation gives CSS orthogonality. Both matrices have rank 253, so k=674−253−253=168. Each supplied check has weight 16+15=31. In particular the first pure-X check, supported on A in the first block and 337+B in the second, is an explicit odd-weight stabilizer generator. It is not a logical operator or a distance witness.

As additional constructor data, the full/left/right projection ranks are 253/252/253 for HX and 253/253/252 for HZ. Integer bit i encodes the coefficient of x^i:

```text
g = gcd(b,x^337+1) = gcd(a,b,x^337+1) = 32650130462612855861996279
gcd(a,x^337+1) = (x+1)g = 54412013000919294326554393.
```

These rank and gcd facts are not needed for the parity obstruction. They do not imply X/Z distance asymmetry. The GB block-swap/reversal involution exchanges the entire X and Z stabilizer spaces and logical sectors while preserving weight.

## The parity obstruction

In a binary UB code with odd block length, the map i -> 2^ell*i modulo the block length permutes coordinates. Thus f and f^(2^ell) have equal weight; every row of each CSS check matrix has even weight. Every x in row(HX) and z in row(HZ) consequently has even Hamming weight. CSS orthogonality also gives x·z=0, so the intersection of their supports has even size.

Every stabilizer is, up to phase, X^x Z^z for such x and z. Its Pauli support is the union of the two supports, including their intersection where the operator is Y. Therefore

```text
weight(X^x Z^z) = weight(x) + weight(z) − |support(x) ∩ support(z)|
```

is even. This proves the all-even property for the entire stabilizer group, independently of which generating set is displayed. The general even/odd stabilizer-weight dichotomy appears in Wei et al., *Theory of low-weight quantum codes*, [Appendix G.2, equation (68)](https://arxiv.org/html/2601.19848v1#A7.SS2).

Conjugating by a single-qubit Clifford maps I to I and a nonidentity Pauli to a nonidentity Pauli. A tensor product of these gates preserves the support weight of every Pauli, and a qubit permutation preserves it as well. Phases do not affect support. An equivalence would map the explicit weight-31 stabilizer above to an odd-weight stabilizer of the UB code, contradicting its all-even property. This excludes every such local-Clifford-plus-permutation equivalence, including global H as a special case. No Sylow or projection-rank hypothesis is needed.

The example belongs to the established generalized-bicycle family; see [Panteleev and Kalachev, arXiv:1904.02703v3](https://arxiv.org/abs/1904.02703v3). The obstruction applies to the stated Frobenius UB subclass. It does not exclude equivalence through entangling Clifford circuits, assert a new family, certify distance, or establish novelty against the full literature.

# qLDPC Code Metrics Report

Generated from 125 board codes in `codes/` with `w_max_row <= 16` (codes above this weight are not yet promoted to the board and are excluded). All metrics computed by `research/metrics.py` directly from the parity-check matrices (no circuit simulation). See the notes for the motivation behind each metric.

## Per-metric top 20

> **Note on girth.** The notes' "girth 6" is the *per-side* Tanner graph (each side decoded independently by BP-OSD). The combined X+Z graph is *always* girth 4 for CSS codes because X- and Z-checks share qubits — this is a structural fact, not a defect. We rank on per-side girth.

### Raw figure of merit kd^2/n  (`K`)

Baseline; ignores weight/structure.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 189.231 |
| 2 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 153.277 |
| 3 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 136.697 |
| 4 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 100.701 |
| 5 | [[254,44,24]] | 254 | 44 | 24 | 16 | 99.780 |
| 6 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 89.462 |
| 7 | [[254,44,21]] | 254 | 44 | 21 | 12 | 76.394 |
| 8 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 69.594 |
| 9 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 60.031 |
| 10 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 58.687 |
| 11 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 58.576 |
| 12 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 50.661 |
| 13 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 50.607 |
| 14 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 50.380 |
| 15 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 45.714 |
| 16 | [[126,18,14]] weight-10 cyclic GB, N=63 | 126 | 18 | 14 | 10 | 28.000 |
| 17 | [[240,16,20]] coset 2BGA (ATB Table VI) | 240 | 16 | 20 | 8 | 26.667 |
| 18 | [[336,20,21]] coset 2BGA on MC336(m=56,r=29)/H<3> (weight-8) | 336 | 20 | 21 | 8 | 26.250 |
| 19 | [[336,26,18]] | 336 | 26 | 18 | 8 | 25.071 |
| 20 | [[210,26,14]] GB divisor-trick code on Z_105 | 210 | 26 | 14 | 8 | 24.267 |

### Graph-normalized kd^2/(n*T_graph)  (`K_G`)

Divides by scheduling depth (König).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 5.913 |
| 2 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 5.258 |
| 3 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 4.790 |
| 4 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 3.728 |
| 5 | [[254,44,21]] | 254 | 44 | 21 | 12 | 3.183 |
| 6 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 3.166 |
| 7 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 3.163 |
| 8 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 3.149 |
| 9 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 3.147 |
| 10 | [[254,44,24]] | 254 | 44 | 24 | 16 | 3.118 |
| 11 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 3.002 |
| 12 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 2.934 |
| 13 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 2.929 |
| 14 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 2.900 |
| 15 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 2.286 |
| 16 | [[240,16,20]] coset 2BGA (ATB Table VI) | 240 | 16 | 20 | 8 | 1.667 |
| 17 | [[336,20,21]] coset 2BGA on MC336(m=56,r=29)/H<3> (weight-8) | 336 | 20 | 21 | 8 | 1.641 |
| 18 | [[360,12,24]] twisted-torus BB code (arXiv:2503.03827) | 360 | 12 | 24 | 6 | 1.600 |
| 19 | [[336,26,18]] | 336 | 26 | 18 | 8 | 1.567 |
| 20 | [[210,26,14]] GB divisor-trick code on Z_105 | 210 | 26 | 14 | 8 | 1.517 |

### Weight-penalized kd^2/(n*w_max)  (`FoM_w`)

Linear penalty by max check weight.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 11.827 |
| 2 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 10.515 |
| 3 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 9.580 |
| 4 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 7.455 |
| 5 | [[254,44,21]] | 254 | 44 | 21 | 12 | 6.366 |
| 6 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 6.333 |
| 7 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 6.326 |
| 8 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 6.298 |
| 9 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 6.294 |
| 10 | [[254,44,24]] | 254 | 44 | 24 | 16 | 6.236 |
| 11 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 6.003 |
| 12 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 5.869 |
| 13 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 5.858 |
| 14 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 5.800 |
| 15 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 4.571 |
| 16 | [[240,16,20]] coset 2BGA (ATB Table VI) | 240 | 16 | 20 | 8 | 3.333 |
| 17 | [[336,20,21]] coset 2BGA on MC336(m=56,r=29)/H<3> (weight-8) | 336 | 20 | 21 | 8 | 3.281 |
| 18 | [[360,12,24]] twisted-torus BB code (arXiv:2503.03827) | 360 | 12 | 24 | 6 | 3.200 |
| 19 | [[336,26,18]] | 336 | 26 | 18 | 8 | 3.134 |
| 20 | [[210,26,14]] GB divisor-trick code on Z_105 | 210 | 26 | 14 | 8 | 3.033 |

### kd^2/(n*w_row*w_col)  (`COI`)

Double weight penalty (informal term).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 1.055 |
| 2 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 1.054 |
| 3 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 1.050 |
| 4 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 0.978 |
| 5 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 0.976 |
| 6 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 0.932 |
| 7 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 0.809 |
| 8 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 0.739 |
| 9 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 0.725 |
| 10 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 0.600 |
| 11 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 0.599 |
| 12 | [[360,12,24]] twisted-torus BB code (arXiv:2503.03827) | 360 | 12 | 24 | 6 | 0.533 |
| 13 | [[254,44,21]] | 254 | 44 | 21 | 12 | 0.530 |
| 14 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 0.457 |
| 15 | [[340,16,18]] twisted-torus BB code (arXiv:2503.03827) | 340 | 16 | 18 | 6 | 0.423 |
| 16 | [[240,16,20]] coset 2BGA (ATB Table VI) | 240 | 16 | 20 | 8 | 0.417 |
| 17 | [[336,20,21]] coset 2BGA on MC336(m=56,r=29)/H<3> (weight-8) | 336 | 20 | 21 | 8 | 0.410 |
| 18 | [[288,16,16]] 2BGA MC(12,12,r5) | 288 | 16 | 16 | 6 | 0.395 |
| 19 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 0.393 |
| 20 | [[336,26,18]] | 336 | 26 | 18 | 8 | 0.392 |

### kd^2/(n*(<w_row>+<w_col>))  (`Score_Fair`)

Uses *average* weights (anti tail-spike).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 5.913 |
| 2 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 5.258 |
| 3 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 4.790 |
| 4 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 4.473 |
| 5 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 3.668 |
| 6 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 3.661 |
| 7 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 3.619 |
| 8 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 3.615 |
| 9 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 3.599 |
| 10 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 3.480 |
| 11 | [[254,44,21]] | 254 | 44 | 21 | 12 | 3.183 |
| 12 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 3.147 |
| 13 | [[254,44,24]] | 254 | 44 | 24 | 16 | 3.118 |
| 14 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 3.002 |
| 15 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 2.286 |
| 16 | [[240,16,20]] coset 2BGA (ATB Table VI) | 240 | 16 | 20 | 8 | 1.667 |
| 17 | [[336,20,21]] coset 2BGA on MC336(m=56,r=29)/H<3> (weight-8) | 336 | 20 | 21 | 8 | 1.641 |
| 18 | [[360,12,24]] twisted-torus BB code (arXiv:2503.03827) | 360 | 12 | 24 | 6 | 1.600 |
| 19 | [[336,26,18]] | 336 | 26 | 18 | 8 | 1.567 |
| 20 | [[210,26,14]] GB divisor-trick code on Z_105 | 210 | 26 | 14 | 8 | 1.517 |

### Linear kd/n  (`K_lin`)

Stops over-rewarding deep d.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 6.308 |
| 2 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 5.677 |
| 3 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 5.591 |
| 4 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 4.971 |
| 5 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 4.891 |
| 6 | [[390,68,28]] cyclic GB divisor code on Z_195 (weight-13) | 390 | 68 | 28 | 13 | 4.882 |
| 7 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 4.881 |
| 8 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 4.795 |
| 9 | [[254,44,24]] | 254 | 44 | 24 | 16 | 4.157 |
| 10 | [[254,44,21]] | 254 | 44 | 21 | 12 | 3.638 |
| 11 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 3.619 |
| 12 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 3.615 |
| 13 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 3.599 |
| 14 | [[258,32,22]] weight-10 cyclic GB, N=129 | 258 | 32 | 22 | 10 | 2.729 |
| 15 | [[210,24,20]] weight-10 cyclic GB, N=105 | 210 | 24 | 20 | 10 | 2.286 |
| 16 | [[126,18,14]] weight-10 cyclic GB, N=63 | 126 | 18 | 14 | 10 | 2.000 |
| 17 | [[126,28,8]] generalized bicycle code | 126 | 28 | 8 | 10 | 1.778 |
| 18 | [[210,26,14]] GB divisor-trick code on Z_105 | 210 | 26 | 14 | 8 | 1.733 |
| 19 | [[168,20,14]] double-cover 2BGA code (weight-8) | 168 | 20 | 14 | 8 | 1.667 |
| 20 | [[180,20,<=14]] coset two-block code (weight-8) | 180 | 20 | 14 | 8 | 1.556 |

### (k+d)/n  (`mu`)

Information-density ratio.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 14 | 6 | 2 | 6 | 0.571 |
| 2 | [[7,1,3]] color code | 7 | 1 | 3 | 4 | 0.571 |
| 3 | [[12,4,2]] twisted-torus BB code (arXiv:2503.03827) | 12 | 4 | 2 | 6 | 0.500 |
| 4 | [[18,4,4]] twisted-torus BB code (arXiv:2503.03827) | 18 | 4 | 4 | 6 | 0.444 |
| 5 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 0.430 |
| 6 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 0.427 |
| 7 | [[24,6,4]] weight-6 generalized bicycle (2BGA) code | 24 | 6 | 4 | 6 | 0.417 |
| 8 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 0.406 |
| 9 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 0.393 |
| 10 | [[16,2,4]] toric code | 16 | 2 | 4 | 4 | 0.375 |
| 11 | [[32,8,4]] two-block group algebra CSS (arXiv:2306.16400) | 32 | 8 | 4 | 8 | 0.375 |
| 12 | [[30,4,6]] twisted-torus BB code (arXiv:2503.03827) | 30 | 4 | 6 | 6 | 0.333 |
| 13 | [[58,16,3]] | 58 | 16 | 3 | 7 | 0.328 |
| 14 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 0.311 |
| 15 | [[51,12,3]] HP ham7xsham6 | 51 | 12 | 3 | 7 | 0.294 |
| 16 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 0.288 |
| 17 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 0.287 |
| 18 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 0.287 |
| 19 | [[126,28,8]] generalized bicycle code | 126 | 28 | 8 | 10 | 0.286 |
| 20 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 0.282 |

### kd/n^2  (`I_V`)

Volumetric / relative-distance index.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 14 | 6 | 2 | 6 | 0.06122 |
| 2 | [[7,1,3]] color code | 7 | 1 | 3 | 4 | 0.06122 |
| 3 | [[12,4,2]] twisted-torus BB code (arXiv:2503.03827) | 12 | 4 | 2 | 6 | 0.05556 |
| 4 | [[18,4,4]] twisted-torus BB code (arXiv:2503.03827) | 18 | 4 | 4 | 6 | 0.04938 |
| 5 | [[24,6,4]] weight-6 generalized bicycle (2BGA) code | 24 | 6 | 4 | 6 | 0.04167 |
| 6 | [[16,2,4]] toric code | 16 | 2 | 4 | 4 | 0.03125 |
| 7 | [[32,8,4]] two-block group algebra CSS (arXiv:2306.16400) | 32 | 8 | 4 | 8 | 0.03125 |
| 8 | [[30,4,6]] twisted-torus BB code (arXiv:2503.03827) | 30 | 4 | 6 | 6 | 0.02667 |
| 9 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 0.01888 |
| 10 | [[40,6,5]] weight-6 generalized bicycle (2BGA) code | 40 | 6 | 5 | 6 | 0.01875 |
| 11 | [[54,6,9]] two-block group algebra CSS (arXiv:2306.16400) | 54 | 6 | 9 | 8 | 0.01852 |
| 12 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 0.01801 |
| 13 | [[254,44,24]] | 254 | 44 | 24 | 16 | 0.01637 |
| 14 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 0.01617 |
| 15 | [[126,18,14]] weight-10 cyclic GB, N=63 | 126 | 18 | 14 | 10 | 0.01587 |
| 16 | [[62,10,6]] twisted-torus BB code (arXiv:2503.03827) | 62 | 10 | 6 | 6 | 0.01561 |
| 17 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 0.01503 |
| 18 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 0.01456 |
| 19 | [[254,44,21]] | 254 | 44 | 21 | 12 | 0.01432 |
| 20 | [[58,16,3]] | 58 | 16 | 3 | 7 | 0.01427 |

### k/d  (`rho`)

Wide (rho>1) vs deep (rho<1) aspect ratio.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | 590 | 240 | 12 | 10 | 20.000 |
| 2 | [[530,216,12]] pair-partition CPM CSS (qc_530_216_12) | 530 | 216 | 12 | 10 | 18.000 |
| 3 | [[568,146,14]] pair-partition CPM CSS (scan qc_472_122_14 P=71) | 568 | 146 | 14 | 8 | 10.429 |
| 4 | [[488,126,14]] pair-partition CPM CSS (qc_488_126_14) | 488 | 126 | 14 | 8 | 9.000 |
| 5 | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | 472 | 122 | 14 | 8 | 8.714 |
| 6 | [[372,130,16]] pair-partition CPM CSS (qc_372_130_16) | 372 | 130 | 16 | 12 | 8.125 |
| 7 | [[276,98,14]] pair-partition CPM CSS (qc_276_98_14) | 276 | 98 | 14 | 12 | 7.000 |
| 8 | [[288,50,8]] weight-8 mixed-monomial bivariate bicycle code | 288 | 50 | 8 | 8 | 6.250 |
| 9 | [[288,48,8]] weight-10 mixed-monomial bivariate bicycle code | 288 | 48 | 8 | 10 | 6.000 |
| 10 | [[288,46,8]] weight-8 mixed-monomial bivariate bicycle code | 288 | 46 | 8 | 8 | 5.750 |
| 11 | [[58,16,3]] | 58 | 16 | 3 | 7 | 5.333 |
| 12 | [[146,18,4]] twisted-torus BB code (arXiv:2503.03827) | 146 | 18 | 4 | 6 | 4.500 |
| 13 | [[51,12,3]] HP ham7xsham6 | 51 | 12 | 3 | 7 | 4.000 |
| 14 | [[126,28,8]] generalized bicycle code | 126 | 28 | 8 | 10 | 3.500 |
| 15 | [[390,82,27]] cyclic GB divisor code on Z_195 | 390 | 82 | 27 | 16 | 3.037 |
| 16 | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 14 | 6 | 2 | 6 | 3.000 |
| 17 | [[45,9,3]] | 45 | 9 | 3 | 5 | 3.000 |
| 18 | [[254,58,21]] cyclic GB divisor code on Z_127 (weight-16) | 254 | 58 | 21 | 16 | 2.762 |
| 19 | [[390,82,30]] weight-16 generalized bicycle code | 390 | 82 | 30 | 16 | 2.733 |
| 20 | [[42,8,3]] generalized bicycle code | 42 | 8 | 3 | 6 | 2.667 |

### Singleton defect n-2d+2-k  (`Delta_Sing`)

Lower is better (closer to MDS).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[7,1,3]] color code | 7 | 1 | 3 | 4 | 2 |
| 2 | [[12,4,2]] twisted-torus BB code (arXiv:2503.03827) | 12 | 4 | 2 | 6 | 6 |
| 3 | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 14 | 6 | 2 | 6 | 6 |
| 4 | [[16,2,4]] toric code | 16 | 2 | 4 | 4 | 8 |
| 5 | [[18,4,4]] twisted-torus BB code (arXiv:2503.03827) | 18 | 4 | 4 | 6 | 8 |
| 6 | [[24,6,4]] weight-6 generalized bicycle (2BGA) code | 24 | 6 | 4 | 6 | 12 |
| 7 | [[25,1,5]] surface code | 25 | 1 | 5 | 4 | 16 |
| 8 | [[30,4,6]] twisted-torus BB code (arXiv:2503.03827) | 30 | 4 | 6 | 6 | 16 |
| 9 | [[32,8,4]] two-block group algebra CSS (arXiv:2306.16400) | 32 | 8 | 4 | 8 | 18 |
| 10 | [[36,2,6]] toric code | 36 | 2 | 6 | 4 | 24 |
| 11 | [[40,6,5]] weight-6 generalized bicycle (2BGA) code | 40 | 6 | 5 | 6 | 26 |
| 12 | [[42,8,3]] generalized bicycle code | 42 | 8 | 3 | 6 | 30 |
| 13 | [[48,4,8]] twisted-torus BB code (arXiv:2503.03827) | 48 | 4 | 8 | 6 | 30 |
| 14 | [[45,9,3]] | 45 | 9 | 3 | 5 | 32 |
| 15 | [[54,6,9]] two-block group algebra CSS (arXiv:2306.16400) | 54 | 6 | 9 | 8 | 32 |
| 16 | [[45,5,4]] generalized weight-6 open-boundary planar BB code | 45 | 5 | 4 | 6 | 34 |
| 17 | [[51,12,3]] HP ham7xsham6 | 51 | 12 | 3 | 7 | 35 |
| 18 | [[49,1,7]] surface code | 49 | 1 | 7 | 4 | 36 |
| 19 | [[50,6,4]] weight-6 planar (generalized BB, our record family) | 50 | 6 | 4 | 6 | 38 |
| 20 | [[58,16,3]] | 58 | 16 | 3 | 7 | 38 |

### w_max/d  (`sigma`)

Confinement; lower is better.

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[354,4,28]] twisted-torus BB code (arXiv:2503.03827) | 354 | 4 | 28 | 6 | 0.214 |
| 2 | [[318,4,26]] twisted-torus BB code (arXiv:2503.03827) | 318 | 4 | 26 | 6 | 0.231 |
| 3 | [[350,6,26]] twisted-torus BB code (arXiv:2503.03827) | 350 | 6 | 26 | 6 | 0.231 |
| 4 | [[276,4,24]] twisted-torus BB code (arXiv:2503.03827) | 276 | 4 | 24 | 6 | 0.250 |
| 5 | [[308,6,24]] twisted-torus BB code (arXiv:2503.03827) | 308 | 6 | 24 | 6 | 0.250 |
| 6 | [[330,8,24]] twisted-torus BB code (arXiv:2503.03827) | 330 | 8 | 24 | 6 | 0.250 |
| 7 | [[360,12,24]] twisted-torus BB code (arXiv:2503.03827) | 360 | 12 | 24 | 6 | 0.250 |
| 8 | [[246,4,22]] twisted-torus BB code (arXiv:2503.03827) | 246 | 4 | 22 | 6 | 0.273 |
| 9 | [[266,6,22]] twisted-torus BB code (arXiv:2503.03827) | 266 | 6 | 22 | 6 | 0.273 |
| 10 | [[312,8,22]] twisted-torus BB code (arXiv:2503.03827) | 312 | 8 | 22 | 6 | 0.273 |
| 11 | [[320,6,28]] 2bga-metacyclic autoresearch | 320 | 6 | 28 | 8 | 0.286 |
| 12 | [[204,4,20]] twisted-torus BB code (arXiv:2503.03827) | 204 | 4 | 20 | 6 | 0.300 |
| 13 | [[224,6,20]] twisted-torus BB code (arXiv:2503.03827) | 224 | 6 | 20 | 6 | 0.300 |
| 14 | [[270,8,20]] twisted-torus BB code (arXiv:2503.03827) | 270 | 8 | 20 | 6 | 0.300 |
| 15 | [[174,4,18]] twisted-torus BB code (arXiv:2503.03827) | 174 | 4 | 18 | 6 | 0.333 |
| 16 | [[182,6,18]] twisted-torus BB code (arXiv:2503.03827) | 182 | 6 | 18 | 6 | 0.333 |
| 17 | [[234,8,18]] twisted-torus BB code (arXiv:2503.03827) | 234 | 8 | 18 | 6 | 0.333 |
| 18 | [[248,10,18]] twisted-torus BB code (arXiv:2503.03827) | 248 | 10 | 18 | 6 | 0.333 |
| 19 | [[288,12,18]] bivariate bicycle code | 288 | 12 | 18 | 6 | 0.333 |
| 20 | [[340,16,18]] twisted-torus BB code (arXiv:2503.03827) | 340 | 16 | 18 | 6 | 0.333 |

### Check overlap max_i sum_j |S_i∩S_j|  (`chi`)

Lower is better (hook-error susceptibility).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[16,2,4]] toric code | 16 | 2 | 4 | 4 | 12 |
| 2 | [[25,1,5]] surface code | 25 | 1 | 5 | 4 | 12 |
| 3 | [[36,2,6]] toric code | 36 | 2 | 6 | 4 | 12 |
| 4 | [[49,1,7]] surface code | 49 | 1 | 7 | 4 | 12 |
| 5 | [[64,2,8]] toric code | 64 | 2 | 8 | 4 | 12 |
| 6 | [[7,1,3]] color code | 7 | 1 | 3 | 4 | 12 |
| 7 | [[81,1,9]] surface code | 81 | 1 | 9 | 4 | 12 |
| 8 | [[45,9,3]] | 45 | 9 | 3 | 5 | 18 |
| 9 | [[50,6,4]] weight-6 planar (generalized BB, our record family) | 50 | 6 | 4 | 6 | 24 |
| 10 | [[45,5,4]] generalized weight-6 open-boundary planar BB code | 45 | 5 | 4 | 6 | 28 |
| 11 | [[108,8,10]] bivariate bicycle code | 108 | 8 | 10 | 6 | 30 |
| 12 | [[112,6,7]] weight-6 planar (generalized BB, our record family) | 112 | 6 | 7 | 6 | 30 |
| 13 | [[114,4,14]] twisted-torus BB code (arXiv:2503.03827) | 114 | 4 | 14 | 6 | 30 |
| 14 | [[12,4,2]] twisted-torus BB code (arXiv:2503.03827) | 12 | 4 | 2 | 6 | 30 |
| 15 | [[120,8,12]] bivariate bicycle code (autoresearch candidate) | 120 | 8 | 12 | 6 | 30 |
| 16 | [[128,6,8]] weight-6 planar (generalized BB, our record family) | 128 | 6 | 8 | 6 | 30 |
| 17 | [[128,8,6]] planar BB (paper Table V baseline) | 128 | 8 | 6 | 6 | 30 |
| 18 | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 14 | 6 | 2 | 6 | 30 |
| 19 | [[140,6,14]] twisted-torus BB code (arXiv:2503.03827) | 140 | 6 | 14 | 6 | 30 |
| 20 | [[144,12,12]] bivariate bicycle code | 144 | 12 | 12 | 6 | 30 |

### Per-side Tanner girth  (`girth`)

Higher is better (BP convergence).

| # | code | n | k | d | w_max | value |
|---|------|---|---|---|--------|-------|
| 1 | [[16,2,4]] toric code | 16 | 2 | 4 | 4 | 8 |
| 2 | [[25,1,5]] surface code | 25 | 1 | 5 | 4 | 8 |
| 3 | [[288,16,16]] 2BGA MC(12,12,r5) | 288 | 16 | 16 | 6 | 8 |
| 4 | [[36,2,6]] toric code | 36 | 2 | 6 | 4 | 8 |
| 5 | [[49,1,7]] surface code | 49 | 1 | 7 | 4 | 8 |
| 6 | [[64,2,8]] toric code | 64 | 2 | 8 | 4 | 8 |
| 7 | [[81,1,9]] surface code | 81 | 1 | 9 | 4 | 8 |
| 8 | [[108,8,10]] bivariate bicycle code | 108 | 8 | 10 | 6 | 6 |
| 9 | [[114,4,14]] twisted-torus BB code (arXiv:2503.03827) | 114 | 4 | 14 | 6 | 6 |
| 10 | [[120,8,12]] bivariate bicycle code (autoresearch candidate) | 120 | 8 | 12 | 6 | 6 |
| 11 | [[128,8,6]] planar BB (paper Table V baseline) | 128 | 8 | 6 | 6 | 6 |
| 12 | [[140,6,14]] twisted-torus BB code (arXiv:2503.03827) | 140 | 6 | 14 | 6 | 6 |
| 13 | [[144,12,12]] bivariate bicycle code | 144 | 12 | 12 | 6 | 6 |
| 14 | [[146,18,4]] twisted-torus BB code (arXiv:2503.03827) | 146 | 18 | 4 | 6 | 6 |
| 15 | [[154,6,16]] twisted-torus BB code (arXiv:2503.03827) | 154 | 6 | 16 | 6 | 6 |
| 16 | [[162,8,14]] twisted-torus BB code (arXiv:2503.03827) | 162 | 8 | 14 | 6 | 6 |
| 17 | [[168,20,14]] double-cover 2BGA code (weight-8) | 168 | 20 | 14 | 8 | 6 |
| 18 | [[174,4,18]] twisted-torus BB code (arXiv:2503.03827) | 174 | 4 | 18 | 6 | 6 |
| 19 | [[180,18,<=14]] coset two-block code (weight-8) | 180 | 18 | 14 | 8 | 6 |
| 20 | [[182,6,18]] twisted-torus BB code (arXiv:2503.03827) | 182 | 6 | 18 | 6 | 6 |

## Raw K vs weight-penalized K: which is fairer?

The notes argue raw `K = kd^2/n` over-rewards codes that buy distance with high-weight checks. We test this on the board by comparing the top-20 set under each metric and tracking where the heaviest code in the analysis (`[[254,44,24]]`, w=16) lands. (Codes with w_max > 16 are excluded — they are not yet promoted to the board.)

| metric | top-1 code | heaviest (w=16) rank | Jaccard vs raw-K top20 | mean w_max in top20 |
|--------|-----------|----------------------|------------------------|--------------------|
| `K_G` | [[390,82,30]] weight-16 generalized bicycle code | 10 | 0.90 | 10.8 |
| `FoM_w` | [[390,82,30]] weight-16 generalized bicycle code | 10 | 0.90 | 10.8 |
| `COI` | [[472,122,14]] pair-partition CPM CSS (qc_472_122_14) | >20 | 0.74 | 10.2 |
| `Score_Fair` | [[390,82,30]] weight-16 generalized bicycle code | 13 | 0.90 | 10.8 |
| `K_lin` | [[390,82,30]] weight-16 generalized bicycle code | 9 | 0.74 | 11.1 |
| `mu` | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | >20 | 0.29 | 8.5 |
| `I_V` | [[14,6,2]] twisted-torus BB code (arXiv:2503.03827) | 13 | 0.25 | 9.2 |
| `rho` | [[590,240,12]] pair-partition CPM CSS (qc_590_240_12) | >20 | 0.33 | 9.4 |
| `Delta_Sing` | [[7,1,3]] color code | >20 | 0.00 | 5.8 |
| `sigma` | [[354,4,28]] twisted-torus BB code (arXiv:2503.03827) | >20 | 0.00 | 6.1 |
| `chi` | [[16,2,4]] toric code | >20 | 0.00 | 5.2 |
| `girth` | [[16,2,4]] toric code | >20 | 0.00 | 5.6 |

**Reading.** A fairer metric should (a) push the heaviest code (`[[254,44,24]]`, w=16) down the ranking and (b) surface lighter-weight codes in its top-20. `K_G`, `FoM_w`, and `Score_Fair` all demote the heaviest code relative to raw K; `K_lin`/`mu`/`I_V` do not touch weight at all and so leave it near the top. The penalized metrics are therefore the ones that actually correct the high-weight bias the notes warn about. (Note: with the w>16 codes excluded, the heaviest remaining code is only w=16, so the demotion effect is milder than on the full board.)

**Rank correlation with raw K (Spearman rho, all 126 codes).** rho=1 means identical ordering; lower rho means the metric reorders codes more aggressively away from raw K:

| metric | rho vs K |
|--------|----------|
| `K_G` | 0.987 |
| `FoM_w` | 0.987 |
| `COI` | 0.945 |
| `Score_Fair` | 0.986 |
| `K_lin` | 0.761 |
| `mu` | 0.105 |
| `I_V` | 0.089 |
| `rho` | 0.281 |

## Parameter ranges to prioritize

The notes recommend near-term targets of $n\in[100,1000]$, $k\in[10,100]$, $d\in[6,16]$, weight 4-8, girth 6. The board's actual coverage (126 codes) is:

- **n:** min 7, max 590, median 192
- **k:** min 1, max 240, median 8
- **d:** min 2, max 30, median 12
- **w_max:** [4, 5, 6, 7, 8, 10, 12, 13, 16]

**Codes already inside the recommended band:** 18 / 125.

**Prioritization guidance (derived from the board, not just the notes):**

1. **Weight class.** 73 codes are weight-6 and 27 weight-8 — the board is already dense there. The *sparse* cells are weight-4 (only 7 codes) and the high-weight tail (w>=12). For near-term fairness, push weight-6/8 girth-6 codes; for a record-breaking play, the weight-4 cell is the emptiest.
2. **Distance band.** Most codes cluster at d<=16; the notes' sweet spot d=10-12 is well populated. Genuine gaps appear at moderate n with d in [6,9] under weight-6.
3. **Rate.** High-k codes (k>100, the pair-partition CPM family) dominate rho and I_V but sit at w=8-10; they are 'wide' codes. The 'deep' regime (rho<1, high d per logical) is where the 390-family lives and is less contested on K_G.
4. **Girth.** 58 codes achieve per-side girth 6 (the notes' target); only 7 reach girth 8. A girth-8 code in the n~100-300, weight-6 band would be a structural standout.

**Concrete next directions:**
- Search the **weight-4** cell (only 7 entries) for any non-dual-containing girth-6 code — emptiest track, highest structural merit per the notes.
- Within weight-6, target **girth 8** at n in [100,300] to beat the 7 existing girth-8 codes on K_G.
- For the 390-family, prefer the **w=16** member (`[[390,82,30]]`) over w=32: it already tops K_G, FoM_w, and Score_Fair, confirming the notes' claim that weight-penalized metrics favor the lighter construction.

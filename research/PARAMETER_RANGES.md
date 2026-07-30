# Parameter Ranges to Prioritize

The notes recommend near-term targets of $n\in[100,1000]$, $k\in[10,100]$,
$d\in[6,16]$, weight 4-8, girth 6. The board's actual coverage (126 codes) is:

- **n:** min 7, max 590, median 198
- **k:** min 1, max 240, median 8
- **d:** min 2, max 40, median 12
- **w_max:** [4, 5, 6, 7, 8, 10, 12, 13, 16, 32]

**Codes already inside the recommended band:** 18 / 126.

## Prioritization guidance (derived from the board, not just the notes)

1. **Weight class.** 73 codes are weight-6 and 27 weight-8 — the board is
   already dense there. The *sparse* cells are weight-4 (only 7 codes) and the
   high-weight tail (w>=12). For near-term fairness, push weight-6/8 girth-6
   codes; for a record-breaking play, the weight-4 cell is the emptiest.
2. **Distance band.** Most codes cluster at d<=16; the notes' sweet spot
   d=10-12 is well populated. Genuine gaps appear at moderate n with d in [6,9]
   under weight-6.
3. **Rate.** High-k codes (k>100, the pair-partition CPM family) dominate rho
   and I_V but sit at w=8-10; they are 'wide' codes. The 'deep' regime
   (rho<1, high d per logical) is where the 390-family lives and is less
   contested on K_G.
4. **Girth.** 58 codes achieve per-side girth 6 (the notes' target); only 7
   reach girth 8. A girth-8 code in the n~100-300, weight-6 band would be a
   structural standout.

## Concrete next directions

- Search the **weight-4** cell (only 7 entries) for any non-dual-containing
  girth-6 code — emptiest track, highest structural merit per the notes.
- Within weight-6, target **girth 8** at n in [100,300] to beat the 7 existing
  girth-8 codes on K_G.
- For the 390-family, prefer the **w=16** member (`[[390,82,30]]`) over w=32:
  it already tops K_G, FoM_w, and Score_Fair, confirming the notes' claim that
  weight-penalized metrics favor the lighter construction.

# Leaderboard UX Guide

Working notes on the leaderboard UI improvements.

---

## 1. Primary Tracks Grid (Locality × Check Weight)

### Current issue

The "Primary tracks" grid packs multiple code links (`[[n,k,d]]`),
`kd²/n` metrics, and status badges directly inside small table cells.
Each non-empty cell contains a code-count button, then 3–6 code entries
each with a distance badge, the code link, and an efficiency number — all
in a compact grid that creates high cognitive load.

### Suggestions

- **Collapse non-Pareto entries by default.** Show only the top 1–2 codes
  per cell (sorted by `kd²/n`); expand the full list on click via the
  code-count button that already exists. This transforms each cell from a
  dense list into a lightweight preview.
- **Add a "best in cell" highlight.** The top code in each cell could get a
  small visual treatment (e.g. a subtle background tint or a small star)
  so the eye lands on the frontier first.
- **Consider a heatmap overlay.** Color the cell background by the best
  `kd²/n` value in that cell, so the user can scan which (locality, weight)
  combinations are productive at a glance, before reading individual codes.

---

### 1.5. Weight Tiers for the Tracks Grid

#### Current issue

The existing grid columns (weight ≤ 4, ≤ 6, ≤ 8, any weight) conflate
near-term hardware constraints with asymptotic connectivity. A code with
`w=32` is not practically useful in the same way as `w=4`, yet both can
appear as "records" in the same column. Without a graded system, the
board implicitly rewards unbounded "weight creep" — pushing check weight
up to game the `kd²/n` score rather than finding efficient codes at
realistic connectivities.

#### Proposal: Keep `kd²/n` as the single score, but grade by weight tier

`kd²/n` (presented as the **data qubit efficiency ratio**) remains the
primary and only score metric. No composite or secondary score (`f`-score
or similar) is introduced. However, the weight axis of the tracks grid
is re-graded so that codes compete within tiers that reflect real hardware
capabilities.

**Option A — Fine-grained bins (seven columns):**

| w ≤ 4 | w ≤ 6 | w ≤ 8 | w ≤ 10 | w ≤ 12 | w ≤ 16 | w ≤ 32 |
|-------|-------|-------|--------|--------|--------|--------|

This preserves the existing column logic but adds intermediate breakpoints
at 10, 12, and 16, giving a more nuanced view of connectivity requirements.

**Option B — Hardware tiers (four columns, preferred):**

| Tier | Weight cap | Label |
|------|-----------|-------|
| **Near term** | w ≤ 6 | Codes routable on near-term devices (low-degree connectivity, e.g. surface-code-scale hardware) |
| **Intermediate** | w ≤ 8 | Codes requiring moderate connectivity (some long-range crossings, but still feasible) |
| **High connectivity** | w ≤ 12 | Codes that need significant connectivity (e.g. neutral atom / ion trap with reconfigurable coupling) |
| **Unconstrained** | w ≤ 32 | Asymptotic / theoretical limit (no reasonable hardware constraint; w > 32 treated as unbounded) |

This avoids weight creep by making the "unconstrained" tier transparently
labeled — a code that wins only by pushing to `w=32` is clearly in the
asymptotic bucket, not competing against near-term designs.

#### How tier labels display

The grid column headers show the tier label + weight cap, e.g.:

> **Near term (w ≤ 6)** | **Intermediate (w ≤ 8)** | **High connectivity (w ≤ 12)** | **Unconstrained (w ≤ 32)**

On hover or in a tooltip, the hardware-context description appears.

#### Relationship to existing weight filter

The slider-based weight filter (`wlo` / `whi` range inputs) in the search
bar remains independent of the grid — it filters the table below regardless
of which tier a code lives in. The grid tracks are a separate navigation
metaphor (primary tracks), while the slider is a free-form exploration tool.

---

## 2. Filter Syntax & Search

### Current issue

The search bar accepts textual commands like `k>=10`, `eff>=5`, `record`,
`submitted`. The legend above the table is long and text-heavy, explaining
the meaning of the star, the hex mark, filled vs open circles, exact vs
upper bound, and the column labels.

### Suggestions

- **Add a "filter chips" UI.** As the user types, show recognized filters
  as removable chips below the search bar (e.g. `[k ≥ 10 ×] [record ×]`).
  This makes the filter state visible and editable.
- **Autocomplete / suggestions.** When the user types `k>` or `eff>`, show
  a dropdown of common values (e.g. `k>=4`, `k>=10`, `k>=20`).
- **Collapse the legend into a question-mark tooltip or a collapsible
  details element.** The legend is useful once but adds vertical scroll on
  every visit. A small `?` icon next to the search bar could open a compact
  legend modal.
- **Add a "clear all filters" button** that appears when any filter is active.
- **Track-tab + search interaction.** When a track tab is active (e.g.
  "bivariate bicycle"), show the active filter as a chip rather than
  just highlighting the tab, so the user can see the full filter state at
  a glance.

---

## 3. Color Coding

### Current state

The board uses a consistent palette:

| Element | Color | Code |
|---------|-------|------|
| Accent (links, stars, non-record points) | UF deep purple | `#36006c` |
| Highlight (records, hero glow, logo node) | UF signature yellow | `#ffff00` |
| Certified exact (badge, filled dot) | Emerald green | `#059669` |
| Dark surface (hero, code blocks) | Near-black | `#111111` |
| Non-record / open circle | White fill, slate border | `#fff` / `#475569` |

### Notes

- Green is used exclusively for **certified exact** distance — this is
  consistent and should stay.
- Yellow is used for hero glow, record stars, and the logo highlight node.
  It is loud by design, but only appears in the hero and the star column.
  Avoid expanding yellow into the table body.
- Purple (`#36006c`) is the primary accent for links and filled non-exact
  points. It reads well on white backgrounds.
- The scatter plot uses a separate 6-color palette (`MC` array in JS:
  `['#6d28d9','#0369a1','#b45309','#15803d','#be185d','#475569']`) for
  per-model series. These are distinct from the board palette and should
  remain so.
- **Consider a color-blind safe check.** The green/purple distinction is
  the main semantic signal (exact vs upper bound). Add a secondary cue:
  green = filled circle + `d =` label, purple = filled circle + `d ≤`
  label. The label already exists, so the information is already
  redundantly encoded.

---

### 3.5. Hardware & Decoder Badges

Beyond the core `kd²/n` score and distance tier, many practical constraints
determine whether a code is useful on real hardware. A set of opt-in badges
on the code detail page (and optionally in the board table) can surface
these properties without cluttering the primary score.

#### Proposed badges

| Badge | Criteria | Icon / label | Purpose |
|-------|----------|-------------|---------|
| **Decoder friendly** | Achieves fast decoder convergence time | `⚡ Decoder-friendly` | Signals that the code is not only good on paper but also practical to decode efficiently |
| **Hardware friendly** | Girth > 6 *and* low chromatic edge-coloring depth (e.g. ≤ 4 colors for syndrome extraction circuits) | `🔧 Hardware-friendly` | Signals that the code can be scheduled with low circuit depth and tolerates realistic noise — large girth avoids small cycles that hurt belief propagation; low chromatic depth means fewer time steps in the syndrome extraction circuit |
| **Easy routing** | Low column weight in the parity-check matrix (e.g. max column weight ≤ 3 or 4) | `🔄 Easy-routing` | Signals that each qubit participates in few checks, reducing the number of physical connections / crossings needed in a device layout |

#### Where badges appear

- **Code detail page** (`docs/codes/<slug>.html`): a dedicated "Badges" row
  or section below the metadata table, showing which badges a code qualifies
  for. Each badge links to a brief explanation (tooltip or expandable note).
- **Board table** (optional, opt-in column): a single "badges" column with
  compact icon-only indicators (e.g. `⚡` / `🔧` / `🔄`) — only shown if at
  least one badge is active. On narrow screens this column is hidden behind
  the detail page (as with `authors`/`model`/`date`).
- **Primary tracks grid** (optional): badge icons next to the code link in
  the cell, e.g. `[[392,8,15]] ⚡🔧` when the code qualifies for both.

#### Implementation notes

- Badge criteria are **computed by the build script** (`site/build.py`), not
  self-declared by the submitter. The builder computes girth, chromatic edge
  depth, and column weight from the parity-check matrices embedded in the
  submission JSON.
- Decoder-friendly status is more nuanced — it may require a simulation
  step. Start with a conservative heuristic (e.g. `d / w_avg > 2`), and
  replace with a full simulation-based badge later.
- Badges are **informational only**, not part of the scoring or ranking.
  A code with zero badges can still be a record — badges are secondary
  practical signals for hardware-aware comparison.
- Store badge data in `stats.json` alongside the existing code metadata,
  so the frontend can query it without re-running the build.

---

## 4. Interactive How-to-Participate Flow

### Current issue

The 3-step submission guide is a static card layout:
1. **Build a code** — "A CSS qLDPC code, written as one JSON file…"
2. **Open a PR** — "Add it under `codes/`. CI runs the verifier…"
3. **Climb the board** — "If it advances a track's frontier it is highlighted…"

There is a "Participate" button in the hero that opens a `<dialog>` with
a `git clone` command block — but the 3-step cards have no direct calls to
action and no visual progression.

### Suggestions

- **Make each step clickable.** Step 1 could link to `research/AUTORESEARCH.md`
  or the schema docs. Step 2 could link to `CONTRIBUTING.md`. Step 3 could
  scroll to the board or open the first code detail page.
- **Add a progress indicator.** If the user has submitted a code (tracked via
  `localStorage`), show a checkmark on the completed steps. This is a
  lightweight engagement signal.
- **Inline the "Participate" dialog trigger into the cards.** Replace the
  generic "Participate" button in the hero with a more prominent CTA in
  Step 2, e.g. "Submit your code →" that opens the dialog with the clone
  + submit commands.
- **Add a "quick start" collapsed section.** Below the cards, a collapsible
  `<details>` element with a minimal working example: a 5-line Python snippet
  that generates a random CSS code and saves it as a valid submission JSON.
- **Show a "you could beat this" callout.** In the hero or near the board,
  highlight the easiest track to beat (lowest `kd²/n` record) with a link
  to the research kit. E.g. "The lowest-hanging fruit: beat `[[7,1,3]]` in
  the weight-4, any-locality track."

---

## 5. Mobile & Compact Viewports

### Current issue

The main board table has 11 columns (`star`, `code`, `type`, `n`, `k`,
`d`, `kd²/n`, `w`, `authors`, `model`, `date`). On screens narrower than
~900px this causes severe clipping or requires double-axis scrolling.
The hero, stats bar, and scatter plots also need responsive treatment.

### Suggestions

- **Define responsive breakpoints and column priority.**

  | Breakpoint | Columns shown | Hidden / collapsed |
  |------------|--------------|-------------------|
  | ≥ 1024px | All 11 | — |
  | 768–1023px | 7: star, code, type, n, k, d, kd²/n | w, authors, model, date |
  | < 768px | 5: star, code, n, k, d | type, kd²/n, w, authors, model, date |

  Hidden columns can be revealed by tapping a row (opens the detail page
  which has all info).

- **Make the table horizontally scrollable but snap to the first columns.**
  `position: sticky` on the `code` column (first data column) so it stays
  visible while the user scrolls right to see `authors` / `model` / `date`.
  The star column should also be sticky so the record indicator is always
  visible.

- **Collapse the stats bar into a single-row "scorecard" on mobile.**
  The 4 stat cards (submitted codes, literature baselines, certified exact,
  best kd²/n) can become a horizontal strip with icon + number only, labels
  hidden behind a long-press tooltip.

- **Hero simplification.** On mobile, hide the flow-line animations
  (they already respect `prefers-reduced-motion` but still render), shrink
  the `uflogo`, and stack the GitHub link below the title.

- **Scatter plots.** The three SVG plots (distance, kd²/n, and a third view)
  are 520px wide. On < 540px viewports they overflow. Either:
  - Make them scale with `viewBox` + `width: 100%` (they already have
    `width:100%;height:auto` but the parent container may clip), or
  - Stack them vertically instead of the 3-column layout, or
  - Show only the first plot on mobile with a "show more" toggle.

- **Filter/search bar.** On mobile, collapse the track tabs into a
  `<select>` dropdown and place the weight sliders in a collapsible
  "filters" drawer.

- **Leaderboard contributor list.** The contributor rows (avatar, name,
  code count, etc.) should switch to a compact layout: avatar + name on
  one line, stats on the next line as inline badges.

- **Primary tracks grid.** The 4×5 grid becomes a 2-column or single-column
  layout on mobile. Each cell becomes a full-width card with the cell label
  as the card header.

---

## Appendix: Existing Responsive Infrastructure

The `docs/style.css` currently has **no media queries**. All styling is
desktop-first. The `index.html` viewport meta tag is present:
`<meta name=viewport content="width=device-width,initial-scale=1">`.

The hero flow lines use `prefers-reduced-motion` for accessibility but
not `prefers-color-scheme` for dark mode — the board is light-theme only.

The `boardscroll` and `ptscroll` wrappers use `overflow-x: auto` which
provides native horizontal scrolling on overflow, but the table columns
are too many to be useful on small screens without hiding some.
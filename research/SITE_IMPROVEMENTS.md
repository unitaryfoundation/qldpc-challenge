# QEC Challenge Site — Improvement Recommendations

Based on a full review of the live site at
[https://unitaryfoundation.github.io/qldpc-challenge/](https://unitaryfoundation.github.io/qldpc-challenge/)
and the existing `LEADERBOARD_UX.md` notes, here are prioritized improvements
organized by impact and effort.

---

## Priority 1 — High Impact, Low Effort

### 1.1. Add a "Quick Start" / "Try It" Section

**Problem:** The 3-step cards (Build → Open PR → Climb the Board) are
static and don't link to anything actionable. A new visitor has to read
the FAQ, find CONTRIBUTING.md, and figure out the schema before they can
do anything.

**Fix:** Add a collapsible `<details>` section below the 3-step cards with:
- A minimal 5-line Python snippet that generates a valid submission JSON
- A one-liner `uv run python verify/qldpc_verify.py codes/<slug>.json` to
  verify locally
- A link to `research/AUTORESEARCH.md` for the full research loop

This turns the "how to participate" section from a passive description into
an active on-ramp.

### 1.2. Make the 3-Step Cards Clickable

**Problem:** The cards are purely informational — no links, no CTAs.

**Fix:**
- Step 1 → link to `schema/SCHEMA.md` or `research/AUTORESEARCH.md`
- Step 2 → link to `CONTRIBUTING.md`
- Step 3 → scroll to the board or open the first code detail page

### 1.3. Add a "Lowest-Hanging Fruit" Callout

**Problem:** New contributors don't know where to start. The board is
intimidating with 148 codes and complex metrics.

**Fix:** In the hero or near the board, highlight the easiest track to beat:
> "The lowest-hanging fruit: beat `[[7,1,3]]` (kd²/n = 1.286) in the
> weight-4, any-locality track."

This gives a concrete, achievable target and lowers the barrier to entry.

### 1.4. Add a "Clear All Filters" Button

**Problem:** When filters are active (track tabs, search bar, sliders),
there's no easy way to reset everything at once.

**Fix:** Show a "Clear all filters" button that appears when any filter is
active. This is a simple JS addition.

### 1.5. Collapse the Legend into a Tooltip

**Problem:** The legend block (star, hex mark, filled/open circles, exact
vs upper bound, column labels) is long and adds vertical scroll on every
visit.

**Fix:** Collapse it into a `?` icon or a `<details>` element next to the
search bar. The legend is useful once but shouldn't dominate the page.

---

## Priority 2 — High Impact, Medium Effort

### 2.1. Responsive Design (Mobile)

**Problem:** The board table has 11 columns and no media queries. On
screens < 900px, it clips or requires double-axis scrolling. The scatter
plots, stats bar, and primary tracks grid also need responsive treatment.

**Fix:** Define breakpoints and column priority:

| Breakpoint | Columns shown | Hidden / collapsed |
|------------|--------------|-------------------|
| ≥ 1024px | All 11 | — |
| 768–1023px | 7: star, code, type, n, k, d, kd²/n | w, authors, model, date |
| < 768px | 5: star, code, n, k, d | type, kd²/n, w, authors, model, date |

Hidden columns are revealed by tapping a row (opens the detail page).

Additional mobile fixes:
- Make the table horizontally scrollable with `position: sticky` on the
  `code` column
- Collapse the stats bar into a single-row "scorecard" on mobile
- Stack the scatter plots vertically instead of 3-column layout
- Collapse the track tabs into a `<select>` dropdown on mobile
- Make the primary tracks grid 2-column or single-column on mobile

### 2.2. Filter Chips UI

**Problem:** The search bar accepts textual commands like `k>=10`, `eff>=5`,
`record`, `submitted`. The filter state is invisible — you can't see what's
active without reading the search bar text.

**Fix:** As the user types, show recognized filters as removable chips below
the search bar (e.g. `[k ≥ 10 ×] [record ×]`). This makes the filter state
visible and editable.

### 2.3. Autocomplete / Suggestions for Search

**Problem:** The search syntax is non-obvious. Users have to know the
exact format (`k>=10`, `eff>=5`, `record`, `submitted`, `with-layout`).

**Fix:** When the user types `k>` or `eff>`, show a dropdown of common
values (e.g. `k>=4`, `k>=10`, `k>=20`). This is a small JS addition
that dramatically improves discoverability.

### 2.4. Primary Tracks Grid — Collapse Non-Pareto Entries

**Problem:** Each cell in the primary tracks grid contains 3–6 code entries
with distance badges, code links, and efficiency numbers — creating high
cognitive load.

**Fix:** Show only the top 1–2 codes per cell (sorted by kd²/n); expand
the full list on click via the code-count button that already exists.
This transforms each cell from a dense list into a lightweight preview.

### 2.5. Add a "Best in Cell" Highlight

**Problem:** In the primary tracks grid, it's hard to spot the frontier
code in each cell.

**Fix:** The top code in each cell gets a subtle visual treatment (e.g.
a small star or background tint) so the eye lands on the frontier first.

### 2.6. Heatmap Overlay for Primary Tracks Grid

**Problem:** The grid is a wall of text. It's hard to scan which
(locality, weight) combinations are productive.

**Fix:** Color the cell background by the best kd²/n value in that cell,
so the user can scan which combinations are productive at a glance,
before reading individual codes.

---

## Priority 3 — Medium Impact, Medium Effort

### 3.1. Weight Tier Labels for the Tracks Grid

**Problem:** The existing grid columns (weight ≤ 4, ≤ 6, ≤ 8, any weight)
conflate near-term hardware constraints with asymptotic connectivity. A code
with w=32 is not practically useful in the same way as w=4.

**Fix:** Re-grade the weight axis with hardware-aware tier labels:

| Tier | Weight cap | Label |
|------|-----------|-------|
| **Near term** | w ≤ 6 | Codes routable on near-term devices |
| **Intermediate** | w ≤ 8 | Codes requiring moderate connectivity |
| **High connectivity** | w ≤ 12 | Codes needing significant connectivity |
| **Unconstrained** | w ≤ 32 | Asymptotic / theoretical limit |

The grid column headers show the tier label + weight cap, e.g.:
> **Near term (w ≤ 6)** | **Intermediate (w ≤ 8)** | **High connectivity (w ≤ 12)** | **Unconstrained (w ≤ 32)**

### 3.2. Hardware & Decoder Badges

**Problem:** Beyond the core kd²/n score and distance tier, many practical
constraints determine whether a code is useful on real hardware. These are
not surfaced anywhere.

**Fix:** Add opt-in badges on the code detail page (and optionally in the
board table):

| Badge | Criteria | Purpose |
|-------|----------|---------|
| **Decoder friendly** | Fast decoder convergence | Signals practical decodeability |
| **Hardware friendly** | Girth > 6 and low chromatic edge-coloring depth | Signals low circuit depth |
| **Easy routing** | Low column weight in parity-check matrix | Signals fewer physical connections |

Badges are computed by the build script, not self-declared. They are
informational only, not part of scoring.

### 3.3. Add a "You Could Beat This" Section

**Problem:** The board doesn't tell users where the easiest wins are.

**Fix:** Near the board, show a "lowest-hanging fruit" section that
highlights the easiest track to beat (lowest kd²/n record) with a link
to the research kit. E.g.:
> "The lowest-hanging fruit: beat `[[7,1,3]]` in the weight-4, any-locality track."

### 3.4. Improve the Record Progress Chart

**Problem:** The record progress chart is a single full-width panel with
three lines (w ≤ 6, w ≤ 8, any w). It's hard to see individual record
events or understand the timeline.

**Fix:**
- Add tooltips on hover that show the code name, kd²/n, and date
- Add a "zoom" feature to focus on a specific time range (e.g. 2025–2026)
- Consider adding a "by model" view that shows which AI models are
  contributing to records

### 3.5. Add a "Recent Activity" Feed

**Problem:** The board is static — there's no way to see what's been
submitted recently without scrolling through the entire table.

**Fix:** Add a "Recent Activity" section near the top that shows the
last 5–10 submissions with:
- Code name (e.g. `[[390,82,38]]`)
- Author (e.g. `@mathysrennela`)
- Date (e.g. `2026-07-19`)
- Whether it's a record (★)

This gives a sense of activity and momentum.

---

## Priority 4 — Medium Impact, High Effort

### 4.1. Dark Mode Support

**Problem:** The board is light-theme only. There's no `prefers-color-scheme`
support.

**Fix:** Add a dark mode toggle or respect `prefers-color-scheme: dark`.
The hero already uses a dark background, so the palette is partially
designed for it. The main challenge is the table and scatter plots.

### 4.2. Interactive Scatter Plots

**Problem:** The scatter plots are static SVGs. You can't hover over a
point to see the code name, or click to navigate to the detail page.

**Fix:** Make the scatter plots interactive:
- Hover over a point to see a tooltip with code name, kd²/n, and distance
- Click a point to navigate to the code detail page
- Add a "zoom" feature to focus on a specific region

### 4.3. Code Comparison Tool

**Problem:** There's no way to compare two codes side-by-side.

**Fix:** Add a "Compare" button on the code detail page that lets you
select another code and see a side-by-side comparison of:
- Parameters (n, k, d, w)
- Efficiency (kd²/n, g)
- Layout (r, ρ)
- Badges (decoder-friendly, hardware-friendly, easy-routing)

### 4.4. Export / Download

**Problem:** There's no way to download the board data as a CSV or JSON.

**Fix:** Add a "Download" button that exports the current filtered view
as a CSV or JSON file. This is useful for researchers who want to do
their own analysis.

---

## Priority 5 — Low Impact, Low Effort

### 5.1. Add a "What's New" Section

**Problem:** There's no way to see what's changed since the last visit.

**Fix:** Add a "What's New" section near the top that shows:
- New submissions (last 7 days)
- New records (last 7 days)
- New research notes (last 7 days)

### 5.2. Add a "Contributors" Section

**Problem:** The leaderboard shows contributors, but there's no dedicated
section that lists all contributors with their stats.

**Fix:** Add a "Contributors" section that shows:
- Avatar
- Name
- Number of codes submitted
- Number of records
- Best kd²/n

### 5.3. Add a "FAQ" Link in the Hero

**Problem:** The FAQ is linked in the footer but not in the hero.

**Fix:** Add a "FAQ" link in the hero navigation bar (it's already there
as a button, but it could be more prominent).

### 5.4. Add a "Research Log" Link in the Hero

**Problem:** The research log is linked in the footer but not in the hero.

**Fix:** Add a "Research Log" link in the hero navigation bar (it's already
there as a button, but it could be more prominent).

### 5.5. Add a "References" Link in the Hero

**Problem:** The references are linked in the footer but not in the hero.

**Fix:** Add a "References" link in the hero navigation bar (it's already
there as a button, but it could be more prominent).

---

## Implementation Notes

### Build System

All changes should be made in `site/build.py` since the site is generated
from a single Python script. The CSS is embedded in the `CSS` variable,
and the HTML is generated by the `build()` function.

### Testing

After making changes, run:
```bash
cd /Users/mathysrennela/Documents/GitHub/qldpc-challenge
python site/build.py
```

Then open `docs/index.html` in a browser to verify the changes.

### Accessibility

- Ensure all interactive elements are keyboard-accessible
- Add `aria-label` attributes to icons and buttons
- Ensure color contrast meets WCAG 2.1 AA standards
- Add `prefers-reduced-motion` support for animations

### Performance

- Keep the page lightweight (no external JS frameworks)
- Use CSS Grid and Flexbox for layout (already in use)
- Minimize the number of HTTP requests (already a single HTML file)
- Use lazy loading for images and charts

---

## Summary

| Priority | Impact | Effort | Items |
|----------|--------|--------|-------|
| 1 | High | Low | Quick start, clickable cards, lowest-hanging fruit, clear filters, collapse legend |
| 2 | High | Medium | Responsive design, filter chips, autocomplete, collapse grid entries, heatmap |
| 3 | Medium | Medium | Weight tiers, badges, recent activity, chart improvements |
| 4 | Medium | High | Dark mode, interactive scatter plots, code comparison, export |
| 5 | Low | Low | What's new, contributors, hero links |

The most impactful changes are in Priority 1 and 2. They address the
biggest pain points: discoverability, mobile usability, and filter
visibility. The existing `LEADERBOARD_UX.md` already covers many of these
ideas — this document adds concrete implementation details and prioritization.

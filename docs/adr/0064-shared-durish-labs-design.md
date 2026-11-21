# 0064: One design with the other Durish Labs sites

Status: accepted (2026-11-20).

## Context

The planner, durishlabs.com and the Forever API Atlas looked like three projects: blue-grey
and gold here, green-black and lime on the portfolio, near-black with gold and green on the
Atlas. The planner's gold accent (`#e0b04a`) was 1.1:1 from its own warning colour
(`#e0a24a`), so "primary" and "needs attention" looked the same. Much of its text was
12.8px or smaller, and it had no focus style of its own (#272–#276).

## Decision (Bryce, 2026-11-20)

1. **The planner follows DurishLabsPortfolio's `DESIGN.md`**: its colour tokens, type scale
   and components. The tokens are copied into `frontend/src/index.css` by hand; no shared
   package, CDN or stylesheet. A token changes there first, then here.
2. **Dark only.**
3. **One accent, lime `#d6ef8d`.** Amber is the warning colour only.
4. **System fonts:** `system-ui`, Georgia for display headings, the system monospace stack
   for code. No web fonts.
5. **The Durish Labs masthead** on every page: the DL mark links to durishlabs.com, then
   "Character Planner" links home.
6. **The item-quality colours stay the planner's own,** unchanged; they pass 4.5:1 on the
   shared surfaces except the selected-row fill, where item names don't go.

## Consequences

- ok, warn and error use the shared `--ok`, `--warn` and `--error`; the talent trees' states
  use them too, in place of three hard-coded colours.
- Nothing renders under 14px, and the planner has a visible focus ring on every control.
- A change to the shared look starts as an issue in DurishLabsPortfolio; the screenshot
  (`npm run screenshot`) is retaken after any visible change, and the portfolio copies it.

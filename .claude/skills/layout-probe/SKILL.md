---
name: layout-probe
description: Find and fix layout bugs in the web app with Playwright: things wider than a phone's screen, dialogs off the top, something wrong at one size only, or a layout check that passes locally and fails in CI. Gives a throwaway probe to measure what's wrong, then turns the finding into a lasting check. Use when Bryce reports a layout problem, or e2e fails on layout.
---

# Probe a layout bug

The app's browser checks live in `frontend/e2e/`, against a mocked API
(`api-fixtures.json`):
- `phone.spec.ts`: no sideways overflow per tab, landscape chrome, desktop.
- `dialogs.spec.ts`: every dialog fits and closes, at phone and desktop sizes.

`npm run e2e` builds the app and runs both. A probe comes first: measure, then fix, then
check.

## 1. Measure with the probe
```bash
cp .claude/skills/layout-probe/probe.spec.ts frontend/e2e/probe.spec.ts
cd frontend && npx playwright test e2e/probe.spec.ts --reporter=line 2>&1 | grep -E "^P |Error"
```
- **What to set:** `SIZES`, `TAB` and the optional steps in `inspect` (open a dialog,
  widen the text). For screenshots, set `SHOTS` to the scratchpad folder and look at them
  with the Read tool.
- **What it prints** for each size:
  - `inner`: the layout viewport;
  - `visual`: what's actually visible;
  - `overflow`: the page's width past the screen;
  - `wide`: the first unclipped elements past the right edge, with their right edges;
  - `dialog`: an open dialog's top and bottom.
- **Delete the probe after:** `rm frontend/e2e/probe.spec.ts`. It's never committed.
- **Missing fixture:** a route without an entry in `api-fixtures.json` answers `[]`, and
  some components break on that. Add an entry, keeping the file's one-space indent, so
  the diff stays small.

## 2. Read the numbers
- **`inner` bigger than `visual`:** the page zoomed out because something is too wide.
  - That moves dialogs and fixed elements too: they centre in the bigger box.
  - Fix the wide element; `wide` names it.
- **Something wide only in landscape:** a sideways phone (667–915 px) is wider than the
  640 px phone rules. Rules for both orientations go in the
  `@media (max-width: 640px), (max-height: 500px) and (orientation: landscape)` block in
  `App.css`.
- **Dialogs** cap at `100dvh`. On a real phone, `100vh` includes the hidden toolbar.
  - Playwright has no toolbar, so it can't reproduce that case; say so in the PR, and ask
    Bryce to check on his phone.
- **Fine locally, fails in CI:** CI's Linux fonts are wider. Widen the text in the probe
  (`letter-spacing: 1px` to `3px`) until it breaks locally, then fix it with room to
  spare.

## 3. Fix, and prove the check catches it
1. Fix the CSS, or the component.
2. Turn the finding into a check in `phone.spec.ts` or `dialogs.spec.ts`. Measure
   overflow against `visualViewport.width`, never `innerWidth`: a zoomed-out page grows
   `innerWidth` and hides the overflow. Add the size that showed it, if it's new.
3. Prove the check would have caught it:
   ```bash
   git stash push -q frontend/src/App.css && npx playwright test e2e/phone.spec.ts --reporter=line | grep -E "failed|passed"; git stash pop -q
   ```
   It must fail without the fix and pass with it. If it passes either way, the check is
   too weak: fix the check.
4. Run `npm run e2e`, `npm run lint` and `npm run typecheck`, then ship it with `ship-pr`.

# 0017: Landing page and guest mode

Status: accepted (2026-11-12).

## Context

With no character data the app showed one line: log in, then sync. A visitor without a
linked account got nothing from it, though the item pool and the scoring don't need a
character: only the comparison with worn gear does.

## Decision

- **Landing page** when there's no character data: what the planner does, a line per tab,
  how to get a character in (log in, then sync; "Sync now" when logged in with nothing
  synced), and what it reads and stores (read-only `wow.profile`; snapshots on this
  server).
- **Guest mode** under it: pick a class, a level, a faction and a play style (a shipped
  weight preset), and see the best pool items per slot and the dungeons worth running, as
  if every slot were empty. `GET /api/guest` lists the choices;
  `GET /api/guest/recommendations` computes. Both only read.
- **Shipped defaults only.** Guest mode uses `recommend.yaml` and the shipped presets,
  never edits made in the app, dismissals or targets: those belong to the tracked
  character, and a guest shouldn't see or depend on them. Nothing a guest picks is stored.
- **Classes:** only those with shipped rules, which today is Warrior. #15 adds the rest;
  the class is already a parameter.
- **Not in guest mode:** enchant advice (it scores against the enchant on the worn item),
  talents (only a Warrior plan exists) and the Plan tab.
- **Reaching it with a character:** `#guest` shows the same page with a link back, from
  "Guest mode" in the ⋯ menu.

## Consequences

- The pool's item details cover the levels it has fetched. On a fresh install with no
  character, a pool refresh fetches every item, so guest mode works at any level.
- When #16 adds users, guest mode stays anonymous and read-only.

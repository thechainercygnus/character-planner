# 0053: Every item links to Wowhead, built on the server

Status: accepted (2026-11-19).

## Context

Only some items linked to Wowhead (#225). Forever Companion's items carry a `wowhead`
link, and crafted gear built one, but an equipped item that Companion doesn't know showed
as plain text. Several views didn't link items at all, and the frontend built a link of
its own for the addon's items.

## Decision

1. **One place builds links:** `links.py`. A source's own link wins (Forever Companion's
   `wowhead`); else one is built from the item id as
   `https://www.wowhead.com/forever/item={id}`. That form serves both Forever's new items
   and the classic ones (checked on 270230 and 2589).
2. **Every view model that names an item and knows its id has a `wowhead` field.**
   - Models with only an id compute it (a pydantic `computed_field`).
   - Models with a source's link (`PoolItem`, `TargetInfo`, `CompanionInfo`) fall back
     to the built one.
   - The Markdown summary writes items as Markdown links.
3. **Links are never stored.** A gear target's `wowhead` is excluded when targets are
   saved, so a change to the address needs no migration.
4. **The frontend never builds a link.** One component, `ItemLink`, shows the server's
   link (in a new tab, `rel="noreferrer"`), or plain text when there's none. The targets
   editor takes the link with a pool item's id when a name matches one.
5. **No spell links.** Blizzard's recipe data has no spell id, and a recipe's id isn't
   its spell's. So a plain enchant, with no crafted item, stays unlinked.
6. **No Wowhead tooltips** (`power.js`). A third-party script on every page is a privacy
   and CSP question for its own issue.

## Consequences

- **An item with no id stays plain text:** a hand-entered target with no `item_id`, for
  example.
- **A link sends no character data:** it carries only the item's id, and no referrer.
- **A new view that names an item** gives its model a `wowhead` from `links.item_url`,
  and renders the name with `ItemLink`.

# Privacy

Every instance of Character Planner shows a privacy notice, linked from the footer of
every page as **Privacy**. Blizzard's API terms ask each instance for one, and for a way
to delete a player's data on request (ADR 0034). Each person who runs an instance is
responsible for their own copy, so the notice names that person: set
`OPERATOR_CONTACT` (below).

This page repeats what the notice says, and covers what an operator needs to do.

## What the notice says

**What's stored,** in the instance's own database on the machine it runs on:

- the character's data from Blizzard's Battle.net API (profile, gear, stats, talents,
  professions and the like), fetched at each sync;
- a short history for the Progress tab: the date, level and item level of each sync;
- what's set in the app: gear targets, talent plan, stat weights, rules, dismissed items
  and class quests marked done;
- the Discord webhooks added for alerts, and the alerts waiting to be sent;
- the Battle.net sign-in token, if someone signs in.

It also caches game data that's the same for every character: items, dungeons, recipes
and talent trees.

**How long:** data from Blizzard is kept for at most 30 days, and each sync replaces it.
The progress history and settings stay until they're deleted. Log files, if the operator
keeps them, can name the character in their lines; the operator decides how long to keep
them.

**Who can see it:** anyone who can open the instance's address. The planner has no
accounts of its own, so it's meant for your own computer or a private network
([Self-hosting](self-hosting.md)). Alerts go to the Discord channels chosen for them.

**Sharing:** nothing is sold, shared or used for advertising. The planner asks Blizzard's
API for the character by name and realm, and Forever Companion for items and dungeons by
id. Neither request carries anything else.

**Removing it:** the notice has a button that deletes everything stored for the
character.

## Setting the contact

Add a line to `.env`, then `docker compose up -d`:

```
OPERATOR_CONTACT=you@example.org
```

An email address or a web address shows as a link. Anything else, such as a name, shows
as text. Use one line of up to 200 characters. Without it, the notice says "the person who
runs this instance".

## Deleting the data

**From the app:** open **Privacy** in the footer, then **Delete the character's data**.
The button asks for a second click to confirm.

**From the command line:**

```
docker compose exec app character-planner-db erase --yes
```

From source, run `uv run character-planner-db erase --yes`.

Both delete:
- the snapshots and progress history;
- the settings edited in the app;
- the alerts and their webhooks;
- the stored tokens.

Settings go back to the shipped defaults. The shared game-data caches stay, since nothing
in them is about the character.

**Deletion isn't a stop.** The next sync, by hand or on the worker's schedule, fetches
the character again. To stop using a character's data for good, also stop the planner
(`docker compose down`), or change `CHARACTER_NAME` and `CHARACTER_SURNAME` to another
character before the next sync.

**Backups and logs:** they aren't touched. Delete them yourself if they hold the
character's data.

## Extending the notice

The notice lives in `frontend/src/components/Privacy.tsx`. If your instance stores or
shares more, for example because you've changed the code or put it behind a service that
logs visitors, say so there and on your copy of this page.

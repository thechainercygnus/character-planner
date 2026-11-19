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
- a Discord account linked for DMs: its id and name only, until it's unlinked;
- game data imported from the CharacterPlannerExport addon: the character's bags, bank
  and quest log, as of when the game saved them. Only the newest import is kept; it's
  deleted with the character, or from the app;
- with users on (`PLANNER_USERS`): each user's Battle.net account id, their role (admin,
  superuser or user), when they signed in, their sign-in sessions (only a hash of each),
  and which characters are theirs;
- the Battle.net sign-in token, if someone signs in. With it, the planner can list the
  account's characters to pick from. That list is fetched when it's shown and never
  stored: only the characters picked are tracked.

It also caches game data that's the same for every character: items, dungeons, talent
trees, and recipes, including every recipe of a tracked character's professions, learned or
not. Which professions it looks up follows from the characters tracked, but the recipes
themselves are game data, shared and not tied to anyone.

**How long:** data from Blizzard is kept for at most 30 days, and each sync replaces it.
The progress history and settings stay until they're deleted. Log files, if the operator
keeps them, can name the character in their lines; the operator decides how long to keep
them.

**Who can see it:** anyone who can open the instance's address. The planner has no
accounts of its own, so it's meant for your own computer or a private network
([Self-hosting](self-hosting.md)). Alerts go to the Discord channels chosen for them,
and DMs to the Discord account linked for them. With users on, each user's webhooks and
DMs get alerts about their own characters only.
With users on, a character added to its guild's view (the Guild tab) is shown to the
other members who joined it: its name, level, spec, role and upgrades. Leaving the view
stops that. If the guild sets an alert channel, the alerts a member chooses to share post
to that Discord channel, where anyone who can read it sees them. Nothing is shared until
the member ticks it.
With users on, the admin, and any superusers the admin appoints, see a list of the
accounts: each one's Battle.net account id, role, when it signed up and last signed in, and
its characters' names. Nothing more of anyone's.

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

**From the app:** pick the character in the header, open **Privacy** in the footer, then
**Delete the character's data**. The button asks for a second click to confirm. It
deletes that character's snapshots, progress history and settings, and stops tracking
it. Other characters, alert webhooks and shared game data stay.

**From the command line:**

```
docker compose exec app character-planner-db erase --yes
```

From source, run `uv run character-planner-db erase --yes`. This one deletes everything
stored for **every** character:
- the snapshots and progress history;
- the settings edited in the app;
- the alerts and their webhooks;
- the stored tokens.

Settings go back to the shipped defaults. The shared game-data caches stay, since nothing
in them is about the character.

**With users on,** the Privacy page also has **Delete my account**. It deletes your
characters with all their data and settings, your sign-in sessions, your Battle.net token,
your alert webhooks, a linked Discord account and your account. The admin can delete theirs only once nobody else uses the instance.
An operator handling a request can do it for anyone: in the admin area (**Admin** in the
menu, then **Delete…** on the account), or from the command line:

```
docker compose exec app character-planner-db delete-user ACCOUNT_ID --yes
```

For an access request, the admin area's **Export** downloads everything stored for an
account as JSON in a zip. Webhook URLs are masked, and sign-in sessions and tokens are left
out.

**The admin action log** records each deletion, export, role change and enchant
correction: who did it, to which account and when, as Battle.net account ids, with a short
detail but never the data. It's the record that a request was handled, so it stays after
the account it names is deleted. Entries are deleted after a year.

**With no characters left,** the planner is blank again, unless `CHARACTER_NAME` and
`CHARACTER_SURNAME` are set: then the next start tracks that character again. To stop
using it for good, remove those settings too.

**Backups and logs:** they aren't touched. Delete them yourself if they hold the
character's data.

## Extending the notice

The notice lives in `frontend/src/components/Privacy.tsx`. If your instance stores or
shares more, for example because you've changed the code or put it behind a service that
logs visitors, say so there and on your copy of this page.

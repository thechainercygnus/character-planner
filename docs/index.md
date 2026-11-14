# Character Planner

[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/16645/badge)](https://www.bestpractices.dev/projects/16645)

A planner for a WoW Forever character. It reads your character from Battle.net and works
out what to do next:
- what the next few levels bring;
- the gear upgrades within reach, from dungeons, quests, rares and your own crafting;
- the dungeons worth running;
- the enchants to look for;
- how your talents and gear compare with your plan;
- the class quests to do, and any essential ones missed;
- your professions' next trainer ranks and what they need.

It's free software (AGPL-3.0-or-later) that you host yourself.

- **Run your own:** [Self-hosting](self-hosting.md) goes from nothing to a synced character.
- **Releases:** [Releasing](releasing.md) covers how versions are published, and how to verify
  an image before running it.
- **Privacy:** [Privacy](privacy.md) says what an instance stores, for how long, and how
  to delete it.
- **How it works:** the [architecture](architecture.md) shows the parts and how data flows
  between them; the [assurance case](assurance-case.md) covers its security.
- **API:** the [API reference](api.md) lists every endpoint and the data it takes and returns.
- **Decisions:** the [architecture decision records](adr/index.md) say why things are the way
  they are.

The source, issues and roadmap are on
[GitHub](https://github.com/thechainercygnus/character-planner). To help, see
[CONTRIBUTING.md](https://github.com/thechainercygnus/character-planner/blob/main/CONTRIBUTING.md).
Report security problems privately, as
[SECURITY.md](https://github.com/thechainercygnus/character-planner/blob/main/SECURITY.md)
explains.

Character and game data come from Blizzard Entertainment's
[Battle.net API](https://develop.battle.net/). Item and dungeon data come from
[Forever Companion](https://forevercompanion.io). Fan-made,
not affiliated with Blizzard Entertainment.

```{toctree}
:hidden:

self-hosting
privacy
releasing
architecture
assurance-case
api
adr/index
```

# 0020: Self-hosted and managed, from one codebase

Status: accepted (2026-11-12).

## Context

The planner is to be released as a free tool that anyone can host for themselves, while
Bryce also runs an instance for others. The two have different operators, different
Discord setups and different scale, and should still be the same software.

## Decision

- **One codebase and one image.** There's no "mode" setting. A feature switches on when
  what it needs is configured. For example, Discord bot DMs need a bot token (#58), and
  without one the option doesn't appear.
- **Each instance uses its own Battle.net client.** A self-hoster creates one and puts its
  id and secret in `.env`. The managed instance uses Bryce's.
- **Two audiences for alerts** (#12):
  - **System alerts** go to whoever runs the instance: the user on a self-hosted copy, Bryce on the managed one.
  - **User alerts** go to each character's owner.

  On a self-hosted copy, system alerts default to the user's destination.
- **Webhooks first.** Discord webhooks pasted into the app work everywhere with nothing
  else to run. Bot DMs (#58) and guild channels (#18) come later and are optional.
- **Single-user stays simple.** A self-hoster shouldn't need sign-ups. #16 decides how that
  works while keeping accounts for the managed instance.
- **Before the first public release:**
  - a license (#59);
  - schema migrations (#60), so databases upgrade in place;
  - tagged images on GHCR (#61);
  - a self-hosting guide (#62).
- **The managed instance's extra duties** stay with the multi-user epic (#13, #17, #44):
  - Blizzard's terms for a shared app;
  - Forever Companion's agreement before sending many users' traffic;
  - privacy and data retention;
  - encrypting stored credentials such as webhook URLs at rest;
  - restricting upstream refreshes to the operator.

## Consequences

- Every new setting needs a sensible default for a single self-hoster.
- Docs: one guide, `docs/self-hosting.md` (#62), for anyone; the homelab's specifics are
  sections of it (Bryce, 2026-11-13: merged rather than kept as a second guide).
- Breaking changes to `.env` or the database need release notes and a migration.

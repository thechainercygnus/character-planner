# 0002: Store raw API snapshots before modelling them

Status: accepted (2026-11-11)

## Context

The WoW Forever Profile API is undocumented. Community probing (Nov 2026) found the
`profile-forever-{region}` namespace and `{name}-{surname}` character routes, but some
lookups return 404 and response shapes are unconfirmed.

## Decision

- Every sync stores each endpoint's raw JSON and HTTP status as a `Snapshot` row, failures
  included.
- Typed models are written only from real responses captured by the spike
  (`uv run character-planner-spike`), which become test fixtures.
- Data the API can't supply goes in through `POST /snapshots/manual` in the same shape.

## Consequences

- Nothing captured is lost to a wrong guess about the schema; history is kept for free.
- Readers (`summary.py`) must stay defensive until fixtures replace the synthetic ones.
- The 404 rate per endpoint is itself recorded, which documents the API as it changes.

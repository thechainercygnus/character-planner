# 0001: Python backend with FastAPI

Status: accepted (2026-11-11)

## Context

The planner needs a backend: the Battle.net client secret can't ship to a browser.

## Decision

Python 3.14, FastAPI, SQLite through SQLModel, managed with uv. Frontend is a separate
TypeScript decision, made later.

## Consequences

- Same stack shape as other projects (FastAPI + TS SPA), so patterns carry over.
- One process, one SQLite file: fine for a single user behind the tailnet.

"""Refresh the item pool from the command line, with progress (ADR 0006).

Run with: uv run character-planner-pool [--force] [--level N]

Same work as POST /api/pool/refresh. The first run is a few hundred requests paced
under Forever Companion's rate limit, so it takes a few minutes; later runs only fetch
what's stale. Level and faction come from the latest synced profile unless --level is
given.
"""

import argparse
import sys
from collections import Counter

from sqlmodel import Session

from character_planner.config import get_settings
from character_planner.db import init_db, latest_by_kind, make_engine
from character_planner.pool import pool_view, refresh_pool
from character_planner.views import character_faction, character_level


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh the item pool, with progress.")
    parser.add_argument("--force", action="store_true", help="refetch everything")
    parser.add_argument("--level", type=int, help="level window to use (default: synced level)")
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    with Session(engine) as session:
        profile = latest_by_kind(session).get("profile")
        payload = profile.payload if profile else None
        level = args.level if args.level is not None else character_level(payload)
        faction = character_faction(payload)
        print(f"Level {level or 'unknown (whole pool)'}, faction {faction or 'unknown'}")

        def progress(message: str) -> None:
            print(f"  {message}", end="\r", flush=True)

        result = refresh_pool(
            session,
            level=level,
            faction=faction,
            force=args.force,
            pause=settings.companion_request_pause,
            progress=progress,
        )
        print(" " * 60, end="\r")
        print(
            f"Dungeons: {result.dungeons_listed} listed, {result.dungeons_fetched} fetched\n"
            f"Pool: {result.pool_size} items, {result.in_window} in the level window\n"
            f"Item details: {result.items_fetched} fetched, "
            f"{len(result.items_not_found)} not found"
        )
        for error in result.errors:
            print(f"  error: {error}")

        view = pool_view(session, level, faction)
        by_slot = Counter(item.slot or "?" for item in view.items)
        print("In window by slot: " + ", ".join(f"{s} {n}" for s, n in sorted(by_slot.items())))
    return 1 if result.errors else 0


if __name__ == "__main__":
    sys.exit(main())

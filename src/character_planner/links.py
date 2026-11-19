"""Wowhead links (#225, ADR 0053): every item the app shows links to its page, built here.

Forever has its own section on Wowhead, `/forever/`, which has Forever's new items and the
classic ones (checked on Kindlegem Girdle, 270230, and Linen Cloth, 2589). A link sends no
character data: it's the item's id and nothing else.

Spells aren't linked: Blizzard's recipe data has no spell id (a recipe's id isn't its spell's),
so an enchant with no crafted item has no page we know of.
"""

from typing import Final

WOWHEAD: Final = "https://www.wowhead.com/forever"
WOWHEAD_ITEM: Final = WOWHEAD + "/item={item_id}"
WOWHEAD_QUEST: Final = WOWHEAD + "/quest={quest_id}"


def item_url(item_id: int | None, given: str | None = None) -> str | None:
    """A source's own link (Forever Companion's `wowhead`) when it has one, else one built
    from the id; None with neither."""
    if given:
        return given
    return WOWHEAD_ITEM.format(item_id=item_id) if item_id is not None else None


def quest_url(quest_id: int | None) -> str | None:
    return WOWHEAD_QUEST.format(quest_id=quest_id) if quest_id is not None else None

"""Talent trees from Blizzard's game data (#88, ADR 0025).

Forever's trees are in the static-forever namespace: /talent-tree/index names each class's
tree (Warlock: 1116), /talent-tree/{id} has every node with `locked_by` (prerequisites),
and /talent-tree/{id}/playable-specialization/{spec} has one spec's nodes, each with its
grid place (`display_row`, `display_col`) and its ranks with their tooltip text. Every node
is one talent with 1 to 5 ranks (checked in all 6 Warlock and Warrior trees). Columns
count across the whole class (Protection is 14-17), so each tree's are made 1-based.

The raw responses are stored (TalentTreeData, ADR 0002) and parsed on read; spell icons
come from /media/spell/{id} like item icons.

Points per row: Classic's rule, 5 points in a tree per row before the next row opens. It
isn't in the data; the synced Warrior (5 in row 1, then two talents in row 2 at 9 points)
fits it. Correct POINTS_PER_ROW if Forever differs.
"""

import logging
from collections.abc import Iterable

import httpx
from pydantic import BaseModel
from sqlmodel import Session, select

from character_planner import fields
from character_planner.blizzard import oauth
from character_planner.blizzard.client import BlizzardClient
from character_planner.config import Settings
from character_planner.db import SpellIcon, TalentTreeData, save_now, utcnow
from character_planner.logs import JobLog

logger = logging.getLogger(__name__)

POINTS_PER_ROW = 5


class TalentNode(BaseModel):
    node_id: int
    talent_id: int
    name: str
    spell_id: int | None
    row: int  # 1 at the top
    col: int  # 1 at the left of its tree
    max_rank: int
    ranks: list[str]  # each rank's description
    requires: list[int]  # talent ids that must be at their max rank first
    icon_url: str | None = None


class SpecTree(BaseModel):
    spec_id: int
    name: str
    nodes: list[TalentNode]


class ClassTree(BaseModel):
    class_name: str
    tree_id: int
    specs: list[SpecTree]

    def nodes(self) -> dict[int, tuple[SpecTree, TalentNode]]:
        """Every node by talent id, with its tree."""
        return {n.talent_id: (spec, n) for spec in self.specs for n in spec.nodes}


# --- parsing -----------------------------------------------------------------------------


def _id_from(href: object, after: str) -> int | None:
    if not isinstance(href, str) or after not in href:
        return None
    part = href.split(after, 1)[1].split("?", 1)[0].split("/", 1)[0]
    return int(part) if part.isdigit() else None


def class_tree_id(index: object, class_name: str) -> int | None:
    for entry in fields.get(index, "class_talent_trees") or []:
        if str(fields.get(entry, "name") or "").casefold() == class_name.casefold():
            return _id_from(fields.get(entry, "key", "href"), "/talent-tree/")
    return None


def spec_ids(class_payload: object) -> list[tuple[int, str]]:
    """(spec id, name) for each spec tree a class tree lists, in its order."""
    out = []
    for entry in fields.get(class_payload, "spec_talent_trees") or []:
        spec_id = _id_from(fields.get(entry, "key", "href"), "playable-specialization/")
        if spec_id is not None:
            out.append((spec_id, str(fields.get(entry, "name") or spec_id)))
    return out


def _node(
    payload: object, talent_of: dict[int, int], prereqs: dict[int, list[int]]
) -> TalentNode | None:
    node_id = fields.as_int(fields.get(payload, "id"))
    ranks = fields.get(payload, "ranks") or []
    if node_id is None or not ranks:
        return None
    talent = fields.get(ranks[0], "tooltip", "talent")
    talent_id = fields.as_int(fields.get(talent, "id"))
    row = fields.as_int(fields.get(payload, "display_row"))
    col = fields.as_int(fields.get(payload, "display_col"))
    if talent_id is None or row is None or col is None:
        return None
    return TalentNode(
        node_id=node_id,
        talent_id=talent_id,
        name=str(fields.get(talent, "name") or talent_id),
        spell_id=fields.as_int(fields.get(ranks[0], "tooltip", "spell_tooltip", "spell", "id")),
        row=row,
        col=col,
        max_rank=len(ranks),
        ranks=[str(fields.get(r, "tooltip", "spell_tooltip", "description") or "") for r in ranks],
        requires=[talent_of[n] for n in prereqs.get(node_id, []) if n in talent_of],
    )


def parse_class_tree(
    class_name: str,
    tree_id: int,
    class_payload: object,
    spec_payloads: dict[int, object],
    icons: dict[int, str] | None = None,
) -> ClassTree:
    """A class's spec trees from the stored responses. Prerequisites come from the class
    tree's `locked_by`, as node ids, and are turned into talent ids."""
    icons = icons or {}
    prereqs: dict[int, list[int]] = {}
    talent_of: dict[int, int] = {}
    for payload in fields.get(class_payload, "talent_nodes") or []:
        node_id = fields.as_int(fields.get(payload, "id"))
        ranks = fields.get(payload, "ranks") or []
        talent_id = (
            fields.as_int(fields.get(ranks[0], "tooltip", "talent", "id")) if ranks else None
        )
        if node_id is None:
            continue
        if talent_id is not None:
            talent_of[node_id] = talent_id
        locked = [i for x in fields.get(payload, "locked_by") or [] if (i := fields.as_int(x))]
        prereqs[node_id] = locked
    specs = []
    for spec_id, name in spec_ids(class_payload):
        payload = spec_payloads.get(spec_id)
        nodes = [
            node
            for raw in fields.get(payload, "spec_talent_nodes") or []
            if (node := _node(raw, talent_of, prereqs)) is not None
        ]
        if not nodes:
            continue
        left = min(n.col for n in nodes) - 1
        for node in nodes:
            node.col -= left
            node.icon_url = icons.get(node.spell_id or 0)
        nodes.sort(key=lambda n: (n.row, n.col))
        specs.append(SpecTree(spec_id=spec_id, name=name, nodes=nodes))
    return ClassTree(class_name=class_name, tree_id=tree_id, specs=specs)


# --- storage and refresh --------------------------------------------------------------------


def _stored(session: Session, key: str) -> object | None:
    row = session.get(TalentTreeData, key)
    return row.payload if row else None


def stored_tree(session: Session, class_name: str) -> ClassTree | None:
    """The class's trees as last fetched; None until they're loaded."""
    index = _stored(session, "index")
    tree_id = class_tree_id(index, class_name) if index else None
    class_payload = _stored(session, f"class:{tree_id}") if tree_id else None
    if tree_id is None or class_payload is None:
        return None
    specs = {
        spec_id: payload
        for spec_id, _ in spec_ids(class_payload)
        if (payload := _stored(session, f"spec:{tree_id}:{spec_id}")) is not None
    }
    icons = {row.spell_id: row.url for row in session.exec(select(SpellIcon)).all() if row.url}
    return parse_class_tree(class_name, tree_id, class_payload, specs, icons)


class TalentRefresh(BaseModel):
    class_name: str
    trees: int = 0  # class and spec trees fetched
    icons: int = 0
    errors: list[str] = []


def refresh_talent_trees(
    session: Session, settings: Settings, class_name: str, *, http: httpx.Client | None = None
) -> TalentRefresh:
    """Fetch a class's talent trees and its talents' spell icons (app-only token)."""
    outcome = TalentRefresh(class_name=class_name)
    namespace = settings.static_namespace
    try:
        token = oauth.client_credentials(settings, client=http)
    except httpx.HTTPError as error:
        outcome.errors.append(f"Blizzard token: {error}")
        logger.warning("Talent trees: no Blizzard token: %s", error)
        return outcome
    with BlizzardClient(settings, token, http=http) as client:
        index = client.get("talent-tree-index", "/data/wow/talent-tree/index", namespace)
        if not index.ok:
            outcome.errors.append(f"talent tree index: HTTP {index.status}")
            logger.warning("Talent trees: index HTTP %s", index.status)
            return outcome
        save_now(session, TalentTreeData(key="index", payload=index.body, fetched_at=utcnow()))
        tree_id = class_tree_id(index.body, class_name)
        if tree_id is None:
            outcome.errors.append(f"no talent tree for the class {class_name}")
            logger.warning("Talent trees: no tree for the class %s", class_name)
            return outcome
        path = f"/data/wow/talent-tree/{tree_id}"
        tree = client.get("talent-tree", path, namespace)
        if not tree.ok:
            outcome.errors.append(f"{class_name} talent tree: HTTP {tree.status}")
            return outcome
        save_now(
            session, TalentTreeData(key=f"class:{tree_id}", payload=tree.body, fetched_at=utcnow())
        )
        outcome.trees += 1
        for spec_id, name in spec_ids(tree.body):
            spec = client.get(
                "talent-tree-spec", f"{path}/playable-specialization/{spec_id}", namespace
            )
            if not spec.ok:
                outcome.errors.append(f"{name} talent tree: HTTP {spec.status}")
                continue
            key = f"spec:{tree_id}:{spec_id}"
            save_now(session, TalentTreeData(key=key, payload=spec.body, fetched_at=utcnow()))
            outcome.trees += 1

        parsed = stored_tree(session, class_name)
        spells = [n.spell_id for _, n in (parsed.nodes().values() if parsed else []) if n.spell_id]
        # Spells without an icon yet are tried again: a failed lookup may have been a blip.
        known = {row.spell_id for row in session.exec(select(SpellIcon)).all() if row.url}
        wanted = [s for s in dict.fromkeys(spells) if s not in known]
        job = JobLog(logger, "Talent icons", len(wanted))
        for number, spell_id in enumerate(wanted, start=1):
            job.step(number)
            media = client.get("spell-media", f"/data/wow/media/spell/{spell_id}", namespace)
            url = _icon(media.body) if media.ok else None
            save_now(session, SpellIcon(spell_id=spell_id, url=url, fetched_at=utcnow()))
            outcome.icons += url is not None
        job.done(f"{outcome.icons} icons found")
    logger.info(
        "Talent trees for %s: %d trees fetched, %d errors",
        class_name,
        outcome.trees,
        len(outcome.errors),
    )
    return outcome


def _icon(body: object) -> str | None:
    for asset in fields.get(body, "assets") or []:
        if fields.get(asset, "key") == "icon":
            value = fields.get(asset, "value")
            return value if isinstance(value, str) else None
    return None


# --- plans -----------------------------------------------------------------------------------


class PlanPoint(BaseModel):
    """One step of a plan as the checks see it: a talent raised to a rank."""

    talent_id: int
    rank: int


def check_plan(points: Iterable[PlanPoint], tree: ClassTree) -> list[str]:
    """Problems with a plan, in spending order: unknown talents, ranks past the max or not
    rising, prerequisites not maxed first, and rows opened before their 5 points per row."""
    nodes = tree.nodes()
    rank: dict[int, int] = {}
    spent: dict[int, int] = {}  # points per spec tree
    problems = []
    for number, point in enumerate(points, start=1):
        found = nodes.get(point.talent_id)
        if found is None:
            problems.append(
                f"Step {number}: talent {point.talent_id} isn't in the {tree.class_name} trees"
            )
            continue
        spec, node = found
        before = rank.get(node.talent_id, 0)
        if point.rank <= before:
            problems.append(f"Step {number}: {node.name} is already at rank {before}")
            continue
        if point.rank > node.max_rank:
            problems.append(f"Step {number}: {node.name} only has {node.max_rank} ranks")
            continue
        if before == 0:
            needed = POINTS_PER_ROW * (node.row - 1)
            if spent.get(spec.spec_id, 0) < needed:
                problems.append(
                    f"Step {number}: {node.name} needs {needed} points in {spec.name} first"
                )
            for required in node.requires:
                _, prereq = nodes[required]
                if rank.get(required, 0) < prereq.max_rank:
                    problems.append(
                        f"Step {number}: {node.name} needs {prereq.name} at "
                        f"{prereq.max_rank}/{prereq.max_rank} first"
                    )
        spent[spec.spec_id] = spent.get(spec.spec_id, 0) + point.rank - before
        rank[node.talent_id] = point.rank
    return problems

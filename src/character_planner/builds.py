"""Builds (#216, ADR 0060): what a character is for, as one choice.

A build is curated per class (data/curated/builds.yaml for the Warrior, `builds:` in
classes/<class>.yaml for the rest). Picking one sets its pieces at once:

- its stat-weight preset becomes the active one;
- its talent order, when it has one, becomes the talent plan, so the planner's next point
  is the build's next point;
- its role is the character's in the guild view, unless the member picks one there.

Each piece can still be edited. The character then shows "customised" against the build it
started from, piece by piece. One build per character, switched by hand (Bryce, 2026-11-19).
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlmodel import Session

from character_planner.classes import ClassDefaults, current_defaults
from character_planner.db import (
    CharacterBuild,
    WeightPreset,
    delete_owned,
    owned,
    save_owned,
    utcnow,
)
from character_planner.scoring import activate, active_key
from character_planner.talents import TalentPlan, current_plan, save_plan

Role = Literal["tank", "healer", "dps"]
Piece = Literal["weights", "talents"]


class UnknownBuild(LookupError):
    """A build the character's class doesn't ship."""


class BuildSummary(BaseModel):
    key: str
    name: str
    role: Role
    preset: str  # the weight preset's key
    preset_name: str
    talents: bool  # carries a talent order
    spec: str | None  # the talent order's tree, when it has one


class BuildsView(BaseModel):
    class_name: str
    builds: list[BuildSummary]
    current: str | None  # the build the character follows; None: none picked
    # The pieces changed since it was picked: its weights, its talent plan.
    customised: list[Piece] = []


def _steps(plan: TalentPlan) -> list[tuple[int | None, str, int]]:
    return [(s.talent_id, s.talent.casefold(), s.rank) for s in plan.steps]


def customised(
    session: Session, defaults: ClassDefaults, key: str | None, character_id: int | None
) -> list[Piece]:
    build = defaults.build(key)
    if build is None:
        return []
    pieces: list[Piece] = []
    edited = owned(session, WeightPreset, character_id, key=build.preset)
    active = active_key(session, defaults.presets, character_id)
    if active != build.preset or (edited is not None and edited.shipped):
        pieces.append("weights")
    if build.talents is not None:
        plan = current_plan(session, defaults.talent_plan, character_id)
        if _steps(plan) != _steps(build.talents):
            pieces.append("talents")
    return pieces


def builds_view(session: Session, curated_dir: Path, character_id: int | None) -> BuildsView:
    defaults = current_defaults(session, curated_dir, character_id)
    row = owned(session, CharacterBuild, character_id)
    current = row.key if row is not None and defaults.build(row.key) is not None else None
    return BuildsView(
        class_name=defaults.playable.name,
        builds=[
            BuildSummary(
                key=b.key,
                name=b.name,
                role=b.role,
                preset=b.preset,
                preset_name=preset.name if (preset := defaults.presets.get(b.preset)) else b.preset,
                talents=b.talents is not None,
                spec=b.talents.spec if b.talents is not None else None,
            )
            for b in defaults.builds
        ],
        current=current,
        customised=customised(session, defaults, current, character_id),
    )


def choose(
    session: Session, curated_dir: Path, key: str | None, character_id: int | None
) -> BuildsView:
    """Follow a build: its preset and talent order become the character's. None stops
    following one and changes nothing else."""
    if key is None:
        if delete_owned(session, CharacterBuild, character_id):
            session.commit()
        return builds_view(session, curated_dir, character_id)
    defaults = current_defaults(session, curated_dir, character_id)
    build = defaults.build(key)
    if build is None:
        raise UnknownBuild(f"No {key} build for a {defaults.playable.name}")
    activate(session, defaults.presets, build.preset, character_id)
    if build.talents is not None:
        save_plan(session, build.talents, character_id)
    save_owned(session, CharacterBuild, character_id, {}, {"key": key, "chosen_at": utcnow()})
    session.commit()
    return builds_view(session, curated_dir, character_id)


def build_role(session: Session, curated_dir: Path, character_id: int | None) -> Role | None:
    """The role of the build the character follows, for the guild view (#216)."""
    row = owned(session, CharacterBuild, character_id)
    if row is None:
        return None
    build = current_defaults(session, curated_dir, character_id).build(row.key)
    return build.role if build is not None else None

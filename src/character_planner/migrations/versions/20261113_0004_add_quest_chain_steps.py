"""Add quest chain steps (#7, ADR 0028)

Revision ID: 0004
Revises: 0003
Create date: 2026-11-13 11:33:44.082464
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companionquest",
        sa.Column("quest_id", sa.Integer(), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("quest_id"),
    )


def downgrade() -> None:
    op.drop_table("companionquest")

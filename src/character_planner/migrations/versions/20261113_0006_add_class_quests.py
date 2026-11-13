"""Add class quests and done marks (#8, ADR 0030)

Revision ID: 0006
Revises: 0005
Create date: 2026-11-13 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "companionclassquest",
        sa.Column("quest_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("quest_id"),
    )
    op.create_table(
        "classquestdone",
        sa.Column("quest_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("done_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("quest_id"),
    )


def downgrade() -> None:
    op.drop_table("classquestdone")
    op.drop_table("companionclassquest")

# pyright: basic
"""Alert webhooks belong to users: the ones from before go to the admin (#164)

Webhooks had no owner while only the admin could add them. With users on, a character's
alerts now go only to its owner's webhooks, so an instance that already has an admin hands
them its webhooks, as their characters were handed to them at the first sign-in. Without
users there's no admin yet: they stay unowned, and the first sign-in adopts them.

Revision ID: 0015
Revises: 0014
Create date: 2026-11-15 02:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE notificationdestination SET user_id = "
            '(SELECT id FROM "user" WHERE is_admin ORDER BY id LIMIT 1) '
            "WHERE user_id IS NULL AND kind = 'discord_webhook'"
        )
    )


def downgrade() -> None:
    # Owned webhooks worked before too, as the admin's: nothing to undo.
    pass

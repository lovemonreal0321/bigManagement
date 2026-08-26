"""per-user jobs visibility

Jobs carry salaries, so unlike the rest of the workspace they are not readable
by default. Existing accounts get `false`: nobody silently gains sight of pay
because of an upgrade. An administrator grants it deliberately, per account.

Revision ID: c92d2ecf7f9c
Revises: 80445fac75da
Create Date: 2026-08-26 23:55:21.650301
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c92d2ecf7f9c'
down_revision: str | None = '80445fac75da'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A server default is required to add a NOT NULL column to a populated
    # table. It is dropped again below so the application, not the database,
    # decides what a new account looks like.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'can_view_jobs',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('can_view_jobs', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('can_view_jobs')

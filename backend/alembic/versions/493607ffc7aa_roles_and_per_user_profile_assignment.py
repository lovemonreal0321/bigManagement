"""roles and per-user profile assignment

Adds the admin/user split. Any account that already exists predates roles and
was the workspace's sole login, so it is promoted to admin — otherwise the
upgrade would lock the only user out of their own settings.

Revision ID: 493607ffc7aa
Revises: 7f968376af4b
Create Date: 2026-08-19 16:00:34.923220
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Migrations reference the project's custom column types (GUID, UTCDateTime),
# which autogenerate renders with their full dotted path.
import app.core.types

revision: str = '493607ffc7aa'
down_revision: str | None = '7f968376af4b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user_people',
        sa.Column('user_id', app.core.types.GUID(length=36), nullable=False),
        sa.Column('person_id', app.core.types.GUID(length=36), nullable=False),
        sa.ForeignKeyConstraint(['person_id'], ['people.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'person_id'),
    )

    # Server defaults are required to add NOT NULL columns to a populated
    # table. They are dropped again below so that the application, not the
    # database, decides what a new account looks like.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('role', sa.String(length=16), nullable=False, server_default='user')
        )
        batch_op.add_column(
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column(
                'must_change_password',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column('password_changed_at', app.core.types.UTCDateTime(), nullable=True)
        )

    op.execute(sa.text("UPDATE users SET role = 'admin'"))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('role', server_default=None)
        batch_op.alter_column('is_active', server_default=None)
        batch_op.alter_column('must_change_password', server_default=None)


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('password_changed_at')
        batch_op.drop_column('must_change_password')
        batch_op.drop_column('is_active')
        batch_op.drop_column('role')

    op.drop_table('user_people')

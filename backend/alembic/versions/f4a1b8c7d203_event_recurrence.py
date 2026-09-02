"""Record whether an imported event is one of a repeating series.

Every imported event now counts as an interview unless someone says otherwise,
which makes a weekly standup expensive: fifty-two of them would land in the
funnel. Knowing an event repeats lets the importer pre-mark it as not an
interview, so the default stays right for the events that matter.

Revision ID: f4a1b8c7d203
Revises: c92d2ecf7f9c
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f4a1b8c7d203"
down_revision = "c92d2ecf7f9c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A NOT NULL column cannot be added to a populated table without a default,
    # so give it one for the backfill and then drop it — the model supplies the
    # default for new rows.
    with op.batch_alter_table("calendar_events") as batch:
        batch.add_column(
            sa.Column(
                "is_recurring",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    with op.batch_alter_table("calendar_events") as batch:
        batch.alter_column("is_recurring", server_default=None)

    _backfill()


def _backfill() -> None:
    """Apply the new default to events that were imported under the old one.

    Without this, every standup and every all-day block already in the database
    becomes an interview the moment this ships — which is a worse first
    impression than the problem being fixed. The provider payload was kept on
    import, so the repeating ones can be recognised after the fact.

    Only untouched rows are moved. A classification someone chose by hand is
    left exactly as they left it.
    """
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        # json_extract is SQLite's spelling. On anything else the column simply
        # starts false and the next sync fills it in.
        return

    connection.execute(
        sa.text(
            """
            UPDATE calendar_events
            SET is_recurring = 1
            WHERE raw IS NOT NULL
              AND (
                json_extract(raw, '$.recurringEventId') IS NOT NULL
                OR json_extract(raw, '$.seriesMasterId') IS NOT NULL
                OR json_extract(raw, '$.type') IN ('occurrence', 'exception')
              )
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE calendar_events
            SET classification = 'normal_meeting'
            WHERE classification = 'unclassified'
              AND classification_locked = 0
              AND (is_recurring = 1 OR is_all_day = 1)
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("calendar_events") as batch:
        batch.drop_column("is_recurring")

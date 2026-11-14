"""Persist the local archive without modifying saved results."""

import sqlalchemy as sa
from alembic import op

revision = "0005_run_archive"
down_revision = "0004_hosted_claims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_runs_archived_at_id",
        "runs",
        ["archived_at", "id"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_runs_archived_at_id", table_name="runs")
    op.drop_column("runs", "archived_at")

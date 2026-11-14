"""Keep transferred packages out of the queue until explicitly started."""

import sqlalchemy as sa
from alembic import op

revision = "0006_prepared_upload"
down_revision = "0005_run_archive"
branch_labels = None
depends_on = None

_ACTIVE_STATES = "'queued', 'processing', 'completed', 'completed_with_issues', 'failed'"


def upgrade() -> None:
    op.add_column("runs", sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("runs_status_check", "runs", type_="check")
    op.create_check_constraint(
        "runs_status_check", "runs", f"status IN ('prepared', {_ACTIVE_STATES})"
    )
    op.create_index(
        "ix_runs_prepared_at",
        "runs",
        ["prepared_at"],
        postgresql_where=sa.text("status = 'prepared'"),
    )


def downgrade() -> None:
    pending = sa.text("SELECT EXISTS (SELECT 1 FROM runs WHERE status = 'prepared')")
    if op.get_bind().scalar(pending):
        raise RuntimeError("Discard prepared packages before downgrading the upload schema")
    op.drop_index("ix_runs_prepared_at", table_name="runs")
    op.drop_constraint("runs_status_check", "runs", type_="check")
    op.create_check_constraint("runs_status_check", "runs", f"status IN ({_ACTIVE_STATES})")
    op.drop_column("runs", "prepared_at")

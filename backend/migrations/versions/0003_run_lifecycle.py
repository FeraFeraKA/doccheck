"""Persist the timing, result and safe technical error of a document run."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_run_lifecycle"
down_revision = "0002_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("result", postgresql.JSONB(), nullable=True))
    op.add_column("runs", sa.Column("error", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    for column in ("error", "result", "finished_at", "started_at"):
        op.drop_column("runs", column)

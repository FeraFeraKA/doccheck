"""Synthetic lifecycle scaffold, separate from future document job storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_synthetic_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synthetic_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed')"),
        sa.CheckConstraint("synthetic = true"),
    )
    op.create_index("ix_synthetic_jobs_status", "synthetic_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_synthetic_jobs_status", table_name="synthetic_jobs")
    op.drop_table("synthetic_jobs")

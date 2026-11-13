"""Document runs, with an idempotency key and an immutable upload manifest."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_runs"
down_revision = "0001_synthetic_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False, unique=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scope", postgresql.JSONB(), nullable=False),
        sa.Column("documents", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'completed_with_issues', 'failed')"
        ),
    )


def downgrade() -> None:
    op.drop_table("runs")

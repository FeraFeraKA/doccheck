"""Add admission and lease state for the separate hosted synthetic queue."""

import sqlalchemy as sa
from alembic import op

revision = "0004_hosted_claims"
down_revision = "0003_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hosted_claims",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.Uuid(), unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("receipt", sa.String(64)),
        sa.Column("viewer_id", sa.Uuid()),
        sa.CheckConstraint("attempt BETWEEN 0 AND 3"),
    )
    op.create_index("ix_hosted_claims_viewer_id", "hosted_claims", ["viewer_id"])


def downgrade() -> None:
    op.drop_table("hosted_claims")

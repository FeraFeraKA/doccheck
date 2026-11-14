"""Associate runs submitted through the web gateway with their browser session."""

import sqlalchemy as sa
from alembic import op

revision = "0004_web_run_sessions"
down_revision = "0003_run_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("web_session_id", sa.Uuid(), nullable=True))
    op.create_index("ix_runs_web_session_id", "runs", ["web_session_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_web_session_id", table_name="runs")
    op.drop_column("runs", "web_session_id")

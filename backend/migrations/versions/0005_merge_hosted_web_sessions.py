"""Combine the hosted claims and local web-session migration histories."""

revision = "0005_merge_hosted_web_sessions"
down_revision = ("0004_hosted_claims", "0004_web_run_sessions")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

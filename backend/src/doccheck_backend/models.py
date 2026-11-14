from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SyntheticJob(Base):
    """Deliberately separate from future production document jobs and their result DTO."""

    __tablename__ = "synthetic_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'processing', 'completed', 'failed')"),
        CheckConstraint("synthetic = true"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'completed', 'completed_with_issues', 'failed')"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid, unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    # An empty object means the upload did not include a user-supplied scope.
    scope: Mapped[dict[str, object]] = mapped_column(JSONB)
    documents: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[dict[str, object] | None] = mapped_column(JSONB(none_as_null=True))


class HostedClaim(Base):
    """Admission and current attempt for the separately configured synthetic queue."""

    __tablename__ = "hosted_claims"
    __table_args__ = (CheckConstraint("attempt BETWEEN 0 AND 3"),)

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_id: Mapped[UUID | None] = mapped_column(Uuid, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt: Mapped[str | None] = mapped_column(String(64))

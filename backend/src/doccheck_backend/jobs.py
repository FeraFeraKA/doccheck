"""Short database transactions; no HTTP dependencies or processing under a row lock."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from doccheck_backend.models import SyntheticJob
from doccheck_backend.schemas import JobResponse, SyntheticResult


def create_job(engine: Engine) -> JobResponse:
    with Session(engine) as session, session.begin():
        job = SyntheticJob()
        session.add(job)
        session.flush()
        session.refresh(job)
        response = JobResponse.model_validate(job)
    return response


def get_job(engine: Engine, job_id: UUID) -> JobResponse | None:
    with Session(engine) as session:
        job = session.get(SyntheticJob, job_id)
        return JobResponse.model_validate(job) if job is not None else None


def claim_next_job(engine: Engine) -> UUID | None:
    with Session(engine) as session, session.begin():
        job = session.scalar(
            select(SyntheticJob)
            .where(SyntheticJob.status == "queued")
            .order_by(SyntheticJob.created_at, SyntheticJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        job_id = job.id
    return job_id


def finish_job(
    engine: Engine, job_id: UUID, *, result: SyntheticResult | None, error: str | None = None
) -> None:
    if (result is None) == (error is None):
        raise ValueError("A job must finish with either a result or an error")
    with Session(engine) as session, session.begin():
        job = session.get(SyntheticJob, job_id, with_for_update=True)
        if job is None or job.status != "processing":
            raise ValueError("Only a processing job can finish")
        job.result = result.model_dump() if result else None
        job.error = error
        job.finished_at = datetime.now(timezone.utc)
        job.status = "completed" if result is not None else "failed"

"""Worker lifecycle for saved document runs with an explicitly supplied processor."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import Connection, Engine, func, select, update
from sqlalchemy.orm import Session

from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Issue, Scope
from doccheck_backend.models import Run

logger = logging.getLogger(__name__)

_DOCUMENT_WORKER_LOCK = 0x446F6343
_INTERRUPTED = Issue(
    code="worker_interrupted",
    message="Обработка прервана. Запустите новую проверку.",
)
_PROCESSING_FAILED = Issue(code="processing_failed", message="Не удалось обработать пакет.")


@dataclass(frozen=True)
class StoredRun:
    id: UUID
    scope: dict[str, object]
    documents: list[dict[str, object]]


RunProcessor = Callable[[StoredRun, Path], CheckJob]


def run_document_worker(
    engine: Engine,
    upload_root: Path,
    process: RunProcessor,
    *,
    once: bool = False,
    poll_seconds: float = 0.5,
) -> bool:
    """Run the sequential queue with a supplied adapter. Return False if it is already owned."""
    with engine.connect() as connection:
        # Scope serialization to this schema and close the physical session on exit.
        connection.detach()
        with connection.begin():
            acquired = connection.scalar(
                select(
                    func.pg_try_advisory_lock(
                        _DOCUMENT_WORKER_LOCK, func.hashtext(func.current_schema())
                    )
                )
            )
            if not acquired:
                return False
            # No live owner of this queue can be processing once the lock is acquired.
            connection.execute(
                update(Run)
                .where(Run.status == "processing")
                .values(
                    status="failed",
                    result=None,
                    error=_INTERRUPTED.model_dump(mode="json"),
                    finished_at=func.now(),
                )
            )

        while True:
            run = _claim(connection)
            if run is not None:
                outcome = _process(run, upload_root, process)
                _finish(connection, run, outcome)
            if once:
                return True
            if run is None:
                time.sleep(poll_seconds)


def _claim(connection: Connection) -> StoredRun | None:
    with Session(connection) as session, session.begin():
        run = session.scalar(
            select(Run)
            .where(Run.status == "queued")
            .order_by(Run.created_at, Run.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if run is None:
            return None
        run.status = "processing"
        run.started_at = datetime.now(timezone.utc)
        return StoredRun(run.id, run.scope, run.documents)


def _process(run: StoredRun, upload_root: Path, process: RunProcessor) -> CheckJob:
    run_id = str(run.id)
    try:
        # Snapshot the identity before calling code that owns the processing step.
        scope = Scope.model_validate(run.scope)
        documents = {doc["id"]: doc["sha256"] for doc in run.documents}
        returned = process(run, upload_root / run_id)
        outcome = CheckJob.model_validate(returned.model_dump(mode="json"))
        if outcome.run_id != run_id or outcome.status in ("queued", "processing"):
            raise ValueError("processor must return a terminal outcome for the claimed run")
        if outcome.result is not None and (
            outcome.result.scope != scope
            or {doc.id: doc.sha256 for doc in outcome.result.documents} != documents
        ):
            raise ValueError("result must match the uploaded scope and document IDs")
        if outcome.error is not None:
            outcome.error = _PROCESSING_FAILED
        return outcome
    except Exception as exc:
        # Do not log exception text, document data or adapter payloads.
        logger.error("Document run %s: processing failed (%s)", run_id, type(exc).__name__)
        return CheckJob(run_id=run_id, status="failed", result=None, error=_PROCESSING_FAILED)


def _finish(connection: Connection, run: StoredRun, outcome: CheckJob) -> None:
    with Session(connection) as session, session.begin():
        row = session.get(Run, run.id, with_for_update=True)
        if row is None or row.status != "processing":
            raise ValueError("only a processing run can finish")
        row.status = outcome.status
        row.result = outcome.result.model_dump(mode="json") if outcome.result else None
        row.error = outcome.error.model_dump(mode="json") if outcome.error else None
        row.finished_at = datetime.now(timezone.utc)

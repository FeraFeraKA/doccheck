"""Worker lifecycle for saved document runs with an explicitly supplied processor."""

import argparse
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from uuid import UUID

from sqlalchemy import BigInteger, Connection, Engine, cast, func, select, update
from sqlalchemy.dialects.postgresql import OID, REGCLASS
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Issue, Scope
from doccheck_backend.database import create_database_engine
from doccheck_backend.models import Run

logger = logging.getLogger(__name__)

_DOCUMENT_WORKER_LOCK_NAMESPACE = 0x446F6343 << 32
_INTERRUPTED = Issue(
    code="worker_interrupted",
    message="Обработка прервана. Запустите новую проверку.",
)
_PROCESSING_FAILED = Issue(code="processing_failed", message="Не удалось обработать пакет.")
_PROCESSING_COMPLETED_WITH_ISSUES = Issue(
    code="processing_completed_with_issues",
    message="Результат сохранён. При обработке возникла техническая ошибка.",
)


class WorkerSessionLost(RuntimeError):
    """The PostgreSQL session that owned the document queue is no longer available."""


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
        # Closing the physical session on exit releases the advisory lock.
        connection.detach()
        owner = connection.connection.dbapi_connection
        with connection.begin():
            # Resolve the same relation as the unqualified ORM queries, including search_path.
            runs_oid = cast(cast(cast(Run.__tablename__, REGCLASS), OID), BigInteger)
            acquired = connection.scalar(
                select(func.pg_try_advisory_lock(_DOCUMENT_WORKER_LOCK_NAMESPACE + runs_oid))
            )
            if not acquired:
                return False
            # Any previous processing row has lost its owning PostgreSQL session.
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
                # SQLAlchemy can reconnect an invalidated Connection. Its next physical
                # session would not own the lock. Leave recovery to the next owner.
                if connection.invalidated or connection.connection.dbapi_connection is not owner:
                    raise WorkerSessionLost
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
            outcome.error = (
                _PROCESSING_FAILED
                if outcome.status == "failed"
                else _PROCESSING_COMPLETED_WITH_ISSUES
            )
        if outcome.result is not None:
            _validate_jsonb_text(outcome.result.model_dump(mode="json"))
        return outcome
    except Exception as exc:
        # Do not log exception text, document data or adapter payloads.
        logger.error("Document run %s: processing failed (%s)", run_id, type(exc).__name__)
        return CheckJob(run_id=run_id, status="failed", result=None, error=_PROCESSING_FAILED)


def _validate_jsonb_text(value: object) -> None:
    """Reject text PostgreSQL JSONB cannot store in the UTF-8 application database."""
    if isinstance(value, str):
        value.encode("utf-8")
        if "\x00" in value:
            raise ValueError("JSONB strings cannot contain NUL")
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_jsonb_text(key)
            _validate_jsonb_text(item)
    elif isinstance(value, list):
        for item in value:
            _validate_jsonb_text(item)


def _finish(connection: Connection, run: StoredRun, outcome: CheckJob) -> None:
    with Session(connection) as session, session.begin():
        row = session.get(Run, run.id, with_for_update=True)
        if row is None or row.status != "processing":
            raise ValueError("only a processing run can finish")
        row.status = outcome.status
        row.result = outcome.result.model_dump(mode="json") if outcome.result else None
        row.error = outcome.error.model_dump(mode="json") if outcome.error else None
        row.finished_at = datetime.now(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--processor", required=True, help="Trusted local adapter as module:callable"
    )
    parser.add_argument("--once", action="store_true", help="Process at most one run and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    module, separator, name = args.processor.partition(":")
    if (
        not separator
        or not name.isidentifier()
        or not all(part.isidentifier() for part in module.split("."))
    ):
        parser.error("--processor must have the form module:callable")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    try:
        process = getattr(import_module(module), name)
    except Exception:
        logger.error("Configured document processor could not be loaded")
        return 1
    if not callable(process):
        logger.error("Configured document processor must be callable")
        return 1

    engine = create_database_engine(settings.database_url)
    try:
        owned = run_document_worker(
            engine,
            settings.upload_root,
            process,
            once=args.once,
            poll_seconds=settings.worker_poll_seconds,
        )
        if not owned:
            logger.error("Another document worker owns this queue")
            return 1
        return 0
    except KeyboardInterrupt:
        return 0
    except (SQLAlchemyError, WorkerSessionLost):
        logger.error("Database operation failed; document worker stopped")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

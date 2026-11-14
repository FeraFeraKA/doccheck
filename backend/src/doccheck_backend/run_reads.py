"""Read saved runs and resolve sources within an individual upload manifest."""

import json
import re
from base64 import b64decode, urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import file_digest, sha256
from io import BytesIO
from os import fstat, stat_result
from os.path import samestat
from pathlib import Path
from stat import S_ISREG
from typing import BinaryIO
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, select, tuple_
from sqlalchemy.orm import Session, defer

from doccheck_backend.contracts import CheckResult
from doccheck_backend.contracts.result import Evidence, Issue, JobStatus
from doccheck_backend.fragment_preview import MAX_INPUT_BYTES, FragmentPreview, render_preview
from doccheck_backend.models import Run

_STORED_FILE_ID = re.compile(r"[0-9a-f]{32}")
_URL_ID = re.compile(r"[A-Za-z0-9_-]+")
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,160}")


class RunReadError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.field = field


class RunSummary(BaseModel):
    run_id: UUID
    status: JobStatus
    created_at: datetime
    error: Issue | None


class RunProgress(BaseModel):
    processed_documents: int
    total_documents: int


class RunState(RunSummary):
    progress: RunProgress | None


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


def unavailable() -> RunReadError:
    return RunReadError(503, "service_unavailable", "Хранилище проверок недоступно")


def list_runs(
    engine: Engine, limit: int, cursor: str | None, *, web_session: UUID | None = None
) -> RunPage:
    query = select(Run.id, Run.status, Run.created_at, Run.error)
    if web_session is not None:
        query = query.where(Run.web_session_id == web_session)
    if cursor is not None:
        query = query.where(tuple_(Run.created_at, Run.id) < _decode_cursor(cursor))
    query = query.order_by(Run.created_at.desc(), Run.id.desc()).limit(limit + 1)
    with Session(engine) as session:
        items = [
            RunSummary(run_id=run_id, status=status, created_at=created_at, error=error)
            for run_id, status, created_at, error in session.execute(query)
        ]
    if len(items) <= limit:
        return RunPage(items=items, next_cursor=None)
    last = items[limit - 1]
    position = json.dumps([last.created_at.isoformat(), str(last.run_id)]).encode("ascii")
    token = urlsafe_b64encode(position).decode("ascii").rstrip("=")
    return RunPage(items=items[:limit], next_cursor=token)


def _decode_cursor(token: str) -> tuple[datetime, UUID]:
    try:
        if not _CURSOR.fullmatch(token):
            raise ValueError
        payload = b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        value = json.loads(payload)
        if (
            not isinstance(value, list)
            or len(value) != 2
            or not all(isinstance(item, str) for item in value)
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(value[0])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(UTC), UUID(value[1])
    except (ValueError, OverflowError):
        raise RunReadError(422, "invalid_input", "Некорректный курсор", "cursor") from None


def _load_run(
    engine: Engine, run_id: str, *, with_result: bool = False, web_session: UUID | None = None
) -> Run:
    try:
        if not _URL_ID.fullmatch(run_id):
            raise ValueError
        key = UUID(run_id)
    except ValueError:
        raise RunReadError(404, "run_not_found", "Проверка не найдена") from None
    with Session(engine) as session:
        options = () if with_result else (defer(Run.result, raiseload=True),)
        run = session.get(Run, key, options=options)
    if run is None or (web_session is not None and run.web_session_id != web_session):
        raise RunReadError(404, "run_not_found", "Проверка не найдена")
    return run


def get_run_state(engine: Engine, run_id: str, *, web_session: UUID | None = None) -> RunState:
    run = _load_run(engine, run_id, web_session=web_session)
    total = len(run.documents)
    progress = None
    if run.status == "queued":
        progress = RunProgress(processed_documents=0, total_documents=total)
    elif run.status in ("completed", "completed_with_issues"):
        progress = RunProgress(processed_documents=total, total_documents=total)
    return RunState(
        run_id=run.id,
        status=run.status,
        created_at=run.created_at,
        error=run.error,
        progress=progress,
    )


def _stored_result(run: Run) -> CheckResult:
    if run.status in ("queued", "processing"):
        raise RunReadError(409, "result_pending", "Проверка ещё не завершена")
    if run.status == "failed":
        raise RunReadError(409, "run_failed", "Проверка завершилась без результата")
    try:
        result = CheckResult.model_validate(run.result)
    except ValidationError:
        raise unavailable() from None
    if result.run_id != str(run.id):
        raise unavailable()
    return result


def get_run_findings(
    engine: Engine, run_id: str, *, web_session: UUID | None = None
) -> CheckResult:
    return _stored_result(_load_run(engine, run_id, with_result=True, web_session=web_session))


def _document_not_found() -> RunReadError:
    return RunReadError(404, "document_not_found", "Документ проверки недоступен")


def _fragment_not_found() -> RunReadError:
    return RunReadError(404, "fragment_not_found", "Фрагмент документа не найден")


def _stored_document(run: Run, document_id: str) -> dict[str, object]:
    if _STORED_FILE_ID.fullmatch(document_id):
        for document in run.documents:
            if document.get("id") == document_id:
                return document
    raise _document_not_found()


def _document_path(root: Path, run_id: UUID, document_id: str) -> tuple[Path, stat_result]:
    try:
        path = root.resolve(strict=True) / str(run_id) / document_id
        # Only regular files at the original storage location may be downloaded.
        if path.resolve(strict=True) != path:
            raise _document_not_found()
        info = path.stat()
        if not S_ISREG(info.st_mode):
            raise _document_not_found()
    except (FileNotFoundError, NotADirectoryError, PermissionError, RuntimeError):
        raise _document_not_found() from None
    except OSError:
        raise unavailable() from None
    return path, info


def open_run_original(
    root: Path, run_id: UUID, document_id: str, document: dict[str, object]
) -> tuple[BinaryIO, int]:
    path, expected = _document_path(root, run_id, document_id)
    try:
        stream = path.open("rb")
    except (FileNotFoundError, NotADirectoryError, PermissionError, IsADirectoryError):
        raise _document_not_found() from None
    except OSError:
        raise unavailable() from None
    try:
        # Stream the opened file, never reopen a path after validating it.
        actual = fstat(stream.fileno())
        _, current = _document_path(root, run_id, document_id)
        if not samestat(expected, actual) or not samestat(current, actual):
            raise _document_not_found()
        if actual.st_size != document["size"]:
            raise _document_not_found()
        if file_digest(stream, "sha256").hexdigest() != document["sha256"]:
            raise _document_not_found()
        after = fstat(stream.fileno())
        if after.st_size != actual.st_size or after.st_mtime_ns != actual.st_mtime_ns:
            raise _document_not_found()
        stream.seek(0)
    except OSError:
        stream.close()
        raise unavailable() from None
    except RunReadError:
        stream.close()
        raise
    return stream, actual.st_size


def get_run_document(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    *,
    web_session: UUID | None = None,
) -> tuple[BinaryIO, int, str]:
    run = _load_run(engine, run_id, web_session=web_session)
    document = _stored_document(run, document_id)
    name = str(document["name"]).replace("\\", "/").rsplit("/", 1)[-1]
    safe_name = "".join(char for char in name if char.isprintable()).strip(" .") or document_id
    stream, size = open_run_original(root, run.id, document_id, document)
    return stream, size, safe_name


def get_run_fragment(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    evidence_id: str,
    *,
    path_segment: bool = False,
    web_session: UUID | None = None,
) -> Evidence:
    evidence, stream, _, _ = _open_fragment(
        engine, root, run_id, document_id, evidence_id,
        path_segment=path_segment, web_session=web_session
    )
    stream.close()
    return evidence


def get_run_fragment_preview(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    evidence_id: str,
    *,
    web_session: UUID | None = None,
) -> FragmentPreview:
    evidence, stream, size, document = _open_fragment(
        engine, root, run_id, document_id, evidence_id, web_session=web_session
    )
    with stream:
        if size > MAX_INPUT_BYTES:
            return FragmentPreview(text=None, highlight=None)
        try:
            content = stream.read(size + 1)
        except OSError:
            raise unavailable() from None
    # The parser and the hash must see the same bytes, even if the on-disk
    # file is rewritten in place after _open_original verifies it.
    if len(content) != size or sha256(content).hexdigest() != document["sha256"]:
        raise _document_not_found()
    return render_preview(BytesIO(content), document.get("format"), evidence)


def _open_fragment(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    evidence_id: str,
    *,
    path_segment: bool = False,
    web_session: UUID | None = None,
) -> tuple[Evidence, BinaryIO, int, dict[str, object]]:
    run = _load_run(engine, run_id, with_result=True, web_session=web_session)
    document = _stored_document(run, document_id)
    result = _stored_result(run)
    # Intermediaries can normalize separators and dot segments in request paths.
    if path_segment and ("/" in evidence_id or "\\" in evidence_id or evidence_id in (".", "..")):
        raise _fragment_not_found()
    for evidence in result.evidence:
        if evidence.id == evidence_id and evidence.document_id == document_id:
            stream, size = open_run_original(root, run.id, document_id, document)
            return evidence, stream, size, document
    raise _fragment_not_found()

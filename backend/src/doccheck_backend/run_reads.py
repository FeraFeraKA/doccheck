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
from typing import BinaryIO, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import Engine, and_, cast, func, select, tuple_, type_coerce
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import Session, defer
from sqlalchemy.sql import ColumnElement

from doccheck_backend.contracts import CheckResult
from doccheck_backend.contracts.result import Evidence, Issue, JobStatus, RubCoverage, StatusCounts
from doccheck_backend.document_preview import (
    MAX_PREVIEW_BYTES,
    PREVIEW_ERRORS,
    SheetPreview,
    WordPreview,
    pdf_page_preview,
    sheet_preview,
    word_preview,
)
from doccheck_backend.fragment_preview import MAX_INPUT_BYTES, FragmentPreview, render_preview
from doccheck_backend.models import Run
from doccheck_backend.result_summary import build_rub_coverage

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
    archived_at: datetime | None = None
    synthetic: bool = False
    report_name: str | None = None
    report_number: str | None = None


class HistoryRun(RunSummary):
    counts: StatusCounts | None = None
    rub_coverage: RubCoverage | None = None
    report_name: str | None = None
    report_number: str | None = None
    synthetic: bool | None = None
    document_count: int
    contract_number: str | None = None
    archived_at: datetime | None = None


FindingFilter = Literal["discrepancy", "unverified", "verified"]
RunView = Literal["active", "archive"]


class ArchiveState(BaseModel):
    archived_at: datetime | None


class RunPage(BaseModel):
    items: list[HistoryRun]
    next_cursor: str | None


def _report_document() -> ColumnElement[dict[str, object]]:
    return type_coerce(
        func.jsonb_path_query_first(Run.documents, cast('$[*] ? (@.role == "report")', JSONPATH)),
        JSONB,
    )


def unavailable() -> RunReadError:
    return RunReadError(503, "service_unavailable", "Хранилище проверок недоступно")


def list_runs(
    engine: Engine,
    limit: int,
    cursor: str | None,
    finding: FindingFilter | None = None,
    view: RunView = "active",
) -> RunPage:
    counts = Run.result["summary"]["counts"]
    report = _report_document()
    archive = view == "archive"
    sort_date = Run.archived_at if archive else Run.created_at
    columns = (
        Run.id,
        Run.status,
        Run.created_at,
        Run.error,
        counts,
        Run.result["report_number"].as_string(),
        Run.result["synthetic"].as_boolean(),
        report["synthetic"].as_boolean(),
        func.jsonb_array_length(Run.documents),
        Run.result["scope"]["contract_number"].as_string(),
        Run.archived_at,
        report["name"].as_string(),
        Run.result,
    )
    query = select(*columns).where(
        Run.archived_at.is_not(None) if archive else Run.archived_at.is_(None),
        Run.status != "prepared",
    )
    if finding is not None:
        query = query.where(Run.status.in_(("completed", "completed_with_issues")))
        if finding == "verified":
            query = query.where(
                and_(
                    counts["verified"].as_integer() > 0,
                    counts["discrepancy"].as_integer() == 0,
                    counts["unverified"].as_integer() == 0,
                )
            )
        else:
            query = query.where(counts[finding].as_integer() > 0)
    if cursor is not None:
        query = query.where(tuple_(sort_date, Run.id) < _decode_cursor(cursor))
    query = query.order_by(sort_date.desc(), Run.id.desc()).limit(limit + 1)
    with Session(engine) as session:
        page = session.execute(query).all()
    items = []
    for (
        run_id,
        status,
        created_at,
        error,
        row_counts,
        number,
        synthetic,
        demo,
        document_count,
        contract_number,
        archived_at,
        report_name,
        result_payload,
    ) in page[:limit]:
        item = HistoryRun(
            run_id=run_id,
            status=status,
            created_at=created_at,
            error=error,
            document_count=document_count,
        )
        if archived_at is not None:
            item.archived_at = archived_at
        if report_name:
            item.report_name = report_name
        if demo is True:
            item.synthetic = True
        if contract_number is not None:
            item.contract_number = contract_number
        if status in ("completed", "completed_with_issues") and row_counts is not None:
            item.counts = StatusCounts.model_validate(row_counts)
            item.report_number = number
            result = _validated_result(run_id, result_payload)
            if result is not None:
                item.rub_coverage = build_rub_coverage(result)
            if synthetic is not None:
                item.synthetic = synthetic or demo is True
        items.append(item)
    if len(page) <= limit:
        return RunPage(items=items, next_cursor=None)
    last = items[-1]
    moment = last.archived_at if archive else last.created_at
    assert moment is not None
    position = json.dumps([moment.isoformat(), str(last.run_id)]).encode("ascii")
    token = urlsafe_b64encode(position).decode("ascii").rstrip("=")
    return RunPage(items=items, next_cursor=token)


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


def _run_key(run_id: str) -> UUID:
    try:
        if not _URL_ID.fullmatch(run_id):
            raise ValueError
        return UUID(run_id)
    except ValueError:
        raise RunReadError(404, "run_not_found", "Проверка не найдена") from None


def _load_run(engine: Engine, run_id: str, *, with_result: bool = False) -> Run:
    key = _run_key(run_id)
    with Session(engine) as session:
        options = () if with_result else (defer(Run.result, raiseload=True),)
        run = session.get(Run, key, options=options)
    if run is None or run.status == "prepared":
        raise RunReadError(404, "run_not_found", "Проверка не найдена")
    return run


def get_editable_run(engine: Engine, run_id: str) -> Run:
    run = _load_run(engine, run_id)
    if run.status not in ("completed", "completed_with_issues"):
        raise RunReadError(409, "result_pending", "Дождитесь завершения исходной проверки")
    return run


def get_run_state(engine: Engine, run_id: str) -> RunState:
    key = _run_key(run_id)
    totals = func.jsonb_array_length(Run.documents)
    report = _report_document()
    with Session(engine) as session:
        run = session.execute(
            select(
                Run.id,
                Run.status,
                Run.created_at,
                Run.error,
                Run.archived_at,
                totals.label("document_count"),
                report["synthetic"].as_boolean().label("synthetic_package"),
                Run.result["synthetic"].as_boolean().label("synthetic_result"),
                report["name"].as_string().label("report_name"),
                Run.result["report_number"].as_string().label("report_number"),
            ).where(Run.id == key, Run.status != "prepared")
        ).one_or_none()
    if run is None:
        raise RunReadError(404, "run_not_found", "Проверка не найдена")
    total = run.document_count
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
        archived_at=run.archived_at.astimezone(UTC) if run.archived_at is not None else None,
        synthetic=run.synthetic_package is True or run.synthetic_result is True,
        report_name=run.report_name,
        report_number=run.report_number,
    )


def _stored_result(run: Run) -> CheckResult:
    if run.status in ("queued", "processing"):
        raise RunReadError(409, "result_pending", "Проверка ещё не завершена")
    if run.status == "failed":
        raise RunReadError(409, "run_failed", "Проверка завершилась без результата")
    result = _validated_result(run.id, run.result)
    if result is None:
        raise unavailable()
    return result


def _validated_result(run_id: UUID, payload: object) -> CheckResult | None:
    try:
        result = CheckResult.model_validate(payload)
    except ValidationError:
        return None
    return result if result.run_id == str(run_id) else None


def get_run_findings(engine: Engine, run_id: str) -> CheckResult:
    return _stored_result(_load_run(engine, run_id, with_result=True))


def set_run_archive(engine: Engine, run_id: str, archived: bool) -> ArchiveState:
    with Session(engine) as session, session.begin():
        run = session.get(Run, _run_key(run_id), with_for_update=True)
        if run is None or run.status == "prepared":
            raise RunReadError(404, "run_not_found", "Проверка не найдена")
        if archived:
            _stored_result(run)
            if run.archived_at is None:
                run.archived_at = datetime.now(UTC)
        else:
            run.archived_at = None
        return ArchiveState(
            archived_at=run.archived_at.astimezone(UTC) if run.archived_at is not None else None,
        )


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


def _open_original(
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
    engine: Engine, root: Path, run_id: str, document_id: str
) -> tuple[BinaryIO, int, str]:
    run = _load_run(engine, run_id)
    document = _stored_document(run, document_id)
    name = str(document["name"]).replace("\\", "/").rsplit("/", 1)[-1]
    safe_name = "".join(char for char in name if char.isprintable()).strip(" .") or document_id
    stream, size = _open_original(root, run.id, document_id, document)
    return stream, size, safe_name


def get_document_preview(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    *,
    sheet: str | None,
    row: int,
    column: int,
) -> SheetPreview | WordPreview:
    file_format, data = _preview_original(engine, root, run_id, document_id)
    try:
        if file_format == "xlsx":
            return sheet_preview(data, sheet, row, column)
        if file_format == "docx":
            return word_preview(data)
    except (KeyError, *PREVIEW_ERRORS):
        raise RunReadError(422, "preview_unavailable", "Не удалось прочитать документ") from None
    raise RunReadError(415, "preview_unavailable", "Этот формат не имеет офисного предпросмотра")


def get_document_pdf_page(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    page: int,
) -> tuple[bytes, int]:
    file_format, data = _preview_original(engine, root, run_id, document_id)
    if file_format != "pdf":
        raise RunReadError(415, "preview_unavailable", "Документ не является PDF")
    try:
        return pdf_page_preview(data, page)
    except IndexError:
        raise RunReadError(404, "page_not_found", "Страница PDF не найдена") from None
    except PREVIEW_ERRORS:
        raise RunReadError(422, "preview_unavailable", "Не удалось открыть страницу PDF") from None


def _preview_original(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
) -> tuple[object, bytes]:
    run = _load_run(engine, run_id)
    document = _stored_document(run, document_id)
    if document["size"] > MAX_PREVIEW_BYTES:
        raise RunReadError(413, "preview_unavailable", "Файл слишком большой для предпросмотра")
    stream, size = _open_original(root, run.id, document_id, document)
    return document.get("format"), _read_verified_original(stream, size, document)


def _read_verified_original(stream: BinaryIO, size: int, document: dict[str, object]) -> bytes:
    with stream:
        try:
            content = stream.read(size + 1)
        except OSError:
            raise unavailable() from None
    if len(content) != size or sha256(content).hexdigest() != document["sha256"]:
        raise _document_not_found()
    return content


def get_run_fragment(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    evidence_id: str,
    *,
    path_segment: bool = False,
) -> Evidence:
    evidence, stream, _, _ = _open_fragment(
        engine, root, run_id, document_id, evidence_id, path_segment=path_segment
    )
    stream.close()
    return evidence


def get_run_fragment_preview(
    engine: Engine, root: Path, run_id: str, document_id: str, evidence_id: str
) -> FragmentPreview:
    evidence, stream, size, document = _open_fragment(
        engine, root, run_id, document_id, evidence_id
    )
    if size > MAX_INPUT_BYTES:
        stream.close()
        return FragmentPreview(text=None, highlight=None)
    # Verify the exact bytes supplied to the parser.
    content = _read_verified_original(stream, size, document)
    return render_preview(BytesIO(content), document.get("format"), evidence)


def _open_fragment(
    engine: Engine,
    root: Path,
    run_id: str,
    document_id: str,
    evidence_id: str,
    *,
    path_segment: bool = False,
) -> tuple[Evidence, BinaryIO, int, dict[str, object]]:
    run = _load_run(engine, run_id, with_result=True)
    document = _stored_document(run, document_id)
    result = _stored_result(run)
    # Intermediaries can normalize separators and dot segments in request paths.
    if path_segment and ("/" in evidence_id or "\\" in evidence_id or evidence_id in (".", "..")):
        raise _fragment_not_found()
    for evidence in result.evidence:
        if evidence.id == evidence_id and evidence.document_id == document_id:
            stream, size = _open_original(root, run.id, document_id, document)
            return evidence, stream, size, document
    raise _fragment_not_found()

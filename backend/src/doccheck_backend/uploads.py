"""Validate and store uploads before making the run visible to a worker."""

import json
import os
from hashlib import sha256
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from starlette.datastructures import FormData, UploadFile

from doccheck_backend.contracts.locators import Locator
from doccheck_backend.contracts.result import Scope
from doccheck_backend.models import Run

MAX_FILE_SIZE = 50 * 1024**2
MAX_PACKAGE_SIZE = 250 * 1024**2
MAX_MULTIPART_SIZE = MAX_PACKAGE_SIZE + 2 * 1024**2
MAX_DOCUMENTS = 100
SCOPE_FIELDS = {"contract_number", "period_start", "period_end", "report_row_locator"}
LOCATOR_KINDS = {
    "pdf": {"page"},
    "png": {"page"},
    "xlsx": {"sheet"},
    "docx": {"table_cell", "paragraph"},
}
locator_adapter = TypeAdapter(Locator)


class UploadError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.field = field


def input_error(message: str, field: str | None = None) -> UploadError:
    return UploadError(422, "invalid_input", message, field)


def size_error() -> UploadError:
    return UploadError(413, "upload_too_large", "Превышен предел размера загрузки")


def _file_format(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower().removeprefix(".")
    prefix = upload.file.read(8)
    upload.file.seek(0)
    if suffix == "pdf" and prefix.startswith(b"%PDF-"):
        return suffix
    if suffix == "png" and prefix == b"\x89PNG\r\n\x1a\n":
        return suffix
    if suffix in ("xlsx", "docx") and prefix.startswith(b"PK\x03\x04"):
        required_member = {"xlsx": "xl/workbook.xml", "docx": "word/document.xml"}[suffix]
        try:
            with ZipFile(upload.file) as archive:
                if required_member in archive.namelist():
                    return suffix
        except BadZipFile:
            # A damaged OOXML file may still belong to the declared format.
            return suffix
        finally:
            upload.file.seek(0)
    raise UploadError(422, "unsupported_file_format", "Формат файла не поддерживается")


def _get_files(form: FormData, field: str, maximum: int) -> list[UploadFile]:
    files: list[UploadFile] = []
    for item in form.getlist(field):
        if not isinstance(item, UploadFile) or not item.filename:
            raise input_error("Ожидается файл", field)
        if item.size is None or item.size == 0:
            raise input_error("Файл пуст", field)
        if item.size > MAX_FILE_SIZE:
            raise size_error()
        files.append(item)
    if not 1 <= len(files) <= maximum:
        raise input_error("Недопустимое количество файлов", field)
    return files


def _parse_scope(form: FormData, report_id: str, report_format: str) -> Scope:
    values: dict[str, str] = {}
    for field in SCOPE_FIELDS:
        parts = form.getlist(field)
        if len(parts) != 1 or not isinstance(parts[0], str) or not parts[0].strip():
            raise input_error("Ожидается одно непустое значение", field)
        values[field] = parts[0]
    try:
        locator = locator_adapter.validate_json(values["report_row_locator"])
    except ValidationError:
        raise input_error("Некорректный адрес строки КФЗ", "report_row_locator") from None
    if locator.kind not in LOCATOR_KINDS[report_format]:
        raise input_error("Адрес не соответствует формату КФЗ", "report_row_locator")
    try:
        return Scope(
            report_document_id=report_id,
            contract_number=values["contract_number"],
            period_start=values["period_start"],
            period_end=values["period_end"],
            report_row_locator=locator,
        )
    except ValidationError:
        raise input_error("Некорректный договор или период") from None


def _save_file(upload: UploadFile, path: Path) -> str:
    digest = sha256()
    with path.open("xb") as target:
        while chunk := upload.file.read(1024**2):
            target.write(chunk)
            digest.update(chunk)
        target.flush()
        os.fsync(target.fileno())
    return digest.hexdigest()


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def store_run(engine: Engine, root: Path, key: UUID, form: FormData) -> UUID:
    if set(form) - (SCOPE_FIELDS | {"report", "documents"}):
        raise input_error("Неизвестное поле")
    (report,) = _get_files(form, "report", 1)
    uploads = [report, *_get_files(form, "documents", MAX_DOCUMENTS)]
    if sum(upload.size or 0 for upload in uploads) > MAX_PACKAGE_SIZE:
        raise size_error()
    formats = [_file_format(upload) for upload in uploads]
    ids = [uuid4().hex for _ in uploads]
    scope = _parse_scope(form, ids[0], formats[0])
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".upload-", dir=root))
    try:
        documents = [
            {
                "id": file_id,
                "name": upload.filename,
                "format": file_format,
                "size": upload.size,
                "sha256": _save_file(upload, staging / file_id),
                "role": "report" if index == 0 else "supporting",
            }
            for index, (upload, file_id, file_format) in enumerate(
                zip(uploads, ids, formats, strict=True)
            )
        ]
        fingerprint = {
            "scope": scope.model_dump(mode="json", exclude={"report_document_id"}),
            "files": [[doc["name"], doc["sha256"]] for doc in documents],
        }
        digest = sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        run_id = uuid4()
        with engine.begin() as connection:
            query = (
                insert(Run)
                .values(
                    id=run_id,
                    idempotency_key=key,
                    request_digest=digest,
                    status="queued",
                    scope=scope.model_dump(mode="json"),
                    documents=documents,
                )
                .on_conflict_do_nothing(index_elements=[Run.idempotency_key])
                .returning(Run.id)
            )
            if connection.execute(query).scalar_one_or_none() is None:
                existing, existing_digest = connection.execute(
                    select(Run.id, Run.request_digest).where(Run.idempotency_key == key)
                ).one()
                if existing_digest != digest:
                    raise UploadError(
                        409, "idempotency_conflict", "Ключ уже связан с другим пакетом"
                    )
                return existing
            _sync_directory(staging)
            staging.rename(root / str(run_id))
            # An uncertain commit must not delete bytes that a committed run can reference.
            try:
                _sync_directory(root)
            except OSError:
                rmtree(root / str(run_id))
                raise
        return run_id
    finally:
        if staging.exists():
            rmtree(staging)

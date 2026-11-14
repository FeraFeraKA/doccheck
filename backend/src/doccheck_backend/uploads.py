"""Validate and store uploads before making the run visible to a worker."""

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import file_digest, sha256
from pathlib import Path
from shutil import rmtree
from stat import S_ISREG
from tempfile import TemporaryDirectory, mkdtemp
from typing import BinaryIO
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from starlette.datastructures import FormData, UploadFile

from doccheck_backend import run_reads
from doccheck_backend.contracts.locators import Locator
from doccheck_backend.contracts.result import Scope
from doccheck_backend.models import HostedClaim, Run

MAX_FILE_SIZE = 50 * 1024**2
MAX_PACKAGE_SIZE = 250 * 1024**2
MAX_MULTIPART_SIZE = MAX_PACKAGE_SIZE + 2 * 1024**2
MAX_DOCUMENTS = 100
_PREPARED_TTL = timedelta(hours=1)
# The bundled browser example contains two generated inputs, without a stored result.
_DEMO_INPUT_DIGESTS = (
    "4361e7581119c2416e983f21c672ac64deabca9bd94ed4076f22b60a73c2e8ee",
    "a5b65780bb835cedc83f59bd57d529a69c35b6a37a42ae99338fd86ec8637812",
)
SCOPE_FIELDS = ("contract_number", "period_start", "period_end", "report_row_locator")
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
        except (BadZipFile, NotImplementedError, UnicodeDecodeError):
            # Preserve unreadable OOXML for file-level processing.
            return suffix
        finally:
            upload.file.seek(0)
    raise UploadError(422, "unsupported_file_format", "Формат файла не поддерживается")


def _get_files(form: FormData, field: str, maximum: int, *, minimum: int = 1) -> list[UploadFile]:
    files: list[UploadFile] = []
    for item in form.getlist(field):
        if not isinstance(item, UploadFile) or not item.filename:
            raise input_error("Ожидается файл", field)
        if "\x00" in item.filename:
            raise input_error("Недопустимый символ в имени файла", field)
        if item.size is None or item.size == 0:
            raise input_error("Файл пуст", field)
        if item.size > MAX_FILE_SIZE:
            raise size_error()
        files.append(item)
    if not minimum <= len(files) <= maximum:
        raise input_error("Недопустимое количество файлов", field)
    return files


def _parse_scope(form: FormData, report_id: str, report_format: str) -> Scope:
    values: dict[str, str] = {}
    for field in SCOPE_FIELDS:
        parts = form.getlist(field)
        if len(parts) != 1 or not isinstance(parts[0], str) or not parts[0].strip():
            raise input_error("Ожидается одно непустое значение", field)
        if "\x00" in parts[0]:
            raise input_error("Недопустимый символ в значении поля", field)
        values[field] = parts[0]
    try:
        locator = locator_adapter.validate_json(values["report_row_locator"])
    except ValidationError:
        raise input_error("Некорректный адрес строки КФЗ", "report_row_locator") from None
    if any(isinstance(value, str) and "\x00" in value for value in locator.model_dump().values()):
        raise input_error("Недопустимый символ в адресе строки КФЗ", "report_row_locator")
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


def _copy_file(source: BinaryIO, path: Path) -> str:
    digest = sha256()
    with path.open("xb") as target:
        while chunk := source.read(1024**2):
            target.write(chunk)
            digest.update(chunk)
        target.flush()
        os.fsync(target.fileno())
    return digest.hexdigest()


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        # Windows does not expose POSIX directory fsync. File contents are still flushed.
        return
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class _PackFile:
    role: str
    name: str
    size: int
    format: str
    upload: UploadFile | None = None
    source_id: UUID | None = None
    original: dict | None = None


def _new_pack_file(upload: UploadFile, role: str) -> _PackFile:
    return _PackFile(role, upload.filename or "", upload.size or 0, _file_format(upload), upload)


def _pack_files(engine: Engine, form: FormData) -> tuple[list[_PackFile], bool]:
    source_ids = form.getlist("source_run_id")
    retained_ids = form.getlist("retained_document_id")
    retains_synthetic = False
    if source_ids:
        if len(source_ids) != 1 or not isinstance(source_ids[0], str):
            raise input_error("Некорректная исходная проверка", "source_run_id")
        source = run_reads.get_editable_run(engine, source_ids[0])
        if len(retained_ids) > MAX_DOCUMENTS + 1 or not all(
            isinstance(item, str) for item in retained_ids
        ):
            raise input_error("Некорректный список сохранённых файлов", "retained_document_id")
        if len(set(retained_ids)) != len(retained_ids):
            raise input_error("Файл указан повторно", "retained_document_id")
        retained = [run_reads._stored_document(source, document_id) for document_id in retained_ids]
        retains_synthetic = bool(retained) and any(
            document.get("synthetic") is True for document in source.documents
        )
        originals = [
            _PackFile(
                str(item["role"]),
                str(item["name"]),
                int(item["size"]),
                str(item["format"]),
                source_id=source.id,
                original=item,
            )
            for item in retained
        ]
    elif retained_ids:
        raise input_error("Укажите исходную проверку", "source_run_id")
    else:
        originals = []

    reports = [_new_pack_file(item, "report") for item in _get_files(form, "report", 1, minimum=0)]
    documents = [
        _new_pack_file(item, "supporting")
        for item in _get_files(form, "documents", MAX_DOCUMENTS, minimum=0)
    ]
    reports += [original for original in originals if original.role == "report"]
    documents = [original for original in originals if original.role == "supporting"] + documents
    if len(reports) != 1:
        raise input_error("Выберите один файл КФЗ", "report")
    if not 1 <= len(documents) <= MAX_DOCUMENTS:
        raise input_error("Недопустимое количество файлов", "documents")
    files = [*reports, *documents]
    if any(file.size <= 0 or file.size > MAX_FILE_SIZE for file in files):
        raise size_error()
    if sum(file.size for file in files) > MAX_PACKAGE_SIZE:
        raise size_error()
    return files, retains_synthetic


def _store_pack_file(root: Path, item: _PackFile, destination: Path) -> str:
    if item.upload is not None:
        return _copy_file(item.upload.file, destination)
    if item.source_id is None or item.original is None:
        raise ValueError("Retained file must reference a saved original")
    stream, _ = run_reads.open_run_original(
        root, item.source_id, str(item.original["id"]), item.original
    )
    with stream:
        digest = _copy_file(stream, destination)
    if digest != item.original["sha256"]:
        raise UploadError(404, "document_not_found", "Оригинал документа изменился")
    return digest


def store_run(
    engine: Engine,
    root: Path,
    key: UUID,
    form: FormData,
    *,
    hosted_synthetic: bool = False,
    hosted_viewer: UUID | None = None,
    restore_hosted_originals: bool = False,
    prepared: bool = False,
) -> UUID:
    if (hosted_viewer is not None or restore_hosted_originals) and not hosted_synthetic:
        raise ValueError("Hosted options require synthetic admission")
    if prepared and hosted_synthetic:
        raise ValueError("Hosted runs use their own admission")
    local_fields = {"synthetic"} if not hosted_synthetic and not prepared else set()
    retained_fields = {"source_run_id", "retained_document_id"} if prepared else set()
    if set(form) - {*SCOPE_FIELDS, "report", "documents", *local_fields, *retained_fields}:
        raise input_error("Неизвестное поле")
    synthetic_values = form.getlist("synthetic")
    if synthetic_values and synthetic_values != ["true"]:
        raise input_error("Недопустимая маркировка комплекта", "synthetic")
    files, retains_synthetic = _pack_files(engine, form)
    ids = [uuid4().hex for _ in files]
    stored_scope = {}
    if any(field in form for field in SCOPE_FIELDS):
        stored_scope = _parse_scope(form, ids[0], files[0].format).model_dump(mode="json")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".upload-", dir=root))
    try:
        documents = [
            {
                "id": file_id,
                "name": file.name,
                "format": file.format,
                "size": file.size,
                "sha256": _store_pack_file(root, file, staging / file_id),
                "role": file.role,
            }
            for file, file_id in zip(files, ids, strict=True)
        ]
        is_bundled_pack = (
            not stored_scope and tuple(doc["sha256"] for doc in documents) == _DEMO_INPUT_DIGESTS
        )
        if synthetic_values and not is_bundled_pack:
            raise input_error("Недопустимая маркировка комплекта", "synthetic")
        synthetic = bool(synthetic_values) or retains_synthetic or (prepared and is_bundled_pack)
        if synthetic:
            documents[0]["synthetic"] = True
        fingerprint_scope = stored_scope.copy()
        fingerprint_scope.pop("report_document_id", None)
        fingerprint = {
            "scope": fingerprint_scope,
            "files": [[doc["name"], doc["sha256"]] for doc in documents],
        }
        if synthetic:
            fingerprint["synthetic"] = True
        digest = sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
        run_id = uuid4()
        with engine.begin() as connection:
            query = (
                insert(Run)
                .values(
                    id=run_id,
                    idempotency_key=key,
                    request_digest=digest,
                    status="prepared" if prepared else "queued",
                    prepared_at=func.now() if prepared else None,
                    scope=stored_scope,
                    documents=documents,
                )
                .on_conflict_do_nothing(index_elements=[Run.idempotency_key])
                .returning(Run.id)
            )
            if connection.execute(query).scalar_one_or_none() is None:
                previous = connection.execute(
                    select(Run.id, Run.request_digest, Run.documents, Run.status, Run.prepared_at)
                    .where(Run.idempotency_key == key)
                    .with_for_update()
                ).one_or_none()
                if previous is None:
                    # A concurrent DELETE may have released the package after the conflict.
                    raise UploadError(404, "upload_not_found", "Пакет больше не сохранён")
                existing = previous.id
                if previous.request_digest != digest or prepared != (
                    previous.prepared_at is not None
                ):
                    raise UploadError(
                        409, "idempotency_conflict", "Ключ уже связан с другим пакетом"
                    )
                if previous.status == "prepared" and _is_expired(previous.prepared_at):
                    raise _expired_upload()
                admission = connection.execute(
                    select(HostedClaim.viewer_id).where(HostedClaim.run_id == existing)
                ).one_or_none()
                if hosted_synthetic != (admission is not None) or (
                    admission is not None and admission.viewer_id != hosted_viewer
                ):
                    raise UploadError(409, "idempotency_conflict", "Ключ связан с другой очередью")
                if restore_hosted_originals:
                    _restore_hosted_dir(root, existing, staging, previous.documents, documents)
                return existing
            if hosted_synthetic:
                connection.execute(
                    insert(HostedClaim).values(run_id=run_id, attempt=0, viewer_id=hosted_viewer)
                )
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


def _is_expired(created: datetime) -> bool:
    return datetime.now(UTC) >= created + _PREPARED_TTL


def _expired_upload() -> UploadError:
    return UploadError(410, "upload_expired", "Срок хранения пакета истёк. Загрузите файлы снова")


def _parse_upload_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError:
        raise UploadError(404, "upload_not_found", "Пакет не найден") from None


def start_prepared_run(engine: Engine, root: Path, upload_id: str) -> UUID:
    key = _parse_upload_id(upload_id)
    with engine.begin() as connection:
        row = connection.execute(
            select(Run.status, Run.prepared_at, Run.documents)
            .where(Run.id == key, Run.prepared_at.is_not(None))
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise UploadError(404, "upload_not_found", "Пакет не найден")
        if row.status == "prepared":
            if _is_expired(row.prepared_at):
                raise _expired_upload()
            for document in row.documents:
                try:
                    _, info = run_reads._document_path(root, key, document["id"])
                except run_reads.RunReadError as error:
                    if error.status != 404:
                        raise
                    raise UploadError(404, "upload_not_found", "Загрузите файлы снова") from None
                if info.st_size != document["size"]:
                    raise UploadError(404, "upload_not_found", "Загрузите файлы снова")
            connection.execute(
                update(Run).where(Run.id == key).values(status="queued", created_at=func.now())
            )
        return key


def discard_prepared_run(engine: Engine, root: Path, upload_id: str) -> None:
    key = _parse_upload_id(upload_id)
    with engine.begin() as connection:
        prepared = connection.execute(
            select(Run.id).where(Run.id == key, Run.status == "prepared").with_for_update()
        ).scalar_one_or_none()
        if prepared is not None:
            _remove_prepared_files(root, prepared)
            connection.execute(delete(Run).where(Run.id == prepared))


def discard_expired_uploads(engine: Engine, root: Path) -> None:
    threshold = datetime.now(UTC) - _PREPARED_TTL
    expired = (
        select(Run.id)
        .where(Run.status == "prepared", Run.prepared_at <= threshold)
        .order_by(Run.prepared_at)
        .limit(20)
        .with_for_update(skip_locked=True)
    )
    with engine.begin() as connection:
        for identifier in connection.scalars(expired).all():
            _remove_prepared_files(root, identifier)
            connection.execute(delete(Run).where(Run.id == identifier))


def _remove_prepared_files(root: Path, identifier: UUID) -> None:
    try:
        rmtree(root / str(identifier))
    except FileNotFoundError:
        pass


def _restore_hosted_dir(
    root: Path, run_id: UUID, staged: Path, previous: list[dict], current: list[dict]
) -> None:
    """Restore byte-identical originals under saved IDs after ephemeral storage loss."""
    if len(previous) != len(current):
        raise ValueError("Hosted package manifest differs from saved originals")
    for old, new in zip(previous, current, strict=True):
        identifier = old["id"]
        if UUID(hex=identifier).hex != identifier or any(
            old[key] != new[key] for key in ("sha256", "size", "name", "format", "role")
        ):
            raise ValueError("Hosted package manifest differs from saved originals")
    destination = root / str(run_id)
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ValueError("Hosted package directory is not a regular directory")
    if destination.is_dir():
        for old, new in zip(previous, current, strict=True):
            original = destination / old["id"]
            if not _matches_original(original, old):
                (staged / new["id"]).replace(original)
        _sync_directory(destination)
        return
    # Work via unique staged names first, then switch atomically into place.
    with TemporaryDirectory(prefix=".restore-", dir=root) as directory:
        restored = Path(directory) / "originals"
        restored.mkdir(mode=0o700)
        for old, new in zip(previous, current, strict=True):
            (staged / new["id"]).rename(restored / old["id"])
        _sync_directory(restored)
        restored.rename(destination)
        _sync_directory(root)


def _matches_original(path: Path, item: dict) -> bool:
    try:
        info = path.lstat()
        if not S_ISREG(info.st_mode) or info.st_size != item["size"]:
            return False
        with path.open("rb") as stream:
            return file_digest(stream, "sha256").hexdigest() == item["sha256"]
    except FileNotFoundError:
        return False

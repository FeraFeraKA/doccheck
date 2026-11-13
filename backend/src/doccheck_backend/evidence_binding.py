"""Bind explicit, addressed assertions to the version of a document in a run."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError

from doccheck_backend.contracts.locators import Locator, PageLocator
from doccheck_backend.contracts.result import (
    Digest,
    Evidence,
    EvidenceKind,
    FileError,
    FileFormat,
    Period,
)

type DiagnosticCode = Literal[
    "source_changed",
    "unsupported_format",
    "invalid_locator",
    "invalid_reading",
    "missing_reading",
    "unreadable_source",
    "format_mismatch",
]

_DIGEST = TypeAdapter(Digest)
_LOCATOR = TypeAdapter(Locator)
_MESSAGES = {
    "source_changed": "Извлечение относится к другой версии исходного файла.",
    "unsupported_format": "Формат источника не поддерживается.",
    "format_mismatch": "Формат наблюдения отличается от формата в манифесте.",
    "invalid_locator": "Адрес наблюдения не соответствует формату источника.",
    "invalid_reading": "Наблюдение не соответствует контракту доказательства.",
    "missing_reading": "Подтверждённое значение в наблюдении отсутствует.",
    "unreadable_source": "Не удалось прочитать фрагмент исходного файла.",
}


class EvidenceBindingError(ValueError):
    """An assertion cannot be associated with the supplied run manifest."""


@dataclass(frozen=True)
class ManifestDocument:
    id: str
    sha256: str
    format: FileFormat | None
    role: Literal["report", "supporting"]


@dataclass(frozen=True)
class ObservationAssertion:
    run_id: UUID
    document_id: str
    # Digest of the bytes opened by the extractor, not a copied manifest field.
    opened_sha256: str
    source_format: FileFormat | None
    kind: EvidenceKind
    raw_value: str
    normalized_value: str | Period | None
    unit: str | None
    method: Literal["native", "ocr"]
    locator: Locator | None
    unreadable: bool = False


@dataclass(frozen=True)
class BoundFileError:
    document_id: str
    error: FileError
    # Kept for local diagnosis. Do not serialize the raw payload into API errors.
    raw_value: str
    locator: Locator | None


@dataclass(frozen=True)
class EvidenceBinding:
    evidence: tuple[Evidence, ...]
    errors: tuple[BoundFileError, ...]


def _stable_id(prefix: str, run_id: UUID, document: ManifestDocument, payload: object) -> str:
    value = json.dumps(
        [str(run_id), document.id, document.sha256, payload],
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"{prefix}-{sha256(value.encode()).hexdigest()}"


def _locator_matches(file_format: FileFormat | None, locator: Locator) -> bool:
    if isinstance(locator, PageLocator):
        return file_format == "pdf" or (file_format == "png" and locator.page == 1)
    if file_format == "xlsx":
        return locator.kind == "sheet"
    return file_format == "docx" and locator.kind in ("paragraph", "table_cell")


def _file_error(
    run_id: UUID, document: ManifestDocument, assertion: ObservationAssertion, code: DiagnosticCode
) -> BoundFileError:
    locator = assertion.locator
    address = None
    if locator is not None:
        try:
            checked = _LOCATOR.validate_python(locator.model_dump(mode="python", warnings=False))
            address = checked.model_dump(mode="json")
        except (ValidationError, PydanticSerializationError, ValueError, UnicodeError):
            # Keep the original locator locally, but exclude it from the wire error ID.
            pass
    return BoundFileError(
        document.id,
        FileError(
            id=_stable_id(
                "file-error",
                run_id,
                document,
                [
                    code,
                    assertion.kind,
                    assertion.method,
                    assertion.raw_value,
                    address,
                    assertion.opened_sha256,
                    assertion.source_format,
                ],
            ),
            code=code,
            message=_MESSAGES[code],
        ),
        assertion.raw_value,
        locator,
    )


def _bind(
    run_id: UUID,
    document: ManifestDocument,
    assertion: ObservationAssertion,
) -> Evidence | BoundFileError:
    try:
        opened = _DIGEST.validate_python(assertion.opened_sha256)
    except ValidationError:
        raise EvidenceBindingError("Malformed digest from the source reader") from None
    if opened != document.sha256:
        return _file_error(run_id, document, assertion, "source_changed")
    if document.format is None:
        return _file_error(run_id, document, assertion, "unsupported_format")
    if assertion.source_format != document.format:
        return _file_error(run_id, document, assertion, "format_mismatch")
    if assertion.unreadable:
        return _file_error(run_id, document, assertion, "unreadable_source")
    if assertion.locator is None:
        return _file_error(run_id, document, assertion, "invalid_locator")
    try:
        locator = _LOCATOR.validate_python(
            assertion.locator.model_dump(mode="python", warnings=False)
        )
        if not _locator_matches(document.format, locator):
            raise ValueError("Locator format mismatch")
    except (ValidationError, PydanticSerializationError, ValueError, UnicodeError):
        return _file_error(run_id, document, assertion, "invalid_locator")
    if assertion.normalized_value is None:
        return _file_error(run_id, document, assertion, "missing_reading")
    if assertion.method not in ("native", "ocr"):
        return _file_error(run_id, document, assertion, "invalid_reading")
    if (assertion.kind == "reported_value" and document.role != "report") or (
        assertion.kind == "amount" and document.role != "supporting"
    ):
        return _file_error(run_id, document, assertion, "invalid_reading")

    try:
        reading = assertion.normalized_value
        if isinstance(reading, Period):
            reading = reading.model_dump(mode="python")
        payload = {
            "kind": assertion.kind,
            "raw_value": assertion.raw_value,
            "normalized_value": reading,
            "unit": assertion.unit,
            "method": assertion.method,
            "locator": locator.model_dump(mode="python"),
        }
        # Revalidate serialized values, including caller-built Pydantic model updates.
        evidence = Evidence.model_validate({"id": "pending", "document_id": document.id, **payload})
        locator_fields = evidence.locator.model_dump(mode="json")
        for value in (
            evidence.document_id,
            evidence.raw_value,
            evidence.unit,
            evidence.normalized_value,
            *locator_fields.values(),
        ):
            if isinstance(value, str):
                if "\x00" in value:
                    raise ValueError("NUL is not valid in stored text")
                value.encode("utf-8")
        canonical = evidence.model_dump(mode="json", exclude={"id", "document_id"})
        return evidence.model_copy(update={"id": _stable_id("ev", run_id, document, canonical)})
    except (ValidationError, PydanticSerializationError, UnicodeError, ValueError):
        return _file_error(run_id, document, assertion, "invalid_reading")


def bind_observations(
    run_id: UUID,
    manifest: Sequence[ManifestDocument],
    assertions: Sequence[ObservationAssertion],
) -> EvidenceBinding:
    """Bind supplied readings; this stage performs no extraction or verification of value roles."""
    if not isinstance(run_id, UUID):
        raise EvidenceBindingError("A UUID run identity is required")
    documents = {}
    for document in manifest:
        if not isinstance(document.id, str) or not document.id.strip() or document.id in documents:
            raise EvidenceBindingError("Manifest document IDs must be present and unique")
        if document.role not in ("report", "supporting") or (
            document.format not in (None, "pdf", "png", "xlsx", "docx")
        ):
            raise EvidenceBindingError("Invalid manifest role or format")
        try:
            _DIGEST.validate_python(document.sha256)
        except ValidationError:
            raise EvidenceBindingError("Malformed manifest digest") from None
        documents[document.id] = document

    evidence: dict[str, Evidence] = {}
    errors: dict[str, BoundFileError] = {}
    for assertion in assertions:
        if assertion.run_id != run_id or assertion.document_id not in documents:
            raise EvidenceBindingError("Observation does not belong to the run manifest")
        result = _bind(run_id, documents[assertion.document_id], assertion)
        if isinstance(result, Evidence):
            evidence[result.id] = result
        else:
            errors[result.error.id] = result
    return EvidenceBinding(tuple(evidence.values()), tuple(errors.values()))

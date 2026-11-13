"""Bridge addressed source observations to the public document identity module."""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Protocol

from pydantic import TypeAdapter, ValidationError

from doccheck_backend.contracts.locators import Locator, PageLocator, SheetLocator
from doccheck_backend.contracts.result import FileFormat

type Method = Literal["native", "ocr"]
_LOCATOR = TypeAdapter(Locator)
_SUPPORTED_FORMATS = {
    "pdf": {"page"},
    "png": {"page"},
    "xlsx": {"sheet"},
    "docx": {"paragraph", "table_cell"},
}
_PREDICTIONS = {
    "doc_number",
    "verbatim_line",
    "contract_number",
    "date",
    "period_start",
    "period_end",
    "amount",
    "category",
    "description",
    "evidence_quote",
}
_DOCUMENT_HEADER = re.compile(
    r"^\s*(?:акт\b|сч[её]т\b|упд\b|ведомость\b|справка\b|"
    r"служебная\s+записка\b|универсальный\s+передаточный\s+документ\b|"
    r"номер\s+(?:документа|акта)\b|(?:№\s*)?документ(?:а)?\b)",
    re.IGNORECASE,
)


class ObservationInputError(ValueError):
    """An invalid local adapter request."""


class IdentityModuleUnavailable(RuntimeError):
    """The public identity package is unavailable in the worker environment."""


class IdentityResponseError(RuntimeError):
    """The identity package returned an incompatible or inconsistent response."""


@dataclass(frozen=True)
class SourceObservation:
    text: str
    locator: Locator
    method: Method


@dataclass(frozen=True)
class ObservedDocument:
    id: str
    source_path: Path
    source_sha256: str
    format: FileFormat
    observations: Sequence[SourceObservation]
    # XLSX inventory supplied by the extractor for the same file version.
    sheet_names: frozenset[str] = frozenset()
    prediction: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class IdentityCandidate:
    field: str
    value: str | None
    sources: tuple[SourceObservation, ...]
    source_ambiguous: bool = False


@dataclass(frozen=True)
class DocumentIdentity:
    id: str
    source_sha256: str
    acquisition: Literal["native", "scan"]
    candidates: tuple[IdentityCandidate, ...]
    number_status: str
    number_requires_review: bool
    conflicts: dict[str, object]
    issuer_status: str
    issuer_tax_id_conflict: bool


@dataclass(frozen=True)
class IdentityIssue:
    code: str
    document_id: str


@dataclass(frozen=True)
class IdentityResult:
    module_version: str
    policy_version: str
    synthetic: bool
    documents: tuple[DocumentIdentity, ...]
    errors: tuple[IdentityIssue, ...]
    duplicate_groups: tuple[tuple[str, ...], ...]
    review_queue: dict[str, object]
    review_pairs: tuple[dict[str, object], ...]


class _DocumentFactory(Protocol):
    def __call__(
        self,
        *,
        id: str,
        source_path: Path,
        source_sha256: str,
        acquisition: str,
        lines: list[dict[str, object]],
        prediction: dict[str, str | None],
    ) -> object: ...


class _ProcessDocuments(Protocol):
    def __call__(self, documents: Sequence[object], *, synthetic: bool) -> object: ...


@dataclass(frozen=True)
class _Prepared:
    document: ObservedDocument
    acquisition: Literal["native", "scan"]
    lines: list[dict[str, object]]
    sources: dict[str, list[SourceObservation]]


def _load_identity() -> tuple[_DocumentFactory, _ProcessDocuments, type[ValueError]]:
    # Keep package deployment in NRT-95 and permit the API server without ML dependencies.
    try:
        from doccheck_ml import DocumentInput, InputError, process_documents
    except ImportError:
        raise IdentityModuleUnavailable("Install the local doccheck-ml identity package") from None
    return DocumentInput, process_documents, InputError


def _module_line(source: SourceObservation) -> dict[str, object]:
    line: dict[str, object] = {"text": source.text}
    locator = source.locator
    if isinstance(locator, PageLocator):
        line["page"] = locator.page
        if locator.line is not None:
            line["line"] = locator.line
        if locator.bbox is not None:
            line["bbox"] = list(locator.bbox)
    elif isinstance(locator, SheetLocator):
        line.update(sheet=locator.sheet, cell=locator.range)
    # The public interface has no DOCX address fields. The real locator stays in the sidecar.
    return line


def _line_signature(line: dict[str, object]) -> str:
    return json.dumps(line, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _prepare(document: ObservedDocument) -> _Prepared:
    if (
        not isinstance(document.id, str)
        or not document.id.strip()
        or not isinstance(document.source_path, Path)
        or not isinstance(document.source_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", document.source_sha256)
        or not isinstance(document.format, str)
        or document.format not in _SUPPORTED_FORMATS
    ):
        raise ObservationInputError("Invalid document identity, path, digest or format")
    if not isinstance(document.prediction, Mapping) or any(
        key not in _PREDICTIONS or (value is not None and not isinstance(value, str))
        for key, value in document.prediction.items()
    ):
        raise ObservationInputError("Invalid identity prediction")
    if not isinstance(document.observations, Sequence) or not document.observations:
        raise ObservationInputError("A source document needs addressed observations")
    if not isinstance(document.sheet_names, frozenset) or any(
        not isinstance(name, str) or not name for name in document.sheet_names
    ):
        raise ObservationInputError("Invalid source sheet inventory")

    acquisition: Literal["native", "scan"] = "native"
    lines = []
    sources: dict[str, list[SourceObservation]] = {}
    for observation in document.observations:
        if (
            not isinstance(observation, SourceObservation)
            or not isinstance(observation.text, str)
            or not observation.text.strip()
            or observation.method not in ("native", "ocr")
        ):
            raise ObservationInputError("Invalid source text or acquisition method")
        try:
            locator = _LOCATOR.validate_python(observation.locator.model_dump())
        except (AttributeError, ValidationError):
            raise ObservationInputError("Invalid source locator") from None
        if locator.kind not in _SUPPORTED_FORMATS[document.format]:
            raise ObservationInputError("Source locator does not match the original format")
        if document.format == "png" and isinstance(locator, PageLocator) and locator.page != 1:
            raise ObservationInputError("PNG permits only page one")
        if isinstance(locator, SheetLocator) and locator.sheet not in document.sheet_names:
            raise ObservationInputError("Source sheet is absent from the extraction inventory")
        if observation.method == "ocr":
            acquisition = "scan"
        checked = SourceObservation(observation.text, locator, observation.method)
        line = _module_line(checked)
        lines.append(line)
        sources.setdefault(_line_signature(line), []).append(checked)
    return _Prepared(document, acquisition, lines, sources)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise IdentityResponseError("Expected an identity response object")
    return value


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise IdentityResponseError("Expected an identity response array")
    return value


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise IdentityResponseError("Expected a non-empty identity response string")
    return value


def _cell_position(locator: SheetLocator) -> tuple[int, int] | None:
    cell = re.fullmatch(r"([A-Z]+)([0-9]+)", locator.range)
    if cell is None:
        return None
    column = 0
    for letter in cell[1]:
        column = column * 26 + ord(letter) - ord("A") + 1
    return column, int(cell[2])


def _adjacent(first: SourceObservation, second: SourceObservation) -> bool:
    if first.method != second.method:
        return False
    left, right = first.locator, second.locator
    if isinstance(left, PageLocator) and isinstance(right, PageLocator):
        return left.page == right.page and left.line is not None and right.line == left.line + 1
    if isinstance(left, SheetLocator) and isinstance(right, SheetLocator):
        if left.sheet != right.sheet:
            return False
        previous, following = _cell_position(left), _cell_position(right)
        return previous is not None and following in (
            (previous[0] + 1, previous[1]),
            (previous[0], previous[1] + 1),
        )
    # The identity module has no DOCX structure. Keep its compounds as candidates.
    return False


def _contains_complete_reading(field: str, value: str | None, text: str) -> bool:
    if value is None:
        return False
    if field == "doc_number":
        # The module has already selected this observation as evidence for this role.
        # Require the entire value at a number marker, without accepting a prefix.
        return (
            re.search(
                rf"(?<!\w)(?:№|N(?:[oоº°])?\.?)\s*{re.escape(value)}"
                r"(?=\s*(?:$|[,;:]|\bот\b|\||[»\"]))",
                text.strip(),
                re.IGNORECASE,
            )
            is not None
        )
    if field != "amount":
        return False
    amount = re.search(
        r"(?<![\w.,+−-])([+-]?(?:[0-9]{1,3}(?:[ \u00a0\u2009\u202f][0-9]{3})+|[0-9]+)"
        r"(?:[.,][0-9]+)?)\s*(?:₽|руб(?:\.|лей|ля|ль)?|RUB)\s*\.?\s*$",
        text,
        re.IGNORECASE,
    )
    if amount is None or re.search(r"[0-9+−-]\s+$", text[: amount.start()]):
        return False
    try:
        compact = re.sub(r"\s+", "", amount[1]).replace(",", ".")
        return Decimal(compact) == Decimal(value)
    except InvalidOperation:
        return False


def _has_document_number_context(source: SourceObservation, prepared: _Prepared) -> bool:
    if _DOCUMENT_HEADER.match(source.text):
        return True
    if not re.match(r"^\s*(?:№|N(?:[oоº°])?\.?)", source.text, re.I):
        # This can be the value half of an addressed, compound reading.
        return True
    return any(
        _DOCUMENT_HEADER.match(previous.text) and _adjacent(previous, source)
        for candidates in prepared.sources.values()
        for previous in candidates
    )


def _evidence_sources(
    value: object,
    prepared: _Prepared,
    field: str,
    reading: str | None,
) -> tuple[tuple[SourceObservation, ...], bool]:
    if value is None:
        return (), False
    evidence = value if isinstance(value, list) else [value]
    sources: list[SourceObservation] = []
    ambiguous = False
    for entry in evidence:
        try:
            matches = prepared.sources.get(_line_signature(_mapping(entry)), [])
        except (IdentityResponseError, TypeError, ValueError):
            matches = []
        # DOCX and otherwise lossy projections can produce identical module evidence.
        # Keep the candidate, without attributing it to an arbitrary source.
        if len(matches) == 1 and matches[0] not in sources:
            sources.append(matches[0])
        elif len(matches) != 1:
            ambiguous = True
    if field == "doc_number":
        trusted = [source for source in sources if _has_document_number_context(source, prepared)]
        ambiguous = ambiguous or len(trusted) != len(sources)
        sources = trusted
    if len(evidence) < 2:
        return tuple(sources), ambiguous

    # The module can flatten independent readings and compounds into the same list.
    # Retain complete readings, or one demonstrably adjacent compound. Without
    # explicit grouping, mixed complete and incomplete entries remain ambiguous.
    complete = {
        index
        for index, source in enumerate(sources)
        if _contains_complete_reading(field, reading, source.text)
    }
    if (
        not ambiguous
        and not complete
        and all(_adjacent(left, right) for left, right in zip(sources, sources[1:]))
    ):
        return tuple(sources), False
    return tuple(source for index, source in enumerate(sources) if index in complete), (
        ambiguous or len(complete) != len(sources)
    )


def _candidate(
    field: str,
    value: object,
    evidence: object,
    prepared: _Prepared,
) -> IdentityCandidate:
    if value is not None and not isinstance(value, str):
        raise IdentityResponseError("Invalid candidate value")
    sources, ambiguous = _evidence_sources(evidence, prepared, field, value)
    return IdentityCandidate(field, value, sources, ambiguous)


def _number_candidates(number: dict[str, object], prepared: _Prepared) -> list[IdentityCandidate]:
    readings = [_mapping(item) for item in _array(number.get("candidates"))]
    selected_value = number.get("value")
    matching_evidence = [
        item.get("evidence")
        for item in readings
        if selected_value is not None and item.get("value") == selected_value
    ]
    # The module's selected evidence can describe an earlier source reading during a conflict.
    selected_evidence = matching_evidence[0] if len(matching_evidence) == 1 else None
    selected = _candidate("doc_number", selected_value, selected_evidence, prepared)
    if selected_value is not None and len(matching_evidence) != 1 and number.get("evidence"):
        selected = IdentityCandidate(selected.field, selected.value, (), True)
    alternatives = [
        _candidate("doc_number", item.get("value"), item.get("evidence"), prepared)
        for item in readings
    ]
    return [selected, *(item for item in alternatives if item != selected)]


def _record(raw: dict[str, object], prepared: _Prepared) -> DocumentIdentity:
    doc = prepared.document
    if (
        raw.get("source_sha256") != doc.source_sha256
        or raw.get("acquisition") != prepared.acquisition
    ):
        raise IdentityResponseError("Identity response source does not match its request")
    facts = _mapping(raw.get("facts"))
    source_facts = _mapping(raw.get("source_facts"))
    proof = _mapping(raw.get("fact_evidence"))
    number = _mapping(raw.get("number"))
    doc_type = _mapping(raw.get("doc_type"))
    issuer = _mapping(raw.get("issuer"))
    candidates = [
        _candidate(
            field, value, proof.get(field) if source_facts.get(field) == value else None, prepared
        )
        for field, value in facts.items()
    ]
    candidates.extend(
        _candidate(field, value, proof.get(field), prepared)
        for field, value in source_facts.items()
        if facts.get(field) != value
    )
    numbers = _number_candidates(number, prepared)
    candidates.extend(numbers)
    candidates.append(
        _candidate("doc_type", doc_type.get("value"), doc_type.get("evidence"), prepared)
    )
    candidates.append(_candidate("issuer", issuer.get("value"), issuer.get("evidence"), prepared))
    for reading in _array(issuer.get("candidates", [])):
        candidate = _mapping(reading)
        item = _candidate("issuer", candidate.get("value"), candidate.get("evidence"), prepared)
        if item not in candidates:
            candidates.append(item)
    candidates.append(
        _candidate("issuer_tax_id", issuer.get("tax_id"), issuer.get("tax_id_evidence"), prepared)
    )
    manual = number.get("manual_review_required")
    tax_conflict = issuer.get("tax_id_conflict")
    if not isinstance(manual, bool) or not isinstance(tax_conflict, bool):
        raise IdentityResponseError("Invalid document review flag")
    return DocumentIdentity(
        doc.id,
        doc.source_sha256,
        prepared.acquisition,
        tuple(candidates),
        _required_text(number.get("status")),
        manual or numbers[0].source_ambiguous,
        _mapping(raw.get("fact_conflicts")),
        _required_text(issuer.get("status")),
        tax_conflict,
    )


def _known_id(value: object, known: Mapping[str, _Prepared]) -> str:
    document_id = _required_text(value)
    if document_id not in known:
        raise IdentityResponseError("Identity response contains an unknown document")
    return document_id


def _duplicates(
    raw: Iterable[object], prepared: Mapping[str, _Prepared]
) -> tuple[tuple[str, ...], ...]:
    groups = []
    seen: set[str] = set()
    for entries in raw:
        members = tuple(_known_id(item, prepared) for item in _array(entries))
        hashes = {prepared[member].document.source_sha256 for member in members}
        if len(hashes) != 1 or seen.intersection(members) or len(set(members)) != len(members):
            raise IdentityResponseError("Invalid byte-duplicate group")
        seen.update(members)
        groups.append(members)
    if seen != set(prepared):
        raise IdentityResponseError("Identity response has incomplete duplicate groups")
    return tuple(groups)


def identify_documents(
    documents: Sequence[ObservedDocument],
    *,
    synthetic: bool,
) -> IdentityResult:
    """Apply identity policy to supplied observations and keep outputs as candidates."""
    if (
        type(synthetic) is not bool
        or not isinstance(documents, Sequence)
        or not documents
        or any(not isinstance(doc, ObservedDocument) for doc in documents)
    ):
        raise ObservationInputError(
            "Use a non-empty document sequence and an explicit synthetic flag"
        )
    items = tuple(_prepare(document) for document in documents)
    prepared = {item.document.id: item for item in items}
    if len(prepared) != len(items):
        raise ObservationInputError("Document IDs must be unique")

    create_input, process, module_input_error = _load_identity()
    inputs = [
        create_input(
            id=item.document.id,
            source_path=item.document.source_path,
            source_sha256=item.document.source_sha256,
            acquisition=item.acquisition,
            lines=item.lines,
            prediction=dict(item.document.prediction),
        )
        for item in items
    ]
    try:
        result = _mapping(process(inputs, synthetic=synthetic))
    except module_input_error:
        raise ObservationInputError("Identity module rejected its input") from None
    if (
        result.get("schema_version") != "doccheck-ml-identity/1"
        or result.get("synthetic") is not synthetic
        or result.get("inference_performed") is not False
        or result.get("financial_reconciliation_performed") is not False
    ):
        raise IdentityResponseError("Incompatible identity response")

    seen: set[str] = set()
    records = []
    errors = []
    for entry in _array(result.get("records")):
        raw = _mapping(entry)
        document_id = _known_id(raw.get("id"), prepared)
        if document_id in seen:
            raise IdentityResponseError("Identity response contains a duplicate document")
        seen.add(document_id)
        records.append(_record(raw, prepared[document_id]))
    for entry in _array(result.get("errors")):
        raw = _mapping(entry)
        document_id = _known_id(raw.get("id"), prepared)
        code = _required_text(raw.get("code"))
        if code not in ("source_unavailable", "source_changed") or document_id in seen:
            raise IdentityResponseError("Unknown or duplicate identity error")
        seen.add(document_id)
        errors.append(IdentityIssue(code, document_id))
    if seen != set(prepared) or result.get("status") != ("partial" if errors else "completed"):
        raise IdentityResponseError("Identity response does not account for every source")

    groups = _mapping(result.get("groups"))
    usable = {record.id: prepared[record.id] for record in records}
    return IdentityResult(
        _required_text(result.get("module_version")),
        _required_text(result.get("policy_version")),
        synthetic,
        tuple(records),
        tuple(errors),
        _duplicates(_array(groups.get("groups")), usable),
        _mapping(result.get("review_queue")),
        tuple(_mapping(item) for item in _array(groups.get("review_pairs"))),
    )

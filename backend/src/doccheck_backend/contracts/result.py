"""Pydantic source of the doccheck-check-result/1 contract."""

import re
from collections import Counter
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .locators import AddressKey, ContractModel, IsoDate, Locator, PageLocator, Text, check_period

RESULT_SCHEMA_VERSION = "doccheck-check-result/1"
JobStatus = Literal["queued", "processing", "completed", "completed_with_issues", "failed"]
RowStatus = Literal["verified", "discrepancy", "unverified"]
FileFormat = Literal["pdf", "png", "xlsx", "docx"]
FileDecisionState = Literal["include", "exclude", "needs_review", "parse_error"]
EvidenceKind = Literal[
    "reported_value", "amount", "contract", "period", "article", "document_identity"
]
_DECIMAL_PATTERN = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?(?![\s\S])")
_RUB_PATTERN = re.compile(r"^(?!-0+\.00(?![\s\S]))-?[0-9]+\.[0-9]{2}(?![\s\S])")
DecimalText = Annotated[str, StringConstraints(strict=True, pattern=_DECIMAL_PATTERN)]
_RUB_SCHEMA = {"type": "string", "pattern": _RUB_PATTERN.pattern}
_DECIMAL_FIELDS = ("reported_value", "expected_value", "observed_evidence_sum", "delta")
_COMPLETED_JOB_STATES = ("completed", "completed_with_issues")
AmountReadings = dict[tuple[str, AddressKey], set[tuple[str | None, Decimal]]]
Digest = Annotated[
    str, StringConstraints(strict=True, pattern=re.compile(r"^[0-9a-f]{64}(?![\s\S])"))
]
Count = Annotated[int, Field(strict=True, ge=0)]
RequiredRefs = Annotated[list[Text], Field(min_length=1)]


class Scope(ContractModel):
    report_document_id: Text
    contract_number: Text
    period_start: IsoDate
    period_end: IsoDate
    report_row_locator: Locator | None

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        check_period(self.period_start, self.period_end)
        return self


class Versions(ContractModel):
    code_revision: Text
    rules_version: Text
    ml_module_version: Text | None
    ml_policy_version: Text | None
    model_revision: Text | None


class Issue(ContractModel):
    code: Text
    message: Text


class FileError(Issue):
    id: Text


class Reason(Issue):
    evidence_refs: list[Text]


class FileDecision(ContractModel):
    state: FileDecisionState
    reason_code: Text
    message: Text
    evidence_refs: list[Text]


class SourceDocument(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"parse_status": {"enum": ["partial", "error"]}}},
                    "then": {"properties": {"errors": {"minItems": 1}}},
                },
                {
                    "if": {
                        "properties": {
                            "decision": {"properties": {"state": {"const": "parse_error"}}}
                        }
                    },
                    "then": {"properties": {"parse_status": {"const": "error"}}},
                },
                {
                    "if": {
                        "properties": {"decision": {"properties": {"state": {"const": "include"}}}}
                    },
                    "then": {"properties": {"parse_status": {"enum": ["parsed", "partial"]}}},
                },
            ]
        }
    )

    id: Text
    name: Text
    sha256: Digest
    format: FileFormat | None
    role: Literal["report", "support"]
    parse_status: Literal["pending", "parsed", "partial", "error"]
    decision: FileDecision
    errors: list[FileError]
    duplicate_of: Text | None = None

    @model_validator(mode="after")
    def check_decision(self) -> Self:
        if self.duplicate_of is not None and self.decision.state != "exclude":
            raise ValueError("a byte copy must be excluded")
        if self.decision.state == "parse_error" and self.parse_status != "error":
            raise ValueError("parse_error requires a failed parse")
        if self.parse_status in ("partial", "error") and not self.errors:
            raise ValueError("a partial or failed parse requires a file error")
        if self.decision.state == "include" and self.parse_status not in ("parsed", "partial"):
            raise ValueError("an included document requires a usable parse")
        if self.format is None and not any(
            error.code == "unsupported_format" for error in self.errors
        ):
            raise ValueError("an unknown format requires an unsupported_format error")
        return self


class Period(ContractModel):
    start: IsoDate | None
    end: IsoDate | None

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        check_period(self.start, self.end)
        if self.start is None and self.end is None:
            raise ValueError("period evidence requires at least one observed date")
        return self


class Evidence(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"kind": {"const": "period"}}},
                    "then": {"properties": {"normalized_value": {"type": "object"}}},
                    "else": {"properties": {"normalized_value": {"type": "string"}}},
                },
                {
                    "if": {"properties": {"kind": {"enum": ["amount", "reported_value"]}}},
                    "then": {
                        "properties": {"normalized_value": {"pattern": _DECIMAL_PATTERN.pattern}}
                    },
                },
                {
                    "if": {
                        "properties": {
                            "kind": {"enum": ["amount", "reported_value"]},
                            "unit": {"const": "RUB"},
                        }
                    },
                    "then": {"properties": {"normalized_value": _RUB_SCHEMA}},
                },
            ]
        }
    )

    id: Text
    document_id: Text
    kind: EvidenceKind
    raw_value: Text
    normalized_value: Text | Period
    unit: Text | None
    method: Text
    locator: Locator

    @model_validator(mode="after")
    def check_normalized_value(self) -> Self:
        value = self.normalized_value
        if self.kind == "period":
            if not isinstance(value, Period):
                raise ValueError("period evidence requires explicit date bounds")
        elif not isinstance(value, str):
            raise ValueError("this evidence kind requires a normalized string")
        if self.kind in ("amount", "reported_value"):
            if not isinstance(value, str) or not _DECIMAL_PATTERN.fullmatch(value):
                raise ValueError("numeric evidence requires an exact decimal string")
            if self.unit == "RUB" and not _RUB_PATTERN.fullmatch(value):
                raise ValueError("RUB evidence requires a decimal string in kopecks")
        return self


class Completeness(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"basis": {"const": "none"}}},
            "then": {"properties": {"state": {"const": "unknown"}}},
        }
    )

    state: Literal["complete", "incomplete", "unknown"]
    basis: Literal["manifest", "user_declaration", "dataset_fixture", "none"]
    reason: Text
    evidence_refs: list[Text]

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        if self.basis == "none" and self.state != "unknown":
            raise ValueError("an unspecified basis requires unknown completeness")
        return self


class Component(ContractModel):
    amount: DecimalText
    amount_refs: RequiredRefs
    contract_refs: RequiredRefs
    period_refs: RequiredRefs
    article_refs: RequiredRefs
    identity_refs: list[Text] = Field(default_factory=list)
    relation_reason: Text


class Calculation(ContractModel):
    policy_id: Text
    operation: Literal["sum"] | None = None
    formula: Text
    components: list[Component]


def _exact_units(value: str, places: int) -> int:
    """Convert a validated decimal string to an integer at a common precision."""
    numerator, denominator = Decimal(value).as_integer_ratio()
    return numerator * 10**places // denominator


class ResultRow(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"unit": {"const": "RUB"}}},
                    "then": {
                        "properties": {
                            **{
                                name: {"anyOf": [_RUB_SCHEMA, {"type": "null"}]}
                                for name in _DECIMAL_FIELDS
                            },
                            "calculation": {
                                "properties": {
                                    "components": {"items": {"properties": {"amount": _RUB_SCHEMA}}}
                                }
                            },
                        }
                    },
                },
                {
                    "if": {"properties": {"status": {"const": "unverified"}}},
                    "then": {"properties": {"delta": {"type": "null"}, "reasons": {"minItems": 1}}},
                    "else": {
                        "properties": {
                            name: {"type": "string"}
                            for name in ("reported_value", "expected_value", "delta")
                        }
                    },
                },
                {
                    "if": {
                        "properties": {
                            "completeness": {
                                "properties": {"state": {"enum": ["unknown", "incomplete"]}}
                            }
                        }
                    },
                    "then": {"properties": {"expected_value": {"type": "null"}}},
                },
                {
                    "if": {"properties": {"expected_value": {"type": "string"}}},
                    "then": {
                        "properties": {
                            "observed_evidence_sum": {"type": "string"},
                            "calculation": {
                                "required": ["operation"],
                                "properties": {
                                    "operation": {"const": "sum"},
                                    "components": {"minItems": 1},
                                },
                            },
                        }
                    },
                },
                {
                    "if": {"properties": {"derived_mismatch": {"const": True}}},
                    "then": {
                        "properties": {
                            "status": {"const": "discrepancy"},
                            "root_issue_id": {"type": "string"},
                        }
                    },
                },
            ]
        }
    )

    id: Text
    label: Text
    indicator_code: Text | None
    unit: Text
    reported_value: DecimalText | None
    reported_evidence_refs: list[Text]
    expected_value: DecimalText | None
    observed_evidence_sum: DecimalText | None
    delta: DecimalText | None
    status: RowStatus
    completeness: Completeness
    calculation: Calculation
    reasons: list[Reason]
    root_issue_id: Text | None
    derived_mismatch: StrictBool

    @model_validator(mode="after")
    def check_totals(self) -> Self:
        totals = (self.reported_value, self.expected_value, self.observed_evidence_sum, self.delta)
        components = [component.amount for component in self.calculation.components]
        values = [value for value in totals if value is not None] + components
        if self.unit == "RUB" and any(not _RUB_PATTERN.fullmatch(value) for value in values):
            raise ValueError("RUB values must be decimal strings in kopecks")
        places = max((len(value.partition(".")[2]) for value in values), default=0)
        if components:
            observed = self.observed_evidence_sum
            if observed is None or sum(_exact_units(value, places) for value in components) != (
                _exact_units(observed, places)
            ):
                raise ValueError("observed sum must equal the sum of admitted components")
        elif self.observed_evidence_sum is not None:
            raise ValueError("observed sum must be null without admitted components")
        if self.reported_value is not None and not self.reported_evidence_refs:
            raise ValueError("a reported value requires evidence")
        if self.expected_value is not None:
            if self.completeness.state != "complete":
                raise ValueError("an expected value requires complete coverage")
            if self.calculation.operation != "sum" or self.observed_evidence_sum is None:
                raise ValueError("an expected value requires a supported calculation with evidence")
            if Decimal(self.expected_value) != Decimal(self.observed_evidence_sum):
                raise ValueError("an expected sum must equal the sum of admitted components")
        if self.derived_mismatch and (self.status != "discrepancy" or self.root_issue_id is None):
            raise ValueError("a derived mismatch requires a discrepancy and a root issue")
        if self.status == "unverified":
            if self.delta is not None or not self.reasons:
                raise ValueError("an unverified row requires a reason and null delta")
            return self
        if self.reported_value is None or self.expected_value is None or self.delta is None:
            raise ValueError("a checked row requires reported value, expected value and delta")
        delta = _exact_units(self.delta, places)
        if delta != (
            _exact_units(self.reported_value, places) - _exact_units(self.expected_value, places)
        ):
            raise ValueError("delta must be reported minus expected")
        if (self.status == "verified") != (delta == 0):
            raise ValueError("row status must agree with delta")
        if self.status == "discrepancy" and not self.reasons:
            raise ValueError("a discrepancy requires a reason")
        return self


class StatusCounts(ContractModel):
    verified: Count
    discrepancy: Count
    unverified: Count


class PrimaryIssue(Reason):
    id: Text
    file_error_refs: list[Text] = Field(default_factory=list)


class Summary(ContractModel):
    counts: StatusCounts
    primary_issues: list[PrimaryIssue]
    conclusion: Text


class CheckResult(ContractModel):
    schema_version: Literal[RESULT_SCHEMA_VERSION]
    run_id: Text
    synthetic: StrictBool
    scope: Scope
    versions: Versions
    documents: list[SourceDocument]
    evidence: list[Evidence]
    rows: list[ResultRow]
    summary: Summary

    @model_validator(mode="after")
    def check_references(self) -> Self:
        documents = {item.id: item for item in self.documents}
        evidence = {item.id: item for item in self.evidence}
        primary = {item.id for item in self.summary.primary_issues}
        if len(documents) != len(self.documents) or len(evidence) != len(self.evidence):
            raise ValueError("document and evidence IDs must be unique")
        if len(primary) != len(self.summary.primary_issues):
            raise ValueError("primary issue IDs must be unique")
        file_errors = [error.id for document in self.documents for error in document.errors]
        error_ids = set(file_errors)
        if len(error_ids) != len(file_errors):
            raise ValueError("file error IDs must be unique")
        if len({row.id for row in self.rows}) != len(self.rows):
            raise ValueError("row IDs must be unique")
        report = documents.get(self.scope.report_document_id)
        if report is None or report.role != "report":
            raise ValueError("scope must refer to a report document")
        if self.scope.report_row_locator is not None:
            _check_locator(report.format, self.scope.report_row_locator)
        for item in self.evidence:
            document = documents.get(item.document_id)
            if document is None:
                raise ValueError("evidence must refer to a document in this result")
            _check_locator(document.format, item.locator)
        representatives: set[str] = set()
        for item in self.documents:
            _require_refs(item.decision.evidence_refs, evidence)
            if item.duplicate_of is None:
                if item.sha256 in representatives:
                    raise ValueError("identical documents need one representative")
                representatives.add(item.sha256)
                continue
            original = documents.get(item.duplicate_of)
            if (
                original is None
                or original.sha256 != item.sha256
                or original.duplicate_of is not None
            ):
                raise ValueError("a byte copy must reference a representative with the same digest")
        readings = _index_readings(self.evidence)
        for row in self.rows:
            self._check_row_refs(row, report, documents, evidence, readings)
            if row.root_issue_id is not None and row.root_issue_id not in primary:
                raise ValueError("row root issue must refer to a primary issue in this result")
        for issue in self.summary.primary_issues:
            _require_refs(issue.evidence_refs, evidence)
            if not error_ids.issuperset(issue.file_error_refs):
                raise ValueError("a primary issue must refer to file errors in this result")
        counts = Counter(row.status for row in self.rows)
        declared_counts = self.summary.counts.model_dump()
        if any(counts[status] != count for status, count in declared_counts.items()):
            raise ValueError("summary counts must agree with rows")
        return self

    def _check_row_refs(
        self,
        row: ResultRow,
        report: SourceDocument,
        documents: dict[str, SourceDocument],
        evidence: dict[str, Evidence],
        readings: AmountReadings,
    ) -> None:
        observed = _require_refs(row.reported_evidence_refs, evidence, "reported_value")
        if any(item.document_id != report.id for item in observed):
            raise ValueError("reported evidence must come from the selected report")
        if observed and not _is_admitted(report):
            raise ValueError("reported evidence requires an admitted report")
        if row.reported_value is not None:
            _check_amount_readings(observed, row.unit, row.reported_value, readings, "reported")
        if row.completeness.basis == "dataset_fixture" and not self.synthetic:
            raise ValueError("dataset fixture coverage requires a synthetic result")
        coverage = _require_refs(row.completeness.evidence_refs, evidence)
        if row.completeness.state == "complete" and any(
            not _is_admitted(documents[item.document_id]) for item in coverage
        ):
            raise ValueError("complete coverage cannot rely on an inadmissible document")
        for reason in row.reasons:
            _require_refs(reason.evidence_refs, evidence)
        used_addresses: set[tuple[str, AddressKey]] = set()
        used_lines: set[tuple[str, int, int]] = set()
        used_line_only: set[tuple[str, int, int]] = set()
        for component in row.calculation.components:
            amounts = _require_refs(component.amount_refs, evidence, "amount")
            _check_amount_readings(amounts, row.unit, component.amount, readings, "component")
            addresses: set[tuple[str, AddressKey]] = set()
            lines: set[tuple[str, int, int]] = set()
            line_only: set[tuple[str, int, int]] = set()
            for item in amounts:
                document = documents[item.document_id]
                if document.role != "support" or not _is_admitted(document):
                    raise ValueError("components require admitted supporting documents")
                locator = item.locator
                keys = locator.address_keys()
                addresses.update((document.id, key) for key in keys)
                if isinstance(locator, PageLocator) and locator.line is not None:
                    line = (document.id, locator.page, locator.line)
                    lines.add(line)
                    if ("line", locator.page, locator.line) in keys:
                        line_only.add(line)
            self._check_component_scope(component, row, amounts, documents, evidence)
            if used_addresses & addresses or used_line_only & lines or line_only & used_lines:
                raise ValueError("an amount evidence address must not be counted twice in a row")
            used_addresses.update(addresses)
            used_lines.update(lines)
            used_line_only.update(line_only)

    def _check_component_scope(
        self,
        component: Component,
        row: ResultRow,
        amounts: list[Evidence],
        documents: dict[str, SourceDocument],
        evidence: dict[str, Evidence],
    ) -> None:
        contracts = _require_refs(component.contract_refs, evidence, "contract")
        periods = _require_refs(component.period_refs, evidence, "period")
        articles = _require_refs(component.article_refs, evidence, "article")
        if any(
            not _is_admitted(documents[item.document_id]) for item in contracts + periods + articles
        ):
            raise ValueError("component scope requires admitted documents")
        sources = {item.document_id for item in amounts}
        identity = _require_refs(component.identity_refs, evidence, "document_identity")
        if any(
            not _is_admitted(documents[item.document_id])
            or documents[item.document_id].role != "support"
            for item in identity
        ):
            raise ValueError("component identity requires admitted supporting documents")
        identities: dict[str, set[str]] = {}
        for item in identity:
            if isinstance(item.normalized_value, str):
                identities.setdefault(item.document_id, set()).add(item.normalized_value)
        common_identity = (
            set.intersection(*(identities.get(source, set()) for source in sources))
            if identity
            else set()
        )
        if len(sources) > 1 and not common_identity:
            raise ValueError("multiple amount sources require a shared source identity")
        scope_evidence = contracts + periods + articles
        for item in scope_evidence:
            if documents[item.document_id].role != "support":
                raise ValueError("the report alone cannot establish the scope of a component")
        separate_sources = {item.document_id for item in scope_evidence} - sources
        for source in separate_sources:
            common_identity &= identities.get(source, set())
        if separate_sources and not common_identity:
            raise ValueError("separate scope evidence requires a shared source identity")
        if any(item.normalized_value != self.scope.contract_number for item in contracts):
            raise ValueError("contract evidence contradicts the selected contract")
        for item in periods:
            value = item.normalized_value
            if isinstance(value, Period) and (
                (value.start is not None and value.start > self.scope.period_end)
                or (value.end is not None and value.end < self.scope.period_start)
            ):
                raise ValueError("period evidence lies outside the selected period")
        if row.indicator_code is not None and any(
            item.normalized_value != row.indicator_code for item in articles
        ):
            raise ValueError("article evidence contradicts the indicator code")


def _is_admitted(document: SourceDocument) -> bool:
    return document.decision.state == "include" and document.parse_status in ("parsed", "partial")


def _reading_keys(item: Evidence) -> set[tuple[str, AddressKey]]:
    return {(item.document_id, key) for key in item.locator.address_keys()}


def _index_readings(evidence: list[Evidence]) -> AmountReadings:
    readings: AmountReadings = {}
    for item in evidence:
        if item.kind in ("amount", "reported_value") and isinstance(item.normalized_value, str):
            value = (item.unit, Decimal(item.normalized_value))
            for key in _reading_keys(item):
                readings.setdefault(key, set()).add(value)
            locator = item.locator
            if isinstance(locator, PageLocator) and locator.line is not None:
                line = (item.document_id, ("page_line", locator.page, locator.line))
                readings.setdefault(line, set()).add(value)
    return readings


def _check_amount_readings(
    evidence: list[Evidence],
    unit: str,
    amount: str,
    readings: AmountReadings,
    role: Literal["reported", "component"],
) -> None:
    expected = {(unit, Decimal(amount))}
    message = f"{role} evidence must agree on value and unit at its canonical address"
    if not evidence:
        raise ValueError(message)
    for item in evidence:
        keys = _reading_keys(item)
        if any(readings.get(key) != expected for key in keys):
            raise ValueError(message)
        locator = item.locator
        if isinstance(locator, PageLocator) and locator.line is not None:
            line = (item.document_id, ("line", locator.page, locator.line))
            # Line-only evidence must agree with all readings for that line.
            key = (
                (item.document_id, ("page_line", locator.page, locator.line))
                if line in keys
                else line
            )
            if key in readings and readings[key] != expected:
                raise ValueError(message)


def _check_locator(format_: FileFormat | None, locator: Locator) -> None:
    if format_ in ("pdf", "png") and isinstance(locator, PageLocator):
        if format_ == "pdf" or locator.page == 1:
            return
    if format_ == "xlsx" and locator.kind == "sheet":
        return
    if format_ == "docx" and locator.kind in ("paragraph", "table_cell"):
        return
    raise ValueError("locator does not match the source document format")


def _require_refs(
    ids: list[str], evidence: dict[str, Evidence], kind: EvidenceKind | None = None
) -> list[Evidence]:
    found = []
    for reference in ids:
        item = evidence.get(reference)
        if item is None or (kind is not None and item.kind != kind):
            raise ValueError(f"evidence reference {reference!r} is missing or has the wrong role")
        found.append(item)
    return found


_RESULT_WITH_FILE_ERRORS = {
    "properties": {"documents": {"contains": {"properties": {"errors": {"minItems": 1}}}}}
}


class CheckJob(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "allOf": [
                {
                    "if": {"properties": {"status": {"enum": list(_COMPLETED_JOB_STATES)}}},
                    "then": {"properties": {"result": {"type": "object"}}},
                    "else": {"properties": {"result": {"type": "null"}}},
                },
                {
                    "if": {"properties": {"status": {"const": "failed"}}},
                    "then": {"properties": {"error": {"type": "object"}}},
                },
                {
                    "if": {
                        "properties": {"status": {"enum": ["queued", "processing", "completed"]}}
                    },
                    "then": {"properties": {"error": {"type": "null"}}},
                },
                {
                    "if": {"properties": {"status": {"const": "completed"}}},
                    "then": {"properties": {"result": {"not": _RESULT_WITH_FILE_ERRORS}}},
                },
                {
                    "if": {"properties": {"status": {"const": "completed_with_issues"}}},
                    "then": {
                        "anyOf": [
                            {"properties": {"error": {"type": "object"}}},
                            {"properties": {"result": _RESULT_WITH_FILE_ERRORS}},
                        ]
                    },
                },
            ],
        }
    )

    run_id: Text
    status: JobStatus
    result: CheckResult | None
    error: Issue | None

    @model_validator(mode="after")
    def check_state(self) -> Self:
        if (self.result is not None) != (self.status in _COMPLETED_JOB_STATES):
            raise ValueError("only a completed job has a saved result")
        if self.result is not None and self.result.run_id != self.run_id:
            raise ValueError("job and result run IDs must match")
        if self.status == "failed" and self.error is None:
            raise ValueError("a failed job requires a technical error")
        if self.status in ("queued", "processing", "completed") and self.error is not None:
            raise ValueError("a job error requires failed or completed_with_issues status")
        if self.result is not None:
            has_issues = self.error is not None or any(
                item.errors for item in self.result.documents
            )
            if (self.status == "completed_with_issues") != has_issues:
                raise ValueError(
                    "completed_with_issues must agree with the recorded technical errors"
                )
        return self

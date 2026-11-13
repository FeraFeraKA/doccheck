"""Pydantic source of the doccheck-check-result/1 contract."""

import re
from collections import Counter
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, StrictBool, StringConstraints, model_validator

from .locators import ContractModel, IsoDate, Locator, PageLocator, Text, check_period

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


class Reason(Issue):
    evidence_refs: list[Text]


class FileDecision(ContractModel):
    state: FileDecisionState
    reason_code: Text
    message: Text
    evidence_refs: list[Text]


class SourceDocument(ContractModel):
    id: Text
    name: Text
    sha256: Digest
    format: FileFormat | None
    role: Literal["report", "support"]
    parse_status: Literal["pending", "parsed", "partial", "error"]
    decision: FileDecision
    errors: list[Issue]
    duplicate_of: Text | None = None

    @model_validator(mode="after")
    def check_decision(self) -> Self:
        if self.duplicate_of is not None and self.decision.state != "exclude":
            raise ValueError("a byte copy must be excluded")
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
    relation_reason: Text


class Calculation(ContractModel):
    policy_id: Text
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
        if self.completeness.state != "complete" and self.expected_value is not None:
            raise ValueError("an expected value requires complete coverage")
        if self.derived_mismatch and self.root_issue_id is None:
            raise ValueError("a derived mismatch requires a root issue")
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
        for row in self.rows:
            self._check_row_refs(row, report, documents, evidence)
            if row.root_issue_id is not None and row.root_issue_id not in primary:
                raise ValueError("row root issue must refer to a primary issue in this result")
        for issue in self.summary.primary_issues:
            _require_refs(issue.evidence_refs, evidence)
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
    ) -> None:
        observed = _require_refs(row.reported_evidence_refs, evidence, "reported_value")
        if any(item.document_id != report.id for item in observed):
            raise ValueError("reported evidence must come from the selected report")
        if observed and not _is_admitted(report):
            raise ValueError("reported evidence requires an admitted report")
        if row.reported_value is not None and not any(
            _matching_amount(item, row.unit, row.reported_value) for item in observed
        ):
            raise ValueError("reported evidence must confirm the reported value and unit")
        if row.completeness.basis == "dataset_fixture" and not self.synthetic:
            raise ValueError("dataset fixture coverage requires a synthetic result")
        _require_refs(row.completeness.evidence_refs, evidence)
        for reason in row.reasons:
            _require_refs(reason.evidence_refs, evidence)
        used_addresses: set[tuple[str, str]] = set()
        for component in row.calculation.components:
            amounts = _require_refs(component.amount_refs, evidence, "amount")
            _require_refs(component.contract_refs, evidence, "contract")
            _require_refs(component.period_refs, evidence, "period")
            _require_refs(component.article_refs, evidence, "article")
            if not any(_matching_amount(item, row.unit, component.amount) for item in amounts):
                raise ValueError("amount evidence must confirm the component value and unit")
            addresses = set()
            for item in amounts:
                document = documents[item.document_id]
                if document.role != "support" or not _is_admitted(document):
                    raise ValueError("components require admitted supporting documents")
                addresses.add((document.id, item.locator.model_dump_json(exclude_none=True)))
            if used_addresses & addresses:
                raise ValueError("an amount evidence address must not be counted twice in a row")
            used_addresses.update(addresses)


def _is_admitted(document: SourceDocument) -> bool:
    return document.decision.state == "include" and document.parse_status in ("parsed", "partial")


def _matching_amount(item: Evidence, unit: str, amount: str) -> bool:
    value = item.normalized_value
    return isinstance(value, str) and item.unit == unit and Decimal(value) == Decimal(amount)


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
        return self

"""Pydantic source of the doccheck-check-result/1 contract."""

import re
from collections import Counter, defaultdict
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
    "reported_value", "amount", "contract", "period", "article", "document_identity", "stage"
]
_DECIMAL_PATTERN = re.compile(r"^-?[0-9]+(?:\.[0-9]+)?(?![\s\S])")
_RUB_PATTERN = re.compile(r"^(?!-0+\.00(?![\s\S]))-?[0-9]+\.[0-9]{2}(?![\s\S])")
DecimalText = Annotated[str, StringConstraints(strict=True, pattern=_DECIMAL_PATTERN)]
RubAmount = Annotated[str, StringConstraints(strict=True, pattern=_RUB_PATTERN)]
Percent = Annotated[str, StringConstraints(strict=True, pattern=r"^(?:100\.0|[0-9]{1,2}\.[0-9])$")]
_RUB_SCHEMA = {"type": "string", "pattern": _RUB_PATTERN.pattern}
_DECIMAL_FIELDS = ("reported_value", "expected_value", "observed_evidence_sum", "delta")
_COMPLETED_JOB_STATES = ("completed", "completed_with_issues")
_UNSUPPORTED_FORMAT = "unsupported_format"
PageLine = tuple[str, int, int]
ReadingKind = Literal["numeric", "contract", "period", "article", "document_identity", "stage"]
DateBounds = tuple[str | None, str | None]
Reading = tuple[str | None, Decimal | str | DateBounds]
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
                {
                    "if": {
                        "required": ["duplicate_of"],
                        "properties": {"duplicate_of": {"type": "string"}},
                    },
                    "then": {
                        "properties": {"decision": {"properties": {"state": {"const": "exclude"}}}}
                    },
                },
                {
                    "if": {"properties": {"format": {"type": "null"}}},
                    "then": {
                        "properties": {
                            "errors": {
                                "contains": {
                                    "required": ["code"],
                                    "properties": {"code": {"const": _UNSUPPORTED_FORMAT}},
                                }
                            }
                        }
                    },
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
            error.code == _UNSUPPORTED_FORMAT for error in self.errors
        ):
            raise ValueError("an unknown format requires an unsupported_format error")
        return self


class Period(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "anyOf": [
                {"properties": {"start": {"type": "string"}}},
                {"properties": {"end": {"type": "string"}}},
            ]
        }
    )

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


def _reading(item: Evidence) -> tuple[ReadingKind, Reading]:
    value = item.normalized_value
    if isinstance(value, Period):
        return "period", (None, (value.start, value.end))
    if item.kind in ("amount", "reported_value"):
        return "numeric", (item.unit, Decimal(value))
    return item.kind, (None, value)


class _EvidenceIndex:
    def __init__(self, evidence: list[Evidence]) -> None:
        parents = {item.id: item.id for item in evidence}
        addresses: dict[tuple[str, AddressKey], str] = {}

        def representative(evidence_id: str) -> str:
            while parents[evidence_id] != evidence_id:
                parents[evidence_id] = parents[parents[evidence_id]]
                evidence_id = parents[evidence_id]
            return evidence_id

        for item in evidence:
            for key in item.locator.address_keys():
                previous = addresses.setdefault((item.document_id, key), item.id)
                parents[representative(item.id)] = representative(previous)

        exact_groups: dict[PageLine, set[str]] = defaultdict(set)
        line_only: dict[str, PageLine] = {}
        for item in evidence:
            locator = item.locator
            if isinstance(locator, PageLocator) and locator.line is not None:
                line = (item.document_id, locator.page, locator.line)
                if ("line", locator.page, locator.line) in locator.address_keys():
                    line_only[item.id] = line
                else:
                    exact_groups[line].add(representative(item.id))

        # A line can stand for a single exact group. Several groups need finer addresses.
        self.ambiguous_lines: set[str] = set()
        for evidence_id, line in line_only.items():
            groups = exact_groups[line]
            if len(groups) > 1:
                self.ambiguous_lines.add(evidence_id)
            elif groups:
                parents[representative(evidence_id)] = next(iter(groups))
        self.groups = {item.id: representative(item.id) for item in evidence}

        self.readings: dict[tuple[ReadingKind, str], set[Reading]] = defaultdict(set)
        for item in evidence:
            kind, reading = _reading(item)
            self.readings[kind, self.groups[item.id]].add(reading)

    def values(self, evidence_id: str, kind: ReadingKind) -> set[Reading]:
        if evidence_id in self.ambiguous_lines:
            raise ValueError(
                "a line with several exact fragments requires a precise evidence address"
            )
        return self.readings[kind, self.groups[evidence_id]]

    def period_bounds(
        self,
        evidence_id: str,
        message: str = "component scope evidence must agree at its canonical address",
    ) -> DateBounds:
        # An absent bound does not contradict an observed bound.
        dates = [
            value for _, value in self.values(evidence_id, "period") if isinstance(value, tuple)
        ]
        starts = {start for start, _ in dates if start is not None}
        ends = {end for _, end in dates if end is not None}
        start = next(iter(starts), None)
        end = next(iter(ends), None)
        if len(starts) > 1 or len(ends) > 1 or (start and end and start > end):
            raise ValueError(message)
        return start, end


class Completeness(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"basis": {"const": "none"}}},
            "then": {"properties": {"state": {"const": "unknown"}}},
        }
    )

    state: Literal["complete", "incomplete", "unknown"]
    basis: Literal["manifest", "user_declaration", "dataset_fixture", "uploaded_package", "none"]
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

    def admitted_sum(
        self, *, unit: str, completeness: Completeness
    ) -> tuple[str | None, str | None]:
        """Return observed and expected sums for components admitted in one unit."""
        if self.operation != "sum":
            raise ValueError("calculation requires the sum operation")
        amounts = [component.amount for component in self.components]
        _check_amount_unit(unit, amounts)
        if not amounts:
            zero_for_missing = (
                unit == "RUB"
                and completeness.state == "complete"
                and completeness.basis == "uploaded_package"
            )
            return None, "0.00" if zero_for_missing else None
        observed = format(_sum_exact_amounts(amounts), "f")
        return observed, observed if completeness.state == "complete" else None


def _check_amount_unit(unit: str, amounts: list[str]) -> None:
    if unit == "RUB" and any(not _RUB_PATTERN.fullmatch(value) for value in amounts):
        raise ValueError("RUB values must be decimal strings in kopecks")


def _exact_units(value: str, places: int) -> int:
    """Convert a validated decimal string to an integer at a common precision."""
    numerator, denominator = Decimal(value).as_integer_ratio()
    return numerator * 10**places // denominator


def _sum_exact_amounts(amounts: list[str]) -> Decimal:
    places = max(len(amount.partition(".")[2]) for amount in amounts)
    total = sum(_exact_units(amount, places) for amount in amounts)
    sign, digits, _ = Decimal(total).as_tuple()
    return Decimal((sign, digits, -places))


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
                    "if": {"properties": {"status": {"const": "discrepancy"}}},
                    "then": {"properties": {"reasons": {"minItems": 1}}},
                },
                {
                    "if": {"properties": {"reported_value": {"type": "string"}}},
                    "then": {"properties": {"reported_evidence_refs": {"minItems": 1}}},
                },
                {
                    "if": {
                        "properties": {
                            "calculation": {"properties": {"components": {"minItems": 1}}}
                        }
                    },
                    "then": {"properties": {"observed_evidence_sum": {"type": "string"}}},
                    "else": {"properties": {"observed_evidence_sum": {"type": "null"}}},
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
                            "calculation": {
                                "required": ["operation"],
                                "properties": {"operation": {"const": "sum"}},
                            },
                        },
                        "anyOf": [
                            {
                                "properties": {
                                    "calculation": {"properties": {"components": {"minItems": 1}}}
                                }
                            },
                            {
                                "properties": {
                                    "unit": {"const": "RUB"},
                                    "expected_value": {"const": "0.00"},
                                    "completeness": {
                                        "properties": {
                                            "basis": {"const": "uploaded_package"},
                                        }
                                    },
                                    "calculation": {"properties": {"components": {"maxItems": 0}}},
                                }
                            },
                        ],
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
    is_aggregate: StrictBool | None = Field(default=None, exclude_if=lambda value: value is None)
    parent_row_id: Text | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def check_totals(self) -> Self:
        totals = (self.reported_value, self.expected_value, self.observed_evidence_sum, self.delta)
        components = [component.amount for component in self.calculation.components]
        values = [value for value in totals if value is not None] + components
        _check_amount_unit(self.unit, values)
        if components:
            observed = self.observed_evidence_sum
            if observed is None or Decimal(observed) != _sum_exact_amounts(components):
                raise ValueError("observed sum must equal the sum of admitted components")
        elif self.observed_evidence_sum is not None:
            raise ValueError("observed sum must be null without admitted components")
        if self.reported_value is not None and not self.reported_evidence_refs:
            raise ValueError("a reported value requires evidence")
        if self.expected_value is not None:
            if self.completeness.state != "complete":
                raise ValueError("an expected value requires complete coverage")
            if self.calculation.operation != "sum":
                raise ValueError("an expected value requires a supported calculation with evidence")
            _, expected = self.calculation.admitted_sum(
                unit=self.unit, completeness=self.completeness
            )
            if expected is None:
                raise ValueError("an expected value requires a supported calculation with evidence")
            if Decimal(self.expected_value) != Decimal(expected):
                raise ValueError("an expected sum must equal the sum of admitted components")
        if self.derived_mismatch and (self.status != "discrepancy" or self.root_issue_id is None):
            raise ValueError("a derived mismatch requires a discrepancy and a root issue")
        if self.status == "unverified":
            if self.delta is not None or not self.reasons:
                raise ValueError("an unverified row requires a reason and null delta")
            return self
        if self.reported_value is None or self.expected_value is None or self.delta is None:
            raise ValueError("a checked row requires reported value, expected value and delta")
        places = max(len(value.partition(".")[2]) for value in values)
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


class RubCoverage(ContractModel):
    """Amounts reported in the KFZ, in RUB, for the additive rows with known values."""

    total: RubAmount
    verified: RubAmount | None
    discrepancy: RubAmount | None
    unverified: RubAmount | None
    shares: dict[RowStatus, Percent] | None


class Summary(ContractModel):
    counts: StatusCounts
    primary_issues: list[PrimaryIssue]
    conclusion: Text
    rub_coverage: RubCoverage | None = Field(default=None, exclude_if=lambda value: value is None)


class CheckResult(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "if": {"properties": {"synthetic": {"const": False}}},
            "then": {
                "properties": {
                    "rows": {
                        "items": {
                            "properties": {
                                "completeness": {
                                    "properties": {"basis": {"not": {"const": "dataset_fixture"}}}
                                }
                            }
                        }
                    }
                }
            },
        }
    )

    schema_version: Literal[RESULT_SCHEMA_VERSION]
    run_id: Text
    synthetic: StrictBool
    report_number: Text | None = Field(default=None, exclude_if=lambda value: value is None)
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
        rows_by_id = {row.id: row for row in self.rows}
        if len(rows_by_id) != len(self.rows):
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
        addresses = _EvidenceIndex(self.evidence)
        for row in self.rows:
            if row.parent_row_id is not None:
                parent = rows_by_id.get(row.parent_row_id)
                if parent is None or parent.parent_row_id is not None or parent.unit != row.unit:
                    raise ValueError("a detail must reference a top-level row with the same unit")
            self._check_row_refs(row, report, documents, evidence, addresses)
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
        addresses: _EvidenceIndex,
    ) -> None:
        observed = _require_refs(row.reported_evidence_refs, evidence, "reported_value")
        if any(item.document_id != report.id for item in observed):
            raise ValueError("reported evidence must come from the selected report")
        if observed and not _is_admitted(report):
            raise ValueError("reported evidence requires an admitted report")
        if row.reported_value is not None:
            _check_amount_readings(observed, row.unit, row.reported_value, addresses, "reported")
        if row.completeness.basis == "dataset_fixture" and not self.synthetic:
            raise ValueError("dataset fixture coverage requires a synthetic result")
        coverage = _require_refs(row.completeness.evidence_refs, evidence)
        if row.completeness.state == "complete" and any(
            not _is_admitted(documents[item.document_id]) for item in coverage
        ):
            raise ValueError("complete coverage cannot rely on an inadmissible document")
        for reason in row.reasons:
            _require_refs(reason.evidence_refs, evidence)
        used_groups: set[str] = set()
        for component in row.calculation.components:
            amounts = _require_refs(component.amount_refs, evidence, "amount")
            _check_amount_readings(amounts, row.unit, component.amount, addresses, "component")
            for item in amounts:
                document = documents[item.document_id]
                if document.role != "support" or not _is_admitted(document):
                    raise ValueError("components require admitted supporting documents")
            self._check_component_scope(component, row, amounts, documents, evidence, addresses)
            groups = {addresses.groups[item.id] for item in amounts}
            if used_groups & groups:
                raise ValueError("an amount evidence address must not be counted twice in a row")
            used_groups.update(groups)
        if row.completeness.state == "complete":
            message = "complete coverage evidence must agree at its canonical address"
            for item in coverage:
                kind, _ = _reading(item)
                if kind == "period":
                    addresses.period_bounds(item.id, message)
                elif len(addresses.values(item.id, kind)) != 1:
                    raise ValueError(message)

    def _check_component_scope(
        self,
        component: Component,
        row: ResultRow,
        amounts: list[Evidence],
        documents: dict[str, SourceDocument],
        evidence: dict[str, Evidence],
        addresses: _EvidenceIndex,
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
                if len(addresses.values(item.id, "document_identity")) != 1:
                    raise ValueError(
                        "document identity evidence must agree at its canonical address"
                    )
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
        if any(len(addresses.values(item.id, "contract")) != 1 for item in contracts) or any(
            len(addresses.values(item.id, "article")) != 1 for item in articles
        ):
            raise ValueError("component scope evidence must agree at its canonical address")
        separate_sources = {item.document_id for item in scope_evidence} - sources
        for source in separate_sources:
            common_identity &= identities.get(source, set())
        if separate_sources and not common_identity:
            raise ValueError("separate scope evidence requires a shared source identity")
        if any(item.normalized_value != self.scope.contract_number for item in contracts):
            raise ValueError("contract evidence contradicts the selected contract")
        bounds = [addresses.period_bounds(item.id) for item in periods]
        for start, end in bounds:
            if (start is not None and start > self.scope.period_end) or (
                end is not None and end < self.scope.period_start
            ):
                raise ValueError("period evidence lies outside the selected period")
        latest_start = max((start for start, _ in bounds if start is not None), default=None)
        earliest_end = min((end for _, end in bounds if end is not None), default=None)
        if latest_start is not None and earliest_end is not None and latest_start > earliest_end:
            raise ValueError("period evidence for one component has incompatible bounds")
        if row.indicator_code is not None and any(
            item.normalized_value != row.indicator_code for item in articles
        ):
            raise ValueError("article evidence contradicts the indicator code")


def _is_admitted(document: SourceDocument) -> bool:
    return document.decision.state == "include" and document.parse_status in ("parsed", "partial")


def _check_amount_readings(
    evidence: list[Evidence],
    unit: str,
    amount: str,
    addresses: _EvidenceIndex,
    role: Literal["reported", "component"],
) -> None:
    expected = {(unit, Decimal(amount))}
    if not evidence or any(addresses.values(item.id, "numeric") != expected for item in evidence):
        raise ValueError(f"{role} evidence must agree on value and unit at its canonical address")


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

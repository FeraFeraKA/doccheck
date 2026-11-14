"""Build the result summary from already calculated findings."""

from collections import Counter, defaultdict
from collections.abc import Sequence

from doccheck_backend.contracts.result import (
    CheckResult,
    PrimaryIssue,
    ResultRow,
    RowStatus,
    RubCoverage,
    Scope,
    SourceDocument,
    StatusCounts,
    Summary,
    _EvidenceIndex,
    _exact_units,
    _sum_exact_amounts,
)

_BASIS_LABELS = {
    "manifest": "манифест документов",
    "user_declaration": "заявление пользователя",
    "dataset_fixture": "профиль синтетического набора",
    "uploaded_package": "загруженный комплект",
    "none": "основание не установлено",
}
_COVERAGE_LABELS = {
    "complete": "Полное покрытие",
    "incomplete": "Неполное покрытие",
    "unknown": "Неизвестное покрытие",
}


def build_summary(
    scope: Scope,
    rows: Sequence[ResultRow],
    documents: Sequence[SourceDocument],
    primary_issues: Sequence[PrimaryIssue],
) -> Summary:
    """Describe validated rows and preserve issue IDs for CheckResult validation."""
    by_status = Counter(row.status for row in rows)
    counts = StatusCounts(
        verified=by_status["verified"],
        discrepancy=by_status["discrepancy"],
        unverified=by_status["unverified"],
    )
    sentences = [
        f"Область сверки — договор {scope.contract_number}, "
        f"период {scope.period_start} — {scope.period_end}."
    ]
    if not rows:
        sentences.append("Показатели для проверки отсутствуют.")
    else:
        sentences.append(
            f"Подтверждено {counts.verified}, с расхождениями {counts.discrepancy}, "
            f"не проверено {counts.unverified}."
        )
        coverage = Counter((row.completeness.state, row.completeness.basis) for row in rows)
        for state, label in _COVERAGE_LABELS.items():
            entries = [
                f"{basis_label} — {coverage[state, basis]}"
                for basis, basis_label in _BASIS_LABELS.items()
                if coverage[state, basis]
            ]
            if entries:
                sentences.append(f"{label} ({', '.join(entries)}).")

    exclusions = sum(document.decision.state == "exclude" for document in documents)
    documents_with_errors = sum(bool(document.errors) for document in documents)
    sentences.append(
        f"Исключено документов {exclusions}, документов с ошибками {documents_with_errors}."
    )
    if primary_issues:
        sentences.append(f"Первичных замечаний {len(primary_issues)}.")
    return Summary(
        counts=counts,
        primary_issues=[issue.model_copy(deep=True) for issue in primary_issues],
        conclusion=" ".join(sentences),
    )


def build_rub_coverage(result: CheckResult) -> RubCoverage | None:
    """Summarize reported article amounts without counting totals or their breakdowns."""
    amounts: dict[RowStatus, list[str]] = defaultdict(list)
    seen_sources: set[str] = set()
    sources = _EvidenceIndex(result.evidence)
    for row in result.rows:
        if (
            row.unit != "RUB"
            or row.reported_value is None
            or row.derived_mismatch
            or row.parent_row_id is not None
        ):
            continue
        if row.is_aggregate is None:
            return None
        if row.is_aggregate:
            continue
        # If an address appears again, the reported figures do not form an additive set.
        addresses = {sources.groups[ref] for ref in row.reported_evidence_refs}
        if seen_sources.intersection(addresses):
            return None
        seen_sources.update(addresses)
        amounts[row.status].append(row.reported_value)

    values = [amount for items in amounts.values() for amount in items]
    if not values:
        return None

    subtotals = {status: _sum_exact_amounts(items) for status, items in amounts.items()}
    total = _sum_exact_amounts(values)
    shares = None
    if total > 0 and not any(value < 0 for value in subtotals.values()):
        cents = _exact_units(format(total, "f"), 2)
        shares = {}
        for status, value in subtotals.items():
            subtotal = _exact_units(format(value, "f"), 2)
            tenths = (2 * subtotal * 1000 + cents) // (2 * cents)
            shares[status] = f"{tenths // 10}.{tenths % 10}"

    return RubCoverage(
        total=format(total, "f"),
        verified=format(subtotals["verified"], "f") if "verified" in subtotals else None,
        discrepancy=format(subtotals["discrepancy"], "f") if "discrepancy" in subtotals else None,
        unverified=format(subtotals["unverified"], "f") if "unverified" in subtotals else None,
        shares=shares,
    )

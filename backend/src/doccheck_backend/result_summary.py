"""Build the result summary from already calculated findings."""

from collections import Counter
from collections.abc import Sequence

from doccheck_backend.contracts.result import (
    PrimaryIssue,
    ResultRow,
    Scope,
    SourceDocument,
    StatusCounts,
    Summary,
)

_BASIS_LABELS = {
    "manifest": "манифест документов",
    "user_declaration": "заявление пользователя",
    "dataset_fixture": "профиль синтетического набора",
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

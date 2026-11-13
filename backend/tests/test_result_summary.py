from pathlib import Path

import pytest

from doccheck_backend.contracts import CheckJob, CheckResult
from doccheck_backend.contracts.result import ResultRow
from doccheck_backend.result_summary import build_summary

_FIXTURE = Path(__file__).resolve().parents[2] / "contracts/check-result.v1.synthetic.json"


@pytest.fixture
def result() -> CheckResult:
    job = CheckJob.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))
    assert job.result is not None
    return job.result


def test_empty_result_never_implies_confirmation(result: CheckResult) -> None:
    summary = build_summary(result.scope, [], result.documents, [])

    assert summary.counts.model_dump() == {"verified": 0, "discrepancy": 0, "unverified": 0}
    assert summary.primary_issues == []
    assert "Показатели для проверки отсутствуют." in summary.conclusion
    assert "Подтверждено" not in summary.conclusion


def test_summary_keeps_scope_and_unknown_coverage_visible(result: CheckResult) -> None:
    finding = result.rows[1].model_dump(mode="json")
    finding["completeness"] = {
        "state": "unknown",
        "basis": "none",
        "reason": "Состав неизвестен",
        "evidence_refs": [],
    }
    row = ResultRow.model_validate(finding)
    summary = build_summary(result.scope, [row], result.documents, result.summary.primary_issues)

    assert summary.counts.model_dump() == {"verified": 0, "discrepancy": 0, "unverified": 1}
    assert row.reported_value == "0.00" and row.expected_value is None and row.delta is None
    assert result.scope.contract_number in summary.conclusion
    assert f"{result.scope.period_start} — {result.scope.period_end}" in summary.conclusion
    assert "Неизвестное покрытие (основание не установлено — 1)" in summary.conclusion
    assert "Исключено документов 1, документов с ошибками 1." in summary.conclusion
    assert "0.00" not in summary.conclusion


def test_summary_distinguishes_swapped_coverage_bases(result: CheckResult) -> None:
    conclusions = []
    for complete_basis, incomplete_basis in (
        ("manifest", "user_declaration"),
        ("user_declaration", "manifest"),
    ):
        findings = result.model_dump(mode="json")
        findings["rows"][0]["completeness"].update(
            basis=complete_basis, reason="Проверено основание полноты синтетической статьи A"
        )
        findings["rows"][1]["completeness"].update(
            basis=incomplete_basis, reason="Проверено основание неполноты синтетической статьи B"
        )
        validated = CheckResult.model_validate(findings)
        summary = build_summary(
            validated.scope, validated.rows, validated.documents, validated.summary.primary_issues
        )
        assert summary.counts == result.summary.counts
        conclusions.append(summary.conclusion)

    first, second = conclusions
    assert first != second
    assert "Полное покрытие (манифест документов — 1)" in first
    assert "Неполное покрытие (заявление пользователя — 1)" in first
    assert "Полное покрытие (заявление пользователя — 1)" in second
    assert "Неполное покрытие (манифест документов — 1)" in second


def test_summary_counts_rows_and_preserves_one_issue_for_two_linked_rows(
    result: CheckResult,
) -> None:
    findings = result.model_dump(mode="json")
    original, incomplete = result.rows
    affected = original.model_dump(mode="json")
    affected.update(id="derived-synthetic", label="Зависимая строка", derived_mismatch=True)
    verified = original.model_dump(mode="json")
    verified["id"] = "verified-synthetic"
    verified["reported_value"] = original.expected_value
    verified["reported_evidence_refs"] = ["report-confirmed"]
    verified.update(status="verified", delta="0.00", root_issue_id=None, reasons=[])
    verified["completeness"]["basis"] = "user_declaration"
    reported = findings["evidence"][0]
    findings["evidence"].append(
        {
            **reported,
            "id": "report-confirmed",
            "raw_value": original.expected_value,
            "normalized_value": original.expected_value,
            "locator": {"kind": "page", "page": 1, "line": 50},
        }
    )
    rows = [
        original,
        ResultRow.model_validate(affected),
        incomplete,
        ResultRow.model_validate(verified),
    ]
    summary = build_summary(result.scope, rows, result.documents, result.summary.primary_issues)
    findings["rows"] = [row.model_dump(mode="json") for row in rows]
    findings["summary"] = summary.model_dump(mode="json")
    validated = CheckResult.model_validate(findings)

    assert validated.summary.counts.model_dump() == {
        "verified": 1,
        "discrepancy": 2,
        "unverified": 1,
    }
    assert validated.rows[0].root_issue_id == validated.rows[1].root_issue_id == "issue-a"
    assert [issue.id for issue in validated.summary.primary_issues] == ["issue-a", "issue-b"]
    assert validated.summary.primary_issues[1].file_error_refs == ["scan-read-error"]
    assert validated.summary.primary_issues[0].evidence_refs == ["report-a", "amount-1", "amount-2"]
    assert validated.rows[0].delta == validated.rows[1].delta == original.delta
    assert "заявление пользователя" in summary.conclusion
    assert "Первичных замечаний 2." in summary.conclusion
    assert original.delta is not None and original.delta not in summary.conclusion

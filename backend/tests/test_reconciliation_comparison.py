from decimal import localcontext
from pathlib import Path

import pytest

from doccheck_backend.contracts import CheckJob, CheckResult
from doccheck_backend.contracts.result import Completeness
from doccheck_backend.reconciliation_comparison import compare_admitted_values

_FIXTURE = Path(__file__).resolve().parents[2] / "contracts/check-result.v1.synthetic.json"


def coverage(state: str) -> Completeness:
    return Completeness.model_validate(
        {
            "state": state,
            "basis": "none" if state == "unknown" else "dataset_fixture",
            "reason": "Синтетическое условие проверки",
            "evidence_refs": [],
        }
    )


@pytest.mark.parametrize(
    ("reported", "expected", "status", "delta"),
    [
        ("0.00", "0.00", "verified", "0.00"),
        ("0.00", "-0.05", "discrepancy", "0.05"),
        ("150.49", "150.50", "discrepancy", "-0.01"),
        ("-12.00", "-12.01", "discrepancy", "0.01"),
        ("3.300", "3.30", "verified", "0.000"),
        ("1.234", "1.2301", "discrepancy", "0.0039"),
    ],
)
def test_compares_exact_decimal_strings(reported, expected, status, delta) -> None:
    assert compare_admitted_values(reported, expected, coverage("complete"), comparable=True) == (
        status,
        delta,
    )


@pytest.mark.parametrize(
    ("reported", "expected", "state", "comparable"),
    [
        (None, "0.00", "complete", True),
        ("0.00", None, "complete", True),
        ("150.50", "150.50", "incomplete", True),
        ("150.50", "0.00", "unknown", True),
        ("150.50", "150.50", "complete", False),
    ],
)
def test_missing_or_incomparable_inputs_have_no_delta(
    reported, expected, state, comparable
) -> None:
    assert compare_admitted_values(reported, expected, coverage(state), comparable=comparable) == (
        "unverified",
        None,
    )


def test_comparison_preserves_precision_beyond_current_decimal_context() -> None:
    reported = "99999999999999999999999999999999999.10"
    with localcontext() as context:
        context.prec = 2
        context.Emax = 3
        assert compare_admitted_values(
            reported, "-0.90", coverage("complete"), comparable=True
        ) == (
            "discrepancy",
            "100000000000000000000000000000000000.00",
        )


def test_comparison_with_changed_report_evidence_validates_against_contract() -> None:
    job = CheckJob.model_validate_json(_FIXTURE.read_text(encoding="utf-8"))
    assert job.result is not None
    original = job.result.rows[0]
    payload = job.result.model_dump(mode="json")
    row = payload["rows"][0]
    evidence = next(item for item in payload["evidence"] if item["id"] == "report-a")
    row["reported_value"] = evidence["normalized_value"] = "149.49"
    evidence["raw_value"] = "149,49"
    row["status"], row["delta"] = compare_admitted_values(
        row["reported_value"], original.expected_value, original.completeness, comparable=True
    )
    checked = CheckResult.model_validate(payload).rows[0]

    assert (checked.status, checked.delta) == ("discrepancy", "28.99")
    assert checked.reported_evidence_refs == original.reported_evidence_refs

from decimal import localcontext

import pytest
from test_result_contract import payload as payload

from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Calculation, Completeness


def test_admitted_sum_preserves_original_components_in_saved_result(payload: dict) -> None:
    row = payload["result"]["rows"][0]
    calculation = Calculation.model_validate(row["calculation"])
    completeness = Completeness.model_validate(row["completeness"])
    observed, expected = calculation.admitted_sum(unit=row["unit"], completeness=completeness)
    assert (observed, expected) == ("120.50", "120.50")

    row.update(observed_evidence_sum=observed, expected_value=expected)
    result = CheckJob.model_validate(payload).result
    assert result is not None
    assert result.rows[0].calculation == calculation
    assert calculation.policy_id == "demo-sum/1"
    assert [component.amount_refs for component in calculation.components] == [
        ["amount-1"],
        ["amount-2"],
    ]


@pytest.mark.parametrize(
    ("state", "amounts", "sums"),
    [
        ("complete", ("0.10", "-0.10"), ("0.00", "0.00")),
        ("complete", ("-0.11", "0.10"), ("-0.01", "-0.01")),
        ("incomplete", ("0.01", "0.02"), ("0.03", None)),
        ("unknown", ("0.01", "0.02"), ("0.03", None)),
        ("complete", (), (None, None)),
    ],
)
def test_admitted_sum_requires_components_and_coverage_for_expected(
    payload: dict,
    state: str,
    amounts: tuple[str, ...],
    sums: tuple[str | None, str | None],
) -> None:
    row = payload["result"]["rows"][0]
    raw_calculation = row["calculation"]
    components = raw_calculation["components"]
    raw_calculation["components"] = [
        {**component, "amount": amount} for component, amount in zip(components, amounts)
    ]
    calculation = Calculation.model_validate(raw_calculation)
    completeness = Completeness.model_validate({**row["completeness"], "state": state})
    with localcontext() as context:
        context.prec = 1
        assert calculation.admitted_sum(unit="RUB", completeness=completeness) == sums


def test_admitted_sum_preserves_non_rub_scale_without_applying_rounding(payload: dict) -> None:
    row = payload["result"]["rows"][0]
    raw_calculation = row["calculation"]
    raw_calculation["components"][0]["amount"] = "0.001"
    raw_calculation["components"][1]["amount"] = "2"
    calculation = Calculation.model_validate(raw_calculation)
    completeness = Completeness.model_validate(row["completeness"])

    assert calculation.admitted_sum(unit="hours", completeness=completeness) == ("2.001", "2.001")
    with pytest.raises(ValueError, match="RUB values must be decimal strings in kopecks"):
        calculation.admitted_sum(unit="RUB", completeness=completeness)


def test_admitted_sum_rejects_an_unspecified_operation(payload: dict) -> None:
    row = payload["result"]["rows"][0]
    calculation = Calculation.model_validate({**row["calculation"], "operation": None})
    completeness = Completeness.model_validate(row["completeness"])
    with pytest.raises(ValueError, match="requires the sum operation"):
        calculation.admitted_sum(unit="RUB", completeness=completeness)

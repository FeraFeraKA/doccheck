import pytest
from pydantic import ValidationError
from test_result_contract import payload as payload

from doccheck_backend.contracts import CheckJob


def test_opposite_large_rub_components_keep_the_remainder_in_kopecks(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    evidence = {item["id"]: item for item in result["evidence"]}

    # The whole rubles cancel: 47 - 12 = 35 kopecks. The report is 10 kopecks lower.
    readings = {
        "amount-1": "123456789012345678901234567890.47",
        "amount-2": "-123456789012345678901234567890.12",
        "report-a": "0.25",
    }
    for item_id, value in readings.items():
        evidence[item_id].update(raw_value=value, normalized_value=value)
    for component in row["calculation"]["components"]:
        (amount_ref,) = component["amount_refs"]
        component["amount"] = readings[amount_ref]
    row.update(
        reported_value="0.25", observed_evidence_sum="0.35", expected_value="0.35", delta="-0.10"
    )

    job = CheckJob.model_validate(payload)
    assert job.result is not None
    checked = job.result.rows[0]
    assert (checked.observed_evidence_sum, checked.delta, checked.status) == (
        "0.35",
        "-0.10",
        "discrepancy",
    )

    row.update(observed_evidence_sum="0.00", expected_value="0.00", delta="0.25")
    with pytest.raises(
        ValidationError, match="observed sum must equal the sum of admitted components"
    ):
        CheckJob.model_validate(payload)

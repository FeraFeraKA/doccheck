import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from doccheck_backend.contracts import RESULT_SCHEMA_VERSION, CheckJob, CheckResult
from doccheck_backend.contracts.locators import PageLocator, SheetLocator

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
EXAMPLE = CONTRACTS / "check-result.v1.synthetic.json"
SCHEMA = CONTRACTS / "check-result.v1.schema.json"


@pytest.fixture
def payload() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_checked_in_schema_matches_models_and_example_round_trips(payload: dict) -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema == CheckJob.model_json_schema()
    result_schema = schema["$defs"]["CheckResult"]
    assert result_schema["properties"]["schema_version"]["const"] == RESULT_SCHEMA_VERSION
    assert result_schema["properties"] == CheckResult.model_json_schema()["properties"]
    job = CheckJob.model_validate_json(EXAMPLE.read_text(encoding="utf-8"))
    assert job.result is not None and job.result.synthetic is True
    assert job.status == "completed_with_issues"
    discrepancy, incomplete = job.result.rows
    assert discrepancy.status == "discrepancy" and discrepancy.delta == "30.00"
    assert [component.amount for component in discrepancy.calculation.components] == [
        "60.25",
        "60.25",
    ]
    assert discrepancy.observed_evidence_sum == "120.50"
    assert incomplete.reported_value == "0.00"
    assert incomplete.expected_value is None and incomplete.observed_evidence_sum is None
    assert CheckJob.model_validate_json(job.model_dump_json()) == CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    "value", [1, 1.2, True, "1", "1.2", "-0.00", "1,20", "1e2", "NaN", "1.00\n"]
)
def test_rub_requires_a_decimal_string_in_kopecks(payload: dict, value: object) -> None:
    payload["result"]["rows"][0]["reported_value"] = value
    with pytest.raises(ValidationError):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    "fragment",
    [
        {},
        {"bbox": None},
        {"line": 0},
        {"line": "1"},
        {"table_row": 1},
        {"table_row": 1, "line": 1},
        {"bbox": [0.1, 0.1, 0.1, 0.4]},
        {"bbox": [-0.1, 0, 1, 1]},
        {"bbox": [0, 0, 1.1, 1]},
        {"bbox": [0, 0, 1, float("nan")]},
    ],
)
def test_page_evidence_requires_a_valid_fragment(fragment: dict) -> None:
    with pytest.raises(ValidationError):
        PageLocator.model_validate({"kind": "page", "page": 1, **fragment})


@pytest.mark.parametrize("cell", ["A0", "1A", "A2:A1", "XFE1", "A1048577", "C6\n"])
def test_xlsx_range_requires_ordered_cells_inside_a_worksheet(cell: str) -> None:
    with pytest.raises(ValidationError):
        SheetLocator.model_validate({"kind": "sheet", "sheet": "Demo", "range": cell})


def test_xlsx_range_of_one_cell_has_the_same_address_as_the_cell() -> None:
    cell = SheetLocator(kind="sheet", sheet="Demo", range="C6")
    same_cell = SheetLocator(kind="sheet", sheet="Demo", range="C6:C6")
    assert same_cell.model_dump_json() == cell.model_dump_json()
    assert SheetLocator(kind="sheet", sheet="Demo", range="C6:C7").range == "C6:C7"


@pytest.mark.parametrize(
    ("file_format", "locator"),
    [
        ("png", {"kind": "page", "page": 1, "line": 2}),
        ("docx", {"kind": "paragraph", "paragraph": 2}),
        ("docx", {"kind": "table_cell", "table": 1, "row": 2, "cell": 2}),
    ],
)
def test_accepted_source_formats(payload: dict, file_format: str, locator: dict) -> None:
    payload["result"]["documents"][0]["format"] = file_format
    for item in payload["result"]["evidence"][:2]:
        item["locator"] = locator
    assert CheckJob.model_validate(payload).result is not None


def test_png_evidence_must_point_to_page_one(payload: dict) -> None:
    payload["result"]["documents"][0]["format"] = "png"
    payload["result"]["evidence"][0]["locator"]["page"] = 2
    with pytest.raises(ValidationError, match="locator does not match"):
        CheckJob.model_validate(payload)


def test_amount_cannot_substitute_for_contract_evidence(payload: dict) -> None:
    payload["result"]["rows"][0]["calculation"]["components"][0]["contract_refs"] = ["amount-1"]
    with pytest.raises(ValidationError, match="wrong role"):
        CheckJob.model_validate(payload)


def test_copy_cannot_supply_a_second_amount(payload: dict) -> None:
    payload["result"]["evidence"][3]["document_id"] = "ledger-copy"
    with pytest.raises(ValidationError, match="admitted supporting documents"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize("address", ["C6", "C6:C6"])
def test_amount_cannot_be_counted_twice_under_different_ids(payload: dict, address: str) -> None:
    evidence = payload["result"]["evidence"]
    evidence[3]["locator"]["range"] = address
    with pytest.raises(ValidationError, match="must not be counted twice"):
        CheckJob.model_validate(payload)


def test_unreadable_support_cannot_provide_an_admitted_amount(payload: dict) -> None:
    payload["result"]["documents"][1]["parse_status"] = "error"
    with pytest.raises(ValidationError, match="admitted supporting documents"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observed_evidence_sum", "60.25", "sum of admitted components"),
        ("delta", "30.01", "delta must be reported minus expected"),
        ("root_issue_id", "elsewhere", "must refer to a primary issue"),
    ],
)
def test_row_totals_and_root_issue_must_agree(
    payload: dict, field: str, value: str, message: str
) -> None:
    payload["result"]["rows"][0][field] = value
    with pytest.raises(ValidationError, match=message):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_value", "0.00", "expected value requires complete coverage"),
        ("observed_evidence_sum", "0.00", "observed sum must be null"),
        ("delta", "0.00", "requires a reason and null delta"),
    ],
)
def test_incomplete_row_does_not_become_zero(
    payload: dict, field: str, value: str, message: str
) -> None:
    payload["result"]["rows"][1][field] = value
    with pytest.raises(ValidationError, match=message):
        CheckJob.model_validate(payload)


def test_exact_negative_decimal_and_proven_zero_are_valid(payload: dict) -> None:
    row = payload["result"]["rows"][0]
    row["calculation"]["components"][0]["amount"] = "-60.25"
    payload["result"]["evidence"][2]["normalized_value"] = "-60.25"
    row["observed_evidence_sum"] = row["expected_value"] = "0.00"
    row["delta"] = "150.50"
    job = CheckJob.model_validate(payload)
    assert job.result is not None and job.result.rows[0].observed_evidence_sum == "0.00"


def test_expected_value_must_match_the_supported_sum(payload: dict) -> None:
    result = payload["result"]
    result["rows"][0].update(expected_value="150.50", delta="0.00", status="verified", reasons=[])
    result["summary"]["counts"].update(verified=1, discrepancy=0)
    with pytest.raises(ValidationError, match="expected sum must equal"):
        CheckJob.model_validate(payload)


def test_complete_declaration_does_not_prove_zero(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][1]
    row.update(expected_value="0.00", delta="0.00", status="verified", reasons=[])
    row["completeness"].update(state="complete", basis="user_declaration")
    result["summary"]["counts"].update(verified=1, unverified=0)
    with pytest.raises(ValidationError, match="supported calculation with evidence"):
        CheckJob.model_validate(payload)


def test_unknown_operation_only_preserves_observed_sum(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    del row["calculation"]["operation"]
    with pytest.raises(ValidationError, match="supported calculation with evidence"):
        CheckJob.model_validate(payload)
    row.update(expected_value=None, delta=None, status="unverified")
    result["summary"]["counts"].update(discrepancy=0, unverified=2)
    job = CheckJob.model_validate(payload)
    assert job.result is not None and job.result.rows[0].observed_evidence_sum == "120.50"


def test_job_failure_is_distinct_from_a_discrepancy(payload: dict) -> None:
    payload["status"] = "failed"
    with pytest.raises(ValidationError, match="only a completed job"):
        CheckJob.model_validate(payload)
    payload["result"] = None
    payload["error"] = {"code": "worker_failed", "message": "Ошибка задания"}
    assert CheckJob.model_validate(payload).status == "failed"

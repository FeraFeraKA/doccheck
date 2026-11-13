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
    issue = next(
        item for item in job.result.summary.primary_issues if item.id == incomplete.root_issue_id
    )
    assert issue.file_error_refs == [job.result.documents[3].errors[0].id]
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
    first, second = payload["result"]["evidence"][:2]
    index = {"page": "line", "paragraph": "paragraph", "table_cell": "row"}[locator["kind"]]
    first["locator"] = locator
    second["locator"] = {**locator, index: locator[index] + 1}
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
    payload["result"]["rows"][0]["completeness"]["evidence_refs"] = ["amount-1"]
    with pytest.raises(ValidationError, match="admitted supporting documents"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize("address", ["C6", "C6:C6"])
def test_amount_cannot_be_counted_twice_under_different_ids(payload: dict, address: str) -> None:
    evidence = payload["result"]["evidence"]
    evidence[3]["locator"]["range"] = address
    with pytest.raises(ValidationError, match="must not be counted twice"):
        CheckJob.model_validate(payload)


def test_unreadable_support_cannot_provide_an_admitted_amount(payload: dict) -> None:
    document = payload["result"]["documents"][1]
    document["parse_status"] = "error"
    document["decision"]["state"] = "parse_error"
    document["errors"] = [{"id": "failed-ledger", "code": "read_error", "message": "Failed"}]
    payload["result"]["rows"][0]["completeness"]["evidence_refs"] = []
    for index, item in enumerate(payload["result"]["evidence"][4:], start=1):
        item.update(document_id="report", locator={"kind": "page", "page": 1, "line": index})
    with pytest.raises(ValidationError, match="admitted supporting documents"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    "address",
    [
        {"bbox": [0.2, 0.3, 0.4, 0.5], "fragment_id": "amount", "line": 2},
        {"bbox": [0.2, 0.3, 0.4, 0.5]},
        {"fragment_id": "amount"},
        {"line": 1},
    ],
)
def test_pdf_fragment_identity_ignores_additional_metadata(payload: dict, address: dict) -> None:
    result = payload["result"]
    for document in result["documents"][1:3]:
        document["format"] = "pdf"
    for index, evidence in enumerate(result["evidence"][2:], start=1):
        evidence["locator"] = {"kind": "page", "page": 1, "line": index}
    result["evidence"][2]["locator"].update(bbox=[0.2, 0.3, 0.4, 0.5], fragment_id="amount")
    result["evidence"][3]["locator"] = {"kind": "page", "page": 1, **address}
    with pytest.raises(ValidationError, match="must not be counted twice"):
        CheckJob.model_validate(payload)
    result["evidence"][3]["locator"] = {
        "kind": "page",
        "page": 1,
        "line": 1,
        "bbox": [0.5, 0.3, 0.7, 0.5],
    }
    assert CheckJob.model_validate(payload).result is not None


def test_transitive_pdf_aliases_share_readings_and_cannot_be_counted_twice(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"][1]["format"] = "pdf"
    first, second = result["evidence"][2:4]
    for index, item in enumerate(result["evidence"][4:], start=1):
        item["locator"] = {"kind": "page", "page": 1, "line": index}
    box = [0.2, 0.3, 0.4, 0.5]
    first["locator"] = {"kind": "page", "page": 1, "bbox": box, "line": 10}
    second["locator"] = {"kind": "page", "page": 1, "fragment_id": "another", "line": 10}
    bridge = {
        **first,
        "id": "amount-alias",
        "locator": {**first["locator"], "fragment_id": "same"},
    }
    alias = {
        **first,
        "id": "another-reading",
        "normalized_value": "900.50",
        "locator": {"kind": "page", "page": 1, "fragment_id": "same"},
    }
    result["evidence"].extend([bridge, alias])
    with pytest.raises(ValidationError, match="component evidence must agree"):
        CheckJob.model_validate(payload)
    alias["normalized_value"] = first["normalized_value"]
    assert CheckJob.model_validate(payload).result is not None
    row["calculation"]["components"][1]["amount_refs"] = [alias["id"]]
    with pytest.raises(ValidationError, match="must not be counted twice"):
        CheckJob.model_validate(payload)


def test_transitive_pdf_aliases_are_specific_to_the_document_and_page(payload: dict) -> None:
    result = payload["result"]
    reported = result["evidence"][0]
    reported["locator"]["fragment_id"] = "same"
    for document, page in (("report", 2), ("unreadable", 1)):
        result["evidence"].append(
            {
                **reported,
                "id": f"{document}-{page}",
                "document_id": document,
                "normalized_value": "900.50",
                "locator": {**reported["locator"], "page": page},
            }
        )
    assert CheckJob.model_validate(payload).result is not None


@pytest.mark.parametrize("reverse_evidence", [False, True])
def test_pdf_lines_connected_by_one_fragment_share_conflicts_and_duplicates(
    payload: dict, reverse_evidence: bool
) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"][1]["format"] = "pdf"
    first, second = result["evidence"][2:4]
    for index, item in enumerate(result["evidence"][4:], start=20):
        item["locator"] = {"kind": "page", "page": 1, "line": index}
    first["locator"] = {"kind": "page", "page": 1, "line": 5}
    second["locator"] = {"kind": "page", "page": 1, "line": 30}
    for alias_id, line in (("box-first", 5), ("box-last", 6)):
        result["evidence"].append(
            {
                **first,
                "id": alias_id,
                "locator": {"kind": "page", "page": 1, "line": line, "bbox": [0.1, 0.1, 0.3, 0.2]},
            }
        )
    alias = {
        **first,
        "id": "line-last",
        "locator": {"kind": "page", "page": 1, "line": 6},
        "normalized_value": "900.50",
    }
    result["evidence"].append(alias)
    if reverse_evidence:
        result["evidence"].reverse()
    with pytest.raises(ValidationError, match="component evidence must agree"):
        CheckJob.model_validate(payload)
    alias["normalized_value"] = first["normalized_value"]
    assert CheckJob.model_validate(payload).result is not None
    row["calculation"]["components"][1]["amount_refs"] = [alias["id"]]
    with pytest.raises(ValidationError, match="must not be counted twice"):
        CheckJob.model_validate(payload)


def test_pdf_line_with_multiple_exact_addresses_requires_finer_evidence(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"][1]["format"] = "pdf"
    first, second = result["evidence"][2:4]
    for index, item in enumerate(result["evidence"][4:], start=20):
        item["locator"] = {"kind": "page", "page": 1, "line": index}
    first["locator"] = {"kind": "page", "page": 1, "line": 5, "fragment_id": "first"}
    second["locator"] = {**first["locator"], "fragment_id": "second"}
    ambiguous = {
        **first,
        "id": "line-only",
        "locator": {"kind": "page", "page": 1, "line": 5},
    }
    result["evidence"].append(ambiguous)
    assert CheckJob.model_validate(payload).result.rows[0].observed_evidence_sum == "120.50"
    row["calculation"]["components"][0]["amount_refs"] = [ambiguous["id"]]
    with pytest.raises(ValidationError, match="requires a precise evidence address"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize("index", [4, 5, 6])
def test_component_scope_cannot_rely_on_unreadable_files(payload: dict, index: int) -> None:
    evidence = payload["result"]["evidence"][index]
    evidence.update(document_id="unreadable", locator={"kind": "page", "page": 1, "line": index})
    with pytest.raises(ValidationError, match="scope requires admitted documents"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (4, "OTHER", "contradicts the selected contract"),
        (5, {"start": "2025-01-01", "end": "2025-01-31"}, "lies outside the selected period"),
        (6, "DEMO-B", "contradicts the indicator code"),
    ],
)
def test_component_scope_must_match_normalized_evidence(
    payload: dict, index: int, value: object, message: str
) -> None:
    payload["result"]["evidence"][index]["normalized_value"] = value
    with pytest.raises(ValidationError, match=message):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    ("index", "alternative"),
    [(4, "OTHER"), (5, {"start": "2025-01-01", "end": None}), (6, "DEMO-B")],
)
def test_component_scope_rejects_unreferenced_conflicting_readings(
    payload: dict, index: int, alternative: object
) -> None:
    result = payload["result"]
    row = result["rows"][0]
    observed = result["evidence"][index]
    result["evidence"].append(
        {**observed, "id": "scope-alternative", "normalized_value": alternative}
    )
    with pytest.raises(ValidationError, match="component scope evidence must agree"):
        CheckJob.model_validate(payload)
    row["calculation"]["components"] = []
    row.update(
        status="unverified",
        observed_evidence_sum=None,
        expected_value=None,
        delta=None,
        root_issue_id=None,
    )
    row["completeness"].update(state="incomplete", evidence_refs=[])
    row["reasons"] = [
        {
            "code": "conflicting_readings",
            "message": "Неоднозначная область операции",
            "evidence_refs": [observed["id"], "scope-alternative"],
        }
    ]
    result["summary"]["counts"].update(discrepancy=0, unverified=2)
    assert CheckJob.model_validate(payload).result.rows[0].status == "unverified"


@pytest.mark.parametrize(
    ("kind", "alternative"),
    [
        ("contract", "OTHER"),
        ("period", {"start": None, "end": "2025-02-20"}),
        ("article", "DEMO-B"),
    ],
)
def test_component_scope_follows_pdf_aliases_without_joining_distinct_fragments(
    payload: dict, kind: str, alternative: object
) -> None:
    result = payload["result"]
    result["documents"][1]["format"] = "pdf"
    for line, item in enumerate(result["evidence"][2:], start=1):
        item["locator"] = {"kind": "page", "page": 1, "line": line}
    selected = next(item for item in result["evidence"] if item["kind"] == kind)
    selected_line = selected["locator"]["line"]
    second_line = 20
    for line in (selected_line, second_line):
        result["evidence"].append(
            {
                **selected,
                "id": f"scope-box-{line}",
                "locator": {"kind": "page", "page": 1, "line": line, "bbox": [0.1, 0.1, 0.3, 0.2]},
            }
        )
    other = {
        **selected,
        "id": "unreferenced-scope-reading",
        "locator": {"kind": "page", "page": 1, "line": second_line},
        "normalized_value": alternative,
    }
    result["evidence"].append(other)
    with pytest.raises(ValidationError, match="component scope evidence must agree"):
        CheckJob.model_validate(payload)

    other["locator"]["bbox"] = [0.5, 0.1, 0.7, 0.2]
    assert CheckJob.model_validate(payload).result is not None


def test_period_readings_can_omit_different_bounds_if_compatible(payload: dict) -> None:
    evidence = payload["result"]["evidence"]
    observed = evidence[5]
    observed["normalized_value"]["end"] = None
    alternative = {
        **observed,
        "id": "period-end-only",
        "normalized_value": {"start": None, "end": "2025-02-28"},
    }
    evidence.append(alternative)
    assert CheckJob.model_validate(payload).result is not None
    alternative["normalized_value"]["end"] = "2025-01-31"
    with pytest.raises(ValidationError, match="component scope evidence must agree"):
        CheckJob.model_validate(payload)


def test_period_validation_uses_known_bounds_from_other_readings(payload: dict) -> None:
    evidence = payload["result"]["evidence"]
    observed = evidence[5]
    observed["normalized_value"] = {"start": None, "end": "2025-03-31"}
    evidence.append(
        {
            **observed,
            "id": "period-both-bounds",
            "normalized_value": {"start": "2025-03-01", "end": "2025-03-31"},
        }
    )
    with pytest.raises(ValidationError, match="lies outside the selected period"):
        CheckJob.model_validate(payload)


def test_period_bounds_from_different_addresses_must_be_compatible(payload: dict) -> None:
    result = payload["result"]
    period = result["evidence"][5]
    period["normalized_value"] = {"start": "2025-02-20", "end": None}
    end = {
        **period,
        "id": "period-end",
        "locator": {**period["locator"], "range": "A4"},
        "normalized_value": {"start": None, "end": "2025-02-10"},
    }
    result["evidence"].append(end)
    result["rows"][0]["calculation"]["components"][0]["period_refs"].append(end["id"])
    with pytest.raises(ValidationError, match="one component has incompatible bounds"):
        CheckJob.model_validate(payload)
    end["normalized_value"]["end"] = "2025-02-20"
    assert CheckJob.model_validate(payload).result is not None
    assert period["normalized_value"]["end"] is None


def test_unreadable_file_requires_a_recorded_error(payload: dict) -> None:
    payload["result"]["documents"][3]["errors"] = []
    with pytest.raises(ValidationError, match="requires a file error"):
        CheckJob.model_validate(payload)


def test_completed_job_cannot_hide_file_errors(payload: dict) -> None:
    payload["status"] = "completed"
    with pytest.raises(ValidationError, match="recorded technical errors"):
        CheckJob.model_validate(payload)
    payload["error"] = {"code": "worker_failed", "message": "Ошибка задания"}
    with pytest.raises(ValidationError, match="job error requires"):
        CheckJob.model_validate(payload)


def test_primary_issue_can_only_reference_a_recorded_file_error(payload: dict) -> None:
    payload["result"]["summary"]["primary_issues"][1]["file_error_refs"] = ["missing-error"]
    with pytest.raises(ValidationError, match="must refer to file errors"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize("referenced", [True, False])
@pytest.mark.parametrize("conflict", [{"normalized_value": "600.25"}, {"unit": "USD"}])
def test_component_readings_must_agree_at_the_canonical_address(
    payload: dict, referenced: bool, conflict: dict
) -> None:
    result = payload["result"]
    reading = {**result["evidence"][2], **conflict, "id": "ambiguous"}
    reading["locator"] = {**reading["locator"], "range": "C6:C6"}
    result["evidence"].append(reading)
    if referenced:
        result["rows"][0]["calculation"]["components"][0]["amount_refs"].append("ambiguous")
    with pytest.raises(ValidationError, match="component evidence must agree"):
        CheckJob.model_validate(payload)


def test_conflicting_report_readings_can_be_retained_with_unknown_value(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    reading = {
        **result["evidence"][0],
        "id": "ambiguous-report",
        "normalized_value": "151.50",
        "locator": {**result["evidence"][0]["locator"], "line": 2},
    }
    result["evidence"].append(reading)
    with pytest.raises(ValidationError, match="reported evidence must agree"):
        CheckJob.model_validate(payload)
    row.update(status="unverified", reported_value=None, delta=None, root_issue_id=None)
    row["reported_evidence_refs"].append("ambiguous-report")
    row["reasons"] = [
        {
            "code": "conflicting_readings",
            "message": "Неоднозначная сумма отчёта",
            "evidence_refs": ["report-a", "ambiguous-report"],
        }
    ]
    result["summary"]["counts"].update(discrepancy=0, unverified=2)
    assert CheckJob.model_validate(payload).result.rows[0].reported_value is None


def test_conflicting_component_can_be_retained_outside_calculation(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["evidence"].append(
        {**result["evidence"][2], "id": "ambiguous-amount", "normalized_value": "600.25"}
    )
    row["calculation"]["components"].pop(0)
    row.update(
        status="unverified",
        observed_evidence_sum="60.25",
        expected_value=None,
        delta=None,
        root_issue_id=None,
    )
    row["completeness"].update(state="incomplete", evidence_refs=["amount-2"])
    row["reasons"] = [
        {
            "code": "conflicting_readings",
            "message": "Неоднозначное чтение суммы",
            "evidence_refs": ["amount-1", "ambiguous-amount"],
        }
    ]
    result["summary"]["counts"].update(discrepancy=0, unverified=2)
    assert CheckJob.model_validate(payload).result.rows[0].observed_evidence_sum == "60.25"


@pytest.mark.parametrize("status", ["verified", "discrepancy"])
def test_complete_coverage_cannot_rely_on_conflicting_amount(payload: dict, status: str) -> None:
    result = payload["result"]
    row = result["rows"][0]
    amount = result["evidence"][2]
    conflict = {**amount, "id": "conflicting-coverage", "normalized_value": "900.50"}
    result["evidence"].append(conflict)
    row["calculation"]["components"].pop(0)
    row.update(observed_evidence_sum="60.25", expected_value="60.25", delta="90.25")
    if status == "verified":
        result["evidence"][0]["normalized_value"] = "60.25"
        row.update(
            status="verified", reported_value="60.25", delta="0.00", root_issue_id=None, reasons=[]
        )
        result["summary"]["counts"].update(verified=1, discrepancy=0)
    with pytest.raises(ValidationError, match="complete coverage evidence must agree"):
        CheckJob.model_validate(payload)

    row.update(status="unverified", expected_value=None, delta=None, root_issue_id=None)
    row["completeness"].update(state="incomplete")
    row["reasons"] = [
        {
            "code": "conflicting_readings",
            "message": "Конфликт чтений обязательного слагаемого",
            "evidence_refs": [amount["id"], conflict["id"]],
        }
    ]
    result["summary"]["counts"].update(verified=0, discrepancy=0, unverified=2)
    checked = CheckJob.model_validate(payload).result.rows[0]
    assert checked.status == "unverified" and checked.observed_evidence_sum == "60.25"
    assert checked.expected_value is None and checked.delta is None
    assert checked.reasons[0].evidence_refs == [amount["id"], conflict["id"]]


def test_complete_coverage_requires_a_precise_address_on_an_ambiguous_pdf_line(
    payload: dict,
) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"][1]["format"] = "pdf"
    first, second = result["evidence"][2:4]
    for line, item in enumerate(result["evidence"][4:], start=20):
        item["locator"] = {"kind": "page", "page": 1, "line": line}
    first["locator"] = {"kind": "page", "page": 1, "line": 5, "fragment_id": "one"}
    second["locator"] = {**first["locator"], "fragment_id": "two"}
    ambiguous = {
        **first,
        "id": "coverage-line-only",
        "locator": {"kind": "page", "page": 1, "line": 5},
    }
    result["evidence"].append(ambiguous)
    assert CheckJob.model_validate(payload).result is not None
    row["completeness"]["evidence_refs"].append(ambiguous["id"])
    with pytest.raises(ValidationError, match="requires a precise evidence address"):
        CheckJob.model_validate(payload)


@pytest.mark.parametrize(
    ("index", "alternative"),
    [
        (4, "OTHER"),
        (5, {"start": None, "end": "2025-02-20"}),
        (6, "DEMO-B"),
    ],
)
def test_complete_coverage_checks_requisites_it_cites(
    payload: dict, index: int, alternative: object
) -> None:
    result = payload["result"]
    row = result["rows"][0]
    observed = {
        **result["evidence"][index],
        "id": "coverage-requisite",
        "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A10"},
    }
    result["evidence"].extend(
        [observed, {**observed, "id": "alternate-reading", "normalized_value": alternative}]
    )
    assert CheckJob.model_validate(payload).result is not None
    row["completeness"]["evidence_refs"].append(observed["id"])
    with pytest.raises(ValidationError, match="complete coverage evidence must agree"):
        CheckJob.model_validate(payload)


def test_complete_coverage_preserves_compatible_partial_period_and_independent_basis(
    payload: dict,
) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["evidence"].extend(
        [
            {
                **result["evidence"][5],
                "id": "profile-start",
                "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A10"},
                "normalized_value": {"start": "2025-02-01", "end": None},
            },
            {
                **result["evidence"][5],
                "id": "profile-end",
                "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A10"},
                "normalized_value": {"start": None, "end": "2025-02-28"},
            },
            {
                **result["evidence"][2],
                "id": "unrelated-a",
                "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "C10"},
            },
            {
                **result["evidence"][2],
                "id": "unrelated-b",
                "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "C10"},
                "normalized_value": "900.50",
            },
        ]
    )
    row["completeness"]["evidence_refs"] = ["profile-start", "profile-end"]
    checked = CheckJob.model_validate(payload).result.rows[0]
    assert checked.completeness.state == "complete" and checked.expected_value == "120.50"


def test_report_cannot_establish_the_scope_of_a_supporting_operation(payload: dict) -> None:
    evidence = payload["result"]["evidence"]
    for index, item in enumerate(evidence[4:], start=1):
        item.update(document_id="report", locator={"kind": "page", "page": 1, "line": index})
    with pytest.raises(ValidationError, match="report alone cannot establish"):
        CheckJob.model_validate(payload)


def test_separate_scope_source_requires_matching_addressed_identity(payload: dict) -> None:
    result = payload["result"]
    result["documents"].append(
        {
            **result["documents"][1],
            "id": "scope-source",
            "name": "synthetic-scope.xlsx",
            "sha256": "4" * 64,
        }
    )
    for item in result["evidence"][4:]:
        item["document_id"] = "scope-source"
    with pytest.raises(ValidationError, match="shared source identity"):
        CheckJob.model_validate(payload)
    for document in ("ledger", "scope-source"):
        result["evidence"].append(
            {
                "id": f"{document}-identity",
                "document_id": document,
                "kind": "document_identity",
                "raw_value": "DEMO-ACT-1",
                "normalized_value": "DEMO-ACT-1",
                "unit": None,
                "method": "native",
                "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A1"},
            }
        )
    for component in result["rows"][0]["calculation"]["components"]:
        component["identity_refs"] = ["ledger-identity", "scope-source-identity"]
    assert CheckJob.model_validate(payload).result is not None
    result["evidence"][-1]["normalized_value"] = "DEMO-ACT-2"
    with pytest.raises(ValidationError, match="shared source identity"):
        CheckJob.model_validate(payload)


def test_conflicting_identity_cannot_establish_scope_even_if_unreferenced(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"].append(
        {
            **result["documents"][1],
            "id": "scope-source",
            "name": "synthetic-scope.xlsx",
            "sha256": "4" * 64,
        }
    )
    result["evidence"][4]["document_id"] = "scope-source"
    identity = {
        "id": "ledger-identity",
        "document_id": "ledger",
        "kind": "document_identity",
        "raw_value": "DEMO-ACT-1",
        "normalized_value": "DEMO-ACT-1",
        "unit": None,
        "method": "native",
        "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A1"},
    }
    matched = {**identity, "id": "scope-identity", "document_id": "scope-source"}
    conflicting = {
        **matched,
        "id": "scope-conflict",
        "raw_value": "DEMO-ACT-2",
        "normalized_value": "DEMO-ACT-2",
        "locator": {**matched["locator"], "range": "A1:A1"},
    }
    result["evidence"].extend([identity, matched])
    for component in row["calculation"]["components"]:
        component["identity_refs"] = ["ledger-identity", "scope-identity"]
    assert CheckJob.model_validate(payload).result is not None
    result["evidence"].append(conflicting)
    with pytest.raises(ValidationError, match="document identity evidence must agree"):
        CheckJob.model_validate(payload)
    row["calculation"]["components"] = []
    row.update(
        status="unverified",
        observed_evidence_sum=None,
        expected_value=None,
        delta=None,
        root_issue_id=None,
    )
    row["completeness"].update(state="incomplete", evidence_refs=[])
    row["reasons"] = [
        {
            "code": "conflicting_readings",
            "message": "Неоднозначный реквизит связанного документа",
            "evidence_refs": ["scope-identity", "scope-conflict"],
        }
    ]
    result["summary"]["counts"].update(discrepancy=0, unverified=2)
    assert CheckJob.model_validate(payload).result.rows[0].status == "unverified"


def test_pdf_line_aliases_cannot_hide_an_identity_conflict(payload: dict) -> None:
    result = payload["result"]
    row = result["rows"][0]
    result["documents"].append(
        {
            **result["documents"][1],
            "id": "scope-source",
            "name": "synthetic-scope.pdf",
            "format": "pdf",
            "sha256": "4" * 64,
        }
    )
    result["evidence"][4].update(
        document_id="scope-source", locator={"kind": "page", "page": 1, "line": 1}
    )
    identity = {
        "id": "ledger-identity",
        "document_id": "ledger",
        "kind": "document_identity",
        "raw_value": "DEMO-ACT-1",
        "normalized_value": "DEMO-ACT-1",
        "unit": None,
        "method": "native",
        "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A1"},
    }
    result["evidence"].append(identity)
    for suffix, line, precise in (("first", 5, False), ("box1", 5, True), ("box2", 6, True)):
        locator = {"kind": "page", "page": 1, "line": line}
        if precise:
            locator["bbox"] = [0.1, 0.1, 0.3, 0.2]
        result["evidence"].append(
            {**identity, "id": suffix, "document_id": "scope-source", "locator": locator}
        )
    for component in row["calculation"]["components"]:
        component["identity_refs"] = ["ledger-identity", "first"]
    assert CheckJob.model_validate(payload).result is not None
    result["evidence"].append(
        {
            **identity,
            "id": "conflicting-identity",
            "document_id": "scope-source",
            "locator": {"kind": "page", "page": 1, "line": 6},
            "normalized_value": "DEMO-ACT-2",
        }
    )
    with pytest.raises(ValidationError, match="document identity evidence must agree"):
        CheckJob.model_validate(payload)


def test_derived_mismatch_requires_discrepancy(payload: dict) -> None:
    payload["result"]["rows"][1]["derived_mismatch"] = True
    with pytest.raises(ValidationError, match="requires a discrepancy and a root issue"):
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

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import Session
from test_run_upload import submit

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckJob, CheckResult
from doccheck_backend.models import Run
from doccheck_backend.run_xlsx import XLSX_MEDIA_TYPE, XlsxReportLimitError, export_check_result

FIXTURE = Path(__file__).resolve().parents[2] / "contracts/check-result.v1.synthetic.json"


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def decision_result() -> dict:
    result = fixture_payload()["result"]
    decisions = [
        (
            "other-period",
            "outside_period",
            "Документ вне периода",
            ["late-period", "ambig\x01"],
        ),
        (
            "other-contract",
            "different_contract",
            "Документ относится к другому договору",
            ['=HYPERLINK("https://example.test/")', "contract\nsecond", r"ambig\x01"],
        ),
        ("unresolved", "needs_check", "Основание не установлено", []),
    ]
    for number, (document_id, code, message, refs) in enumerate(decisions, 4):
        result["documents"].append(
            {
                "id": document_id,
                "name": f"synthetic-{document_id}.pdf",
                "sha256": str(number) * 64,
                "format": "pdf",
                "role": "support",
                "parse_status": "parsed",
                "decision": {
                    "state": "needs_review" if document_id == "unresolved" else "exclude",
                    "reason_code": code,
                    "message": message,
                    "evidence_refs": refs,
                },
                "errors": [],
            }
        )
    result["evidence"].extend(
        [
            {
                "id": "late-period",
                "document_id": "other-period",
                "kind": "period",
                "raw_value": "Март 2025",
                "normalized_value": {"start": "2025-03-01", "end": "2025-03-31"},
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 3},
            },
            {
                "id": '=HYPERLINK("https://example.test/")',
                "document_id": "other-contract",
                "kind": "contract",
                "raw_value": "DEMO-K2",
                "normalized_value": "DEMO-K2",
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 4},
            },
            {
                "id": "contract\nsecond",
                "document_id": "other-contract",
                "kind": "contract",
                "raw_value": "DEMO-K2",
                "normalized_value": "DEMO-K2",
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 5},
            },
            {
                "id": "unlinked-source",
                "document_id": "unresolved",
                "kind": "contract",
                "raw_value": "DEMO-K3",
                "normalized_value": "DEMO-K3",
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 6},
            },
            {
                "id": "ambig\x01",
                "document_id": "other-period",
                "kind": "contract",
                "raw_value": "DEMO-K1",
                "normalized_value": "DEMO-K1",
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 7},
            },
            {
                "id": r"ambig\x01",
                "document_id": "other-contract",
                "kind": "contract",
                "raw_value": "DEMO-K2",
                "normalized_value": "DEMO-K2",
                "unit": None,
                "method": "native",
                "locator": {"kind": "page", "page": 1, "line": 8},
            },
        ]
    )
    return result


def assert_document_decision_links(workbook) -> None:
    sheet = workbook["Документы"]
    rows = {row[0].value: row for row in sheet.iter_rows(min_row=2)}
    assert [cell.value for cell in sheet[1]] == [
        "ID документа",
        "Документ",
        "Роль",
        "Состояние",
        "Решение",
        "Основание",
        "Ошибки файла",
        "ID исходного документа",
        "Код причины решения",
        "ID источников решения (JSON)",
    ]
    period = rows["other-period"]
    assert [cell.value for cell in period[:9]] == [
        "other-period",
        "synthetic-other-period.pdf",
        "Первичный",
        "parsed",
        "exclude",
        "Документ вне периода",
        None,
        None,
        "outside_period",
    ]
    period_refs = json.loads(period[9].value)
    assert period_refs == ["late-period", "ambig\x01"]
    contract = rows["other-contract"]
    assert contract[4].value == "exclude"
    assert contract[5].value == "Документ относится к другому договору"
    assert contract[8].value == "different_contract"
    contract_refs = json.loads(contract[9].value)
    assert contract_refs == [
        '=HYPERLINK("https://example.test/")',
        "contract\nsecond",
        r"ambig\x01",
    ]
    assert rows["unresolved"][8].value == "needs_check"
    assert rows["unresolved"][9].value is None

    source_sheet = workbook["Источники"]
    assert [cell.value for cell in source_sheet[1]] == [
        "ID источника",
        "ID документа",
        "Документ",
        "Адрес",
        "Тип свидетельства",
        "ID источника (JSON)",
    ]
    source_rows = list(source_sheet.iter_rows(min_row=2))
    sources = {json.loads(row[5].value): row for row in source_rows}
    assert len(sources) == len(source_rows)
    assert sources["late-period"][5].value == '"late-period"'
    assert [sources[ref][1].value for ref in period_refs] == ["other-period"] * 2
    assert sources["late-period"][3].value == "Страница 1; строка 3"
    assert [sources[ref][1].value for ref in contract_refs] == ["other-contract"] * 3
    assert [sources[ref][3].value for ref in contract_refs] == [
        "Страница 1; строка 4",
        "Страница 1; строка 5",
        "Страница 1; строка 8",
    ]
    assert sources["unlinked-source"][1].value == "unresolved"
    assert sources["ambig\x01"][0].value == sources[r"ambig\x01"][0].value == r"ambig\x01"
    assert sources["ambig\x01"][5].value != sources[r"ambig\x01"][5].value
    assert sources["ambig\x01"][3].value == "Страница 1; строка 7"
    for cell in (
        contract[8],
        contract[9],
        *(sources[ref][column] for ref in contract_refs for column in (0, 5)),
    ):
        assert cell.data_type == "s" and cell.hyperlink is None


def test_document_decisions_preserve_only_their_saved_sources():
    result = CheckResult.model_validate(decision_result())
    workbook = load_workbook(BytesIO(export_check_result(result)))
    assert_document_decision_links(workbook)


def test_document_decision_code_is_literal_and_not_truncated():
    payload = decision_result()
    code = '=HYPERLINK("https://example.test/")'
    payload["documents"][-1]["decision"]["reason_code"] = code
    workbook = load_workbook(BytesIO(export_check_result(CheckResult.model_validate(payload))))
    row = next(
        row for row in workbook["Документы"].iter_rows(min_row=2) if row[0].value == "unresolved"
    )
    assert row[8].value == code and row[8].data_type == "s" and row[8].hyperlink is None

    payload["documents"][-1]["decision"]["reason_code"] = "x" * 32_768
    with pytest.raises(XlsxReportLimitError, match="cell text exceeds Excel limit"):
        export_check_result(CheckResult.model_validate(payload))


def test_serialized_source_id_respects_excel_cell_limit():
    payload = fixture_payload()["result"]
    source = deepcopy(next(item for item in payload["evidence"] if item["id"] == "contract"))
    source["id"] = "x" * 32_765
    payload["evidence"].append(source)
    workbook = load_workbook(BytesIO(export_check_result(CheckResult.model_validate(payload))))
    exported = next(
        row for row in workbook["Источники"].iter_rows(min_row=2) if row[0].value == source["id"]
    )
    assert json.loads(exported[5].value) == source["id"]
    assert len(exported[5].value) == 32_767

    # The old ID cell would fit; JSON's two quotes exceed the XLSX cell limit.
    source["id"] = "x" * 32_766
    with pytest.raises(XlsxReportLimitError, match="cell text exceeds Excel limit"):
        export_check_result(CheckResult.model_validate(payload))


def test_workbook_preserves_amounts_and_keeps_all_untrusted_cells_literal():
    payload = fixture_payload()
    result = payload["result"]
    result["rows"][0]["label"] = "=1+1"
    result["rows"][0]["calculation"]["formula"] = "=SUM(B1:B2)"
    result["rows"][1]["label"] = "#N/A"
    result["documents"][0]["name"] = "=2+3"
    result["summary"]["conclusion"] = "Синтетика\x0bпроверка"
    expected = "12345678901234567890.01"
    result["rows"][1]["reported_value"] = expected
    report_b = next(item for item in result["evidence"] if item["id"] == "report-b")
    report_b["raw_value"] = expected
    report_b["normalized_value"] = expected
    job = CheckJob.model_validate(payload)
    assert job.result is not None

    workbook = load_workbook(BytesIO(export_check_result(job.result)))
    assert workbook.sheetnames == [
        "Сверка",
        "Слагаемые",
        "Источники",
        "Документы",
        "Первичные замечания",
    ]
    reconciliation = workbook["Сверка"]
    rows = {row[0].value: row for row in reconciliation if row[0].value in ("row-a", "row-b")}
    first, second = rows["row-a"], rows["row-b"]
    assert [cell.value for cell in first[3:9]] == [
        "RUB",
        "150.50",
        "120.50",
        "120.50",
        "30.00",
        "Расхождение",
    ]
    assert [cell.value for cell in second[4:9]] == [expected, None, None, None, "Не проверен"]
    assert first[1].value == "=1+1" and first[1].data_type == "s"
    assert first[13].value == "=SUM(B1:B2)" and first[13].data_type == "s"
    assert second[1].value == "#N/A" and second[1].data_type == "s"
    assert second[4].data_type == "s"
    assert "amount-1" in first[15].value.splitlines()
    assert any(
        a == "Заключение" and b == r"Синтетика\x0bпроверка" for a, b, *_ in reconciliation.values
    )

    sources = {item[0]: item for item in workbook["Источники"].values}
    assert sources["amount-1"][3] == "Лист «Синтетика», C6"
    assert "Страница 1" in sources["report-a"][3]
    assert sources["report-a"][2] == "=2+3"
    assert any(row[1] == "=2+3" for row in workbook["Документы"].values)
    root_issue = second[16].value
    assert root_issue == "issue-b"
    issues = {row[0]: row for row in workbook["Первичные замечания"].values}
    assert issues["issue-a"][3] == "report-a\namount-1\namount-2"
    assert issues[root_issue][4] == "scan-read-error"
    assert any(
        row[6] and row[6].startswith(issues[root_issue][4] + " · ")
        for row in workbook["Документы"].values
    )
    assert all(
        cell.data_type != "f" and cell.hyperlink is None
        for sheet in workbook
        for row in sheet
        for cell in row
    )


def test_components_preserve_individual_relations_and_typed_references():
    payload = fixture_payload()
    result = payload["result"]
    items = result["rows"][0]["calculation"]["components"]
    items[0]["relation_reason"] = '=HYPERLINK("https://example.test/")'
    items[1]["relation_reason"] = "#N/A"
    identity = "=identity"
    items[0]["identity_refs"] = [identity]
    result["evidence"].append(
        {
            "id": identity,
            "document_id": "ledger",
            "kind": "document_identity",
            "raw_value": "Синтетический ID",
            "normalized_value": "SYNTHETIC-ID",
            "unit": None,
            "method": "native",
            "locator": {"kind": "sheet", "sheet": "Синтетика", "range": "A5"},
        }
    )
    job = CheckJob.model_validate(payload)
    assert job.result is not None

    workbook = load_workbook(BytesIO(export_check_result(job.result)))
    first, second = list(workbook["Слагаемые"].iter_rows(min_row=2))
    assert [cell.value for cell in first] == [
        "row-a",
        1,
        "60.25",
        "RUB",
        items[0]["relation_reason"],
        "amount-1",
        "contract",
        "period",
        "article",
        identity,
    ]
    assert [cell.value for cell in second] == [
        "row-a",
        2,
        "60.25",
        "RUB",
        "#N/A",
        "amount-2",
        "contract",
        "period",
        "article",
        None,
    ]
    for cell in (first[2], first[4], first[9], second[2], second[4]):
        assert cell.data_type == "s" and cell.hyperlink is None
    sources = {item[0]: item for item in workbook["Источники"].values}
    assert sources[first[5].value][3] == "Лист «Синтетика», C6"
    assert sources[second[5].value][3] == "Лист «Синтетика», C7"
    assert sources[identity][3] == "Лист «Синтетика», A5"


def set_saved_result(client, run_id: str, *, status: str, result: dict | None = None) -> None:
    with Session(client.app.state.engine) as session, session.begin():
        run = session.get(Run, UUID(run_id))
        assert run is not None
        run.status = status
        if status in ("completed", "completed_with_issues"):
            result = result or fixture_payload()["result"]
            result["run_id"] = run_id
            run.result = CheckResult.model_validate(result).model_dump(mode="json")


@pytest.mark.parametrize("status", ["completed", "completed_with_issues"])
def test_export_saved_result_via_http(database_url, tmp_path, status):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        created = submit(client, uuid4())
        run_id = created.json()["run_id"]
        set_saved_result(client, run_id, status=status, result=decision_result())
        response = client.get(f"/api/v0/runs/{run_id}/exports/xlsx")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == XLSX_MEDIA_TYPE
    assert (
        response.headers["Content-Disposition"] == f'attachment; filename="doccheck-{run_id}.xlsx"'
    )
    assert response.headers["Cache-Control"] == "no-store"
    workbook = load_workbook(BytesIO(response.content))
    assert workbook["Сверка"]["B1"].value == run_id
    assert workbook["Сверка"]["B2"].value == "Синтетические"
    assert_document_decision_links(workbook)


def test_export_rejects_saved_result_with_missing_decision_evidence(database_url, tmp_path):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        run_id = submit(client, uuid4()).json()["run_id"]
        set_saved_result(client, run_id, status="completed", result=decision_result())
        with Session(client.app.state.engine) as session, session.begin():
            run = session.get(Run, UUID(run_id))
            assert run is not None
            result = deepcopy(run.result)
            result["documents"][-1]["decision"]["evidence_refs"] = ["missing-id"]
            run.result = result
        response = client.get(f"/api/v0/runs/{run_id}/exports/xlsx")

    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"


@pytest.mark.parametrize(
    ("status", "code"),
    [("queued", "result_pending"), ("processing", "result_pending"), ("failed", "run_failed")],
)
def test_no_exports_for_non_ready_runs(database_url, tmp_path, status, code):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        created = submit(client, uuid4())
        run_id = created.json()["run_id"]
        set_saved_result(client, run_id, status=status)
        response = client.get(f"/api/v0/runs/{run_id}/exports/xlsx")

    assert response.status_code == 409
    assert response.json()["code"] == code


def test_no_export_for_unknown_run(database_url, tmp_path):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        response = client.get(f"/api/v0/runs/{uuid4()}/exports/xlsx")

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"

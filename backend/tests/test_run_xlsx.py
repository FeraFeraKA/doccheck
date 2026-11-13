import json
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
from doccheck_backend.run_xlsx import XLSX_MEDIA_TYPE, export_check_result

FIXTURE = Path(__file__).resolve().parents[2] / "contracts/check-result.v1.synthetic.json"


def fixture_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


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


def set_saved_result(client, run_id: str, *, status: str) -> None:
    with Session(client.app.state.engine) as session, session.begin():
        run = session.get(Run, UUID(run_id))
        assert run is not None
        run.status = status
        if status in ("completed", "completed_with_issues"):
            result = fixture_payload()["result"]
            result["run_id"] = run_id
            run.result = CheckResult.model_validate(result).model_dump(mode="json")


@pytest.mark.parametrize("status", ["completed", "completed_with_issues"])
def test_export_saved_result_via_http(database_url, tmp_path, status):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        created = submit(client, uuid4())
        run_id = created.json()["run_id"]
        set_saved_result(client, run_id, status=status)
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

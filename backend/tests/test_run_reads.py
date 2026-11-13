import os
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_run_upload import DOCUMENT, REPORT, submit
from test_run_worker import _synthetic_result

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckResult
from doccheck_backend.models import Run
from doccheck_backend.run_worker import StoredRun

RUNS = "/api/v0/runs"


@pytest.fixture
def client(database_url, tmp_path):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        yield client


def _create(client) -> str:
    response = submit(client, uuid4())
    assert response.status_code == 202
    return response.json()["run_id"]


def _update_run(client, run_id, **values):
    with Session(client.app.state.engine) as session, session.begin():
        run = session.get(Run, UUID(run_id))
        for key, value in values.items():
            setattr(run, key, value)


def _manifest(client, run_id):
    with Session(client.app.state.engine) as session:
        run = session.get(Run, UUID(run_id))
        return StoredRun(run.id, run.scope, run.documents)


def _complete(client, run_id) -> CheckResult:
    run = _manifest(client, run_id)
    result = _synthetic_result(run, partial=True).model_dump(mode="json")
    result["evidence"] = [
        {
            "id": "amount-7",
            "document_id": run.documents[0]["id"],
            "kind": "reported_value",
            "raw_value": "12 345,67",
            "normalized_value": "12345.67",
            "unit": "RUB",
            "method": "synthetic",
            "locator": {"kind": "page", "page": 1, "line": 3, "fragment_id": "demo-7"},
        }
    ]
    validated = CheckResult.model_validate(result)
    _update_run(
        client,
        run_id,
        status="completed_with_issues",
        result=validated.model_dump(mode="json"),
        error={"code": "processing_completed_with_issues", "message": "Тестовая причина"},
    )
    return validated


def test_history_cursor_orders_ties_and_survives_inserts(client):
    assert client.get(RUNS).json() == {"items": [], "next_cursor": None}
    previous = _create(client)
    ties = [_create(client), _create(client), _create(client)]
    identical_date = datetime(2026, 11, 13, 20, 5, 2, 91024, tzinfo=UTC)
    _update_run(client, previous, created_at=identical_date - timedelta(seconds=1))
    for run_id in ties:
        _update_run(client, run_id, created_at=identical_date)
    ordered = sorted(ties, reverse=True) + [previous]
    first = client.get(RUNS, params={"limit": 2})
    assert first.status_code == 200
    page = first.json()
    assert [item["run_id"] for item in page["items"]] == ordered[:2]
    assert set(page["items"][0]) == {"run_id", "status", "created_at", "error"}
    assert page["next_cursor"]
    newest = _create(client)
    _update_run(client, newest, created_at=identical_date + timedelta(seconds=1))
    second = client.get(RUNS, params={"limit": 2, "cursor": page["next_cursor"]})
    assert second.status_code == 200
    assert [item["run_id"] for item in second.json()["items"]] == ordered[2:]
    assert second.json()["next_cursor"] is None
    assert client.get(RUNS).json()["items"][0]["run_id"] == newest


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"limit": "abc"}, "limit"),
        ({"limit": "0"}, "limit"),
        ({"limit": "101"}, "limit"),
        ({"cursor": ""}, "cursor"),
        ({"cursor": "!invalid"}, "cursor"),
        ({"cursor": "W10"}, "cursor"),
        ({"cursor": "a" * 161}, "cursor"),
    ],
)
def test_invalid_history_inputs_use_contract_error(client, params, field):
    response = client.get(RUNS, params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"
    assert response.json()["field"] == field


def test_run_state_and_findings_distinguish_progress_and_failure(client):
    run_id = _create(client)
    run_url = f"{RUNS}/{run_id}"
    findings_url = f"{run_url}/findings"
    queued = client.get(run_url)
    assert queued.status_code == 200
    assert queued.json()["status"] == "queued"
    assert queued.json()["progress"] == {"processed_documents": 0, "total_documents": 2}
    pending = client.get(findings_url)
    assert (pending.status_code, pending.json()["code"]) == (409, "result_pending")

    _update_run(client, run_id, status="processing")
    assert client.get(run_url).json()["progress"] is None
    pending = client.get(findings_url)
    assert (pending.status_code, pending.json()["code"]) == (409, "result_pending")

    error = {"code": "processing_failed", "message": "Тестовая причина"}
    _update_run(client, run_id, status="failed", error=error)
    failed = client.get(run_url).json()
    assert failed["status"] == "failed"
    assert failed["error"] == error
    assert failed["progress"] is None
    assert client.get(RUNS).json()["items"][0]["error"] == error
    inaccessible = client.get(findings_url)
    assert (inaccessible.status_code, inaccessible.json()["code"]) == (409, "run_failed")

    expected = _complete(client, run_id)
    completed = client.get(run_url).json()
    assert completed["status"] == "completed_with_issues"
    assert completed["error"]["code"] == "processing_completed_with_issues"
    assert completed["progress"] == {"processed_documents": 2, "total_documents": 2}
    findings = client.get(findings_url)
    assert findings.status_code == 200
    assert findings.json() == expected.model_dump(mode="json")
    assert findings.json()["synthetic"] is True
    assert findings.json()["documents"][1]["errors"][0]["code"] == "unreadable"


def test_successful_run_has_full_progress(client):
    run_id = _create(client)
    result = _synthetic_result(_manifest(client, run_id))
    _update_run(client, run_id, status="completed", result=result.model_dump(mode="json"))
    response = client.get(f"{RUNS}/{run_id}")
    assert response.status_code == 200
    assert response.json()["progress"] == {"processed_documents": 2, "total_documents": 2}
    assert response.json()["error"] is None


def test_download_and_fragment_stay_within_run(client, tmp_path):
    run_id = _create(client)
    other_id = _create(client)
    first, second = [document["id"] for document in _manifest(client, run_id).documents]
    foreign = _manifest(client, other_id).documents[0]["id"]
    doc_url = f"{RUNS}/{run_id}/documents"
    attachment = client.get(f"{doc_url}/{first}")
    assert attachment.status_code == 200
    assert attachment.content == REPORT[1][1]
    assert attachment.headers["Content-Type"] == "application/octet-stream"
    assert attachment.headers["Content-Disposition"] == 'attachment; filename="report.pdf"'
    assert client.get(f"{doc_url}/{second}").content == DOCUMENT[1][1]

    for url in (f"{doc_url}/{foreign}", f"{doc_url}/..%5Creport.pdf"):
        response = client.get(url)
        assert (response.status_code, response.json()["code"]) == (404, "document_not_found")

    fragment_url = f"{doc_url}/{first}/fragments/amount-7"
    pending = client.get(fragment_url)
    assert (pending.status_code, pending.json()["code"]) == (409, "result_pending")
    expected = _complete(client, run_id)
    fragment = client.get(fragment_url)
    assert fragment.status_code == 200
    assert fragment.json() == expected.evidence[0].model_dump(mode="json")
    for url in (
        f"{doc_url}/{first}/fragments/unknown",
        f"{doc_url}/{second}/fragments/amount-7",
    ):
        response = client.get(url)
        assert (response.status_code, response.json()["code"]) == (404, "fragment_not_found")
    response = client.get(f"{doc_url}/{foreign}/fragments/amount-7")
    assert (response.status_code, response.json()["code"]) == (404, "document_not_found")

    (tmp_path / run_id / first).unlink()
    for url in (fragment_url, f"{doc_url}/{first}"):
        response = client.get(url)
        assert (response.status_code, response.json()["code"]) == (404, "document_not_found")
        assert str(tmp_path) not in response.text


def test_download_rejects_directory_redirect_to_another_package(client, tmp_path):
    run_id = _create(client)
    document_id = _manifest(client, run_id).documents[0]["id"]
    run_directory = tmp_path / run_id
    outside = tmp_path / "another-package"
    run_directory.rename(outside)
    if os.name == "nt":
        junction = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/j", str(run_directory), str(outside)],
            capture_output=True,
            check=False,
        )
        assert junction.returncode == 0, junction.stderr
    else:
        run_directory.symlink_to(outside, target_is_directory=True)
    response = client.get(f"{RUNS}/{run_id}/documents/{document_id}")
    assert (response.status_code, response.json()["code"]) == (404, "document_not_found")


def test_missing_runs_and_corrupt_result_use_contract_errors(client):
    for run_id in (str(uuid4()), "not-a-uuid"):
        for suffix in ("", "/findings", "/documents/unknown", "/documents/unknown/fragments/a"):
            response = client.get(f"{RUNS}/{run_id}{suffix}")
            assert (response.status_code, response.json()["code"]) == (404, "run_not_found")
    run_id = _create(client)
    _update_run(client, run_id, status="completed")
    response = client.get(f"{RUNS}/{run_id}/findings")
    assert (response.status_code, response.json()["code"]) == (503, "service_unavailable")


def test_missing_database_uses_safe_v0_error(tmp_path):
    settings = Settings(
        "postgresql+psycopg://invalid-user@127.0.0.1:1/doccheck_missing?connect_timeout=1",
        upload_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(RUNS)
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    assert "invalid-user" not in response.text

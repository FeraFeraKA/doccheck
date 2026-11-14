import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import update
from test_run_upload import submit
from test_run_worker import _synthetic_result
from test_scaffold_integration import running_api

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckJob
from doccheck_backend.database import create_database_engine
from doccheck_backend.hosted_seed import seed
from doccheck_backend.hosted_worker import HostedClient
from doccheck_backend.models import HostedClaim, Run
from doccheck_backend.run_worker import StoredRun

_CLAIMS = "/api/worker/v1/claims"
_TOKEN = "synthetic-test-token-" + "0" * 32
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


def _seed(config, directory, *, viewer=None):
    directory.mkdir()
    report = directory / "report.xlsx"
    act = directory / "act.docx"
    Workbook().save(report)
    Document().save(act)
    manifest = directory / "manifest.json"

    def metadata(file):
        return {"name": file.name, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}

    data = {"synthetic": True, "report": metadata(report), "documents": [metadata(act)]}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    key = uuid4()
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    result = seed(config, manifest, digest, key, viewer=viewer)
    assert seed(config, manifest, digest, key, viewer=viewer) == result
    return result, report.read_bytes()


def test_hosted_claim_fences_expired_worker_and_persists_result(database_url, tmp_path):
    config = Settings(
        database_url,
        upload_root=tmp_path / "runs",
        public_demo=True,
        hosted_worker_digest=hashlib.sha256(_TOKEN.encode()).hexdigest(),
    )
    run, report = _seed(config, tmp_path / "inputs")
    with TestClient(create_app(config), headers=_HEADERS) as http:
        assert http.get("/api/v0/runs").status_code == 503
        assert submit(http, uuid4()).status_code == 503
        assert http.post(_CLAIMS, headers={"Authorization": "Bearer wrong"}).status_code == 401
        first = http.post(_CLAIMS).json()
        assert first["run_id"] == str(run)
        assert first["attempt"] == 1
        assert http.post(_CLAIMS).status_code == 204
        first_url = f"{_CLAIMS}/{first['lease_id']}"
        file_url = first_url + f"/files/{first['documents'][0]['id']}"
        payload = http.get(file_url)
        assert payload.content == report
        assert payload.headers["cache-control"] == "no-store"
        assert http.get(first_url + "/files/" + uuid4().hex).status_code == 404
        assert http.post(first_url + "/heartbeat").status_code == 204
        with http.app.state.engine.begin() as connection:
            connection.execute(
                update(HostedClaim)
                .where(HostedClaim.run_id == run)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert http.get(file_url).status_code == 409
        second = http.post(_CLAIMS).json()
        assert second["lease_id"] != first["lease_id"]
        assert second["attempt"] == 2
        second_url = f"{_CLAIMS}/{second['lease_id']}"
        outcome = {
            "run_id": str(run),
            "status": "failed",
            "result": None,
            "error": {"code": "test_error", "message": "Never propagate worker error text"},
        }
        assert http.put(first_url + "/result", json=outcome).status_code == 404
        assert (
            http.put(second_url + "/result", json={**outcome, "run_id": str(uuid4())}).status_code
            == 422
        )
        assert http.put(second_url + "/result", json=outcome).status_code == 204
        assert http.put(second_url + "/result", json=outcome).status_code == 204
        with http.app.state.engine.connect() as connection:
            persisted = connection.execute(Run.__table__.select().where(Run.id == run)).one()
        assert persisted.status == "failed"
        assert persisted.error["code"] == "processing_failed"
        assert "Never propagate" not in persisted.error["message"]
        assert UUID(second["lease_id"])


def test_hosted_worker_pulls_verified_package_and_completes_over_http(database_url, tmp_path):
    digest = hashlib.sha256(_TOKEN.encode()).hexdigest()
    root = tmp_path / "runs"
    config = Settings(database_url, upload_root=root, public_demo=True, hosted_worker_digest=digest)
    run_id, report = _seed(config, tmp_path / "inputs")
    receives = []

    def process(run, directory):
        assert run.id == run_id
        assert (directory / run.documents[0]["id"]).read_bytes() == report
        assert (directory / run.documents[1]["id"]).is_file()
        receives.append(directory)
        simulated = StoredRun(
            run.id,
            {
                "report_document_id": run.report_document_id,
                "contract_number": "SYNTHETIC",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "report_row_locator": {"kind": "sheet", "sheet": "Sheet", "range": "A1"},
            },
            run.documents,
        )
        result = _synthetic_result(simulated).model_copy(update={"synthetic": False})
        return CheckJob(run_id=str(run.id), status="completed", result=result, error=None)

    environment = {
        "DOCCHECK_PUBLIC_DEMO": "1",
        "DOCCHECK_HOSTED_WORKER_SHA256": digest,
        "DOCCHECK_UPLOAD_ROOT": str(root),
    }
    with running_api(database_url, environment=environment) as api:
        worker = HostedClient(str(api.base_url).rstrip("/"), _TOKEN)
        assert worker.process_one(process)
        assert not worker.process_one(process)
        assert len(receives) == 1
        assert not receives[0].exists()
        assert api.get(f"/api/v0/runs/{run_id}/findings").status_code == 503
    engine = create_database_engine(database_url)
    try:
        with engine.connect() as connection:
            persisted = connection.execute(Run.__table__.select().where(Run.id == run_id)).one()
        assert persisted.status == "completed"
        assert persisted.result["synthetic"] is True
    finally:
        engine.dispose()


def test_restricted_preview_has_secure_session_and_denies_cross_viewer(database_url, tmp_path):
    first, second = uuid4(), uuid4()
    token_one, token_two = "1" * 48, "2" * 48
    digest = hashlib.sha256(_TOKEN.encode()).hexdigest()
    config = Settings(
        database_url,
        upload_root=tmp_path / "runs",
        public_demo=True,
        hosted_worker_digest=digest,
        hosted_viewers={
            first: hashlib.sha256(token_one.encode()).hexdigest(),
            second: hashlib.sha256(token_two.encode()).hexdigest(),
        },
        hosted_session_key=b"s" * 32,
    )
    run_one, report = _seed(config, tmp_path / "first", viewer=first)
    run_two, _ = _seed(config, tmp_path / "second", viewer=second)
    base = "/api/preview/v1"
    with TestClient(create_app(config), base_url="https://testserver") as http:
        claim = http.post(_CLAIMS, headers=_HEADERS).json()
        file_id = claim["documents"][0]["id"]
        assert http.get(base + "/runs").status_code == 401
        assert http.post(base + "/session", json={"token": _TOKEN}).status_code == 401
        session = http.post(base + "/session", json={"token": token_one})
        assert session.status_code == 204
        assert "Secure" in session.headers["set-cookie"]
        assert "HttpOnly" in session.headers["set-cookie"]
        assert "SameSite=strict" in session.headers["set-cookie"]
        runs = http.get(base + "/runs")
        assert [run["run_id"] for run in runs.json()] == [str(run_one)]
        assert runs.headers["cache-control"] == "no-store"
        assert http.get(f"{base}/runs/{run_one}").status_code == 200
        original = http.get(f"{base}/runs/{run_one}/documents/{file_id}")
        assert original.content == report
        assert original.headers["cache-control"] == "no-store"
        for suffix in (
            "",
            "/findings",
            "/documents/not-owned",
            "/documents/not-owned/fragments?evidence_id=unknown",
            "/documents/not-owned/fragment-preview?evidence_id=unknown",
            "/exports/xlsx",
        ):
            assert http.get(f"{base}/runs/{run_two}{suffix}").status_code == 404
        assert http.get("/api/v0/runs").status_code == 503
        assert http.post(_CLAIMS).status_code == 401

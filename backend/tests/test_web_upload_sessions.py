from uuid import uuid4

from fastapi.testclient import TestClient
from test_run_reads import _complete
from test_run_upload import submit

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings

RUNS = "/api/v0/runs"
SESSION = "/api/v0/upload-session"
ORIGIN = "https://doccheck.example"


def test_web_upload_requires_session_and_keeps_results_private(database_url, tmp_path):
    settings = Settings(database_url, upload_root=tmp_path, web_sessions=True)
    key = uuid4()
    with TestClient(create_app(settings), base_url=ORIGIN) as browser:
        assert submit(browser, key).status_code == 401
        start = browser.post(SESSION)
        assert start.status_code == 204
        assert all(
            flag in start.headers["set-cookie"]
            for flag in ("Secure", "HttpOnly", "SameSite=strict")
        )
        assert "set-cookie" not in browser.post(SESSION).headers
        accepted = submit(browser, key)
        assert accepted.status_code == 202
        assert submit(browser, key).json() == accepted.json()
        run_id = accepted.json()["run_id"]
        result = _complete(browser, run_id)
        route = f"{RUNS}/{run_id}"
        original = f"{route}/documents/{result.documents[0].id}"
        paths = [
            route,
            route + "/findings",
            route + "/exports/xlsx",
            original,
            original + "/fragments?evidence_id=amount-7",
        ]
        for path in paths:
            assert browser.get(path).status_code == 200

        with TestClient(create_app(settings), base_url=ORIGIN) as stranger:
            assert stranger.get(route).status_code == 404
            assert stranger.post(SESSION).status_code == 204
            assert stranger.get(RUNS).json()["items"] == []
            for path in paths:
                assert stranger.get(path).status_code == 404
            other = submit(stranger, key)
            assert other.status_code == 202
            assert other.json()["run_id"] != run_id
        assert [row["run_id"] for row in browser.get(RUNS).json()["items"]] == [run_id]

        with TestClient(
            create_app(Settings(database_url, upload_root=tmp_path)), base_url=ORIGIN
        ) as local:
            existing = submit(local, uuid4()).json()["run_id"]
        assert browser.get(f"{RUNS}/{existing}").status_code == 404


def test_full_web_queue_allows_retries(database_url, tmp_path):
    settings = Settings(database_url, upload_root=tmp_path, web_sessions=True)
    with TestClient(create_app(settings), base_url=ORIGIN) as browser:
        assert browser.post(SESSION).status_code == 204
        first_key = uuid4()
        first = submit(browser, first_key)
        assert first.status_code == 202
        for _ in range(5):
            assert submit(browser, uuid4()).status_code == 202
        busy = submit(browser, uuid4())
        assert busy.status_code == 503
        assert busy.json()["code"] == "service_unavailable"
        assert submit(browser, first_key).json() == first.json()

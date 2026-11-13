from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from doccheck_backend import uploads
from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.models import Run

FIELDS = {
    "contract_number": "DEMO-1",
    "period_start": "2025-01-01",
    "period_end": "2025-01-31",
    "report_row_locator": '{"kind":"page","page":1,"line":3}',
}
REPORT = ("report", ("../../report.pdf", b"%PDF-1.4 synthetic report"))
DOCUMENT = ("documents", ("support.png", b"\x89PNG\r\n\x1a\nsynthetic document"))


def submit(client, key, data=FIELDS, files=(REPORT, DOCUMENT)):
    return client.post(
        "/api/v0/runs", headers={"Idempotency-Key": str(key)}, data=data, files=list(files)
    )


def test_create_replay_and_conflict(database_url, tmp_path):
    root = tmp_path / "runs"
    key = uuid4()
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: submit(client, key), range(2)))
        created, replay = responses
        assert created.status_code == replay.status_code == 202
        assert created.json() == replay.json()
        run_id = created.json()["run_id"]
        assert created.headers["Location"] == replay.headers["Location"] == f"/api/v0/runs/{run_id}"
        assert created.json()["status"] == "queued"

        changed = submit(
            client, key, data={**FIELDS, "report_row_locator": '{"kind":"page","page":1,"line":4}'}
        )
        assert changed.status_code == 409
        assert changed.json()["code"] == "idempotency_conflict"

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            row = connection.execute(select(Run.__table__)).mappings().one()
            assert row["id"] == UUID(run_id)
            assert row["scope"]["report_document_id"] == row["documents"][0]["id"]
            assert row["scope"]["report_row_locator"]["line"] == 3
            assert [doc["role"] for doc in row["documents"]] == ["report", "supporting"]
            assert list(root.iterdir()) == [root / run_id]
            for file, item in zip((REPORT, DOCUMENT), row["documents"], strict=True):
                stored = root / run_id / item["id"]
                assert stored.read_bytes() == file[1][1]
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("data", "files", "status", "code"),
    [
        ({**FIELDS, "period_start": "2025-02-01"}, (REPORT, DOCUMENT), 422, "invalid_input"),
        ({**FIELDS, "report_row_locator": "null"}, (REPORT, DOCUMENT), 422, "invalid_input"),
        (FIELDS, (REPORT,), 422, "invalid_input"),
        (FIELDS, (REPORT, ("documents", ("empty.png", b""))), 422, "invalid_input"),
        (
            FIELDS,
            (REPORT, ("documents", ("bad.pdf", b"arbitrary bytes"))),
            422,
            "unsupported_file_format",
        ),
    ],
)
def test_invalid_upload_has_safe_errors(tmp_path, data, files, status, code):
    root = tmp_path / "runs"
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=root)
    with TestClient(create_app(settings)) as client:
        response = submit(client, uuid4(), data=data, files=files)
        assert response.status_code == status
        assert response.json()["code"] == code
    assert not root.exists()


@pytest.mark.parametrize("count", [101, 102])
def test_too_many_documents_matches_contract(tmp_path, count):
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = submit(client, uuid4(), files=(REPORT, *([DOCUMENT] * count)))
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"
    assert not list(tmp_path.iterdir())


def test_upload_limits(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=root)
    with TestClient(create_app(settings)) as client:
        monkeypatch.setattr(uploads, "MAX_FILE_SIZE", 5)
        response = submit(client, uuid4())
        assert response.status_code == 413
        assert response.json()["code"] == "upload_too_large"
    assert not root.exists()


def test_write_failure_does_not_queue_a_run(database_url, tmp_path, monkeypatch):
    root = tmp_path / "runs"

    def fail_write(upload, path: Path):
        path.write_bytes(b"partial")
        raise OSError("synthetic disk failure")

    key = uuid4()
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        with monkeypatch.context() as patch:
            patch.setattr(uploads, "_save_file", fail_write)
            failed = submit(client, key)
        assert failed.status_code == 503
        assert failed.json()["code"] == "service_unavailable"
        assert "synthetic disk failure" not in failed.text
        assert list(root.iterdir()) == []
        assert submit(client, key).status_code == 202


def test_damaged_ooxml_is_kept_for_file_level_processing():
    from io import BytesIO
    from zipfile import ZipFile

    from starlette.datastructures import UploadFile

    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("word/тест.xml", "<document />")
    damaged = bytearray(source.getvalue())
    central = damaged.index(b"PK\x01\x02")
    filename_start = central + 46
    damaged[filename_start + len("word/")] = 0xFF
    with BytesIO(damaged) as file:
        upload = UploadFile(file, size=len(damaged), filename="damaged.docx")
        assert uploads._file_format(upload) == "docx"
        assert file.tell() == 0

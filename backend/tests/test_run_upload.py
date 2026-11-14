from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import SpooledTemporaryFile
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Request
from sqlalchemy import create_engine, select, update
from starlette import formparsers

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
LEGACY_DIGEST = "0dd717792c2b0eb48d899c6de63ec77b1984c2da4556768ba787d42f35a9542f"


def submit(client, key, data=FIELDS, files=(REPORT, DOCUMENT)):
    return client.post(
        "/api/v0/runs", headers={"Idempotency-Key": str(key)}, data=data, files=list(files)
    )


def test_transferred_package_is_invisible_until_started(database_url, tmp_path):
    root = tmp_path / "runs"
    key = uuid4()
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:

        def prepare():
            return client.post(
                "/api/v0/runs/uploads",
                headers={"Idempotency-Key": str(key)},
                files=[REPORT, DOCUMENT],
            )

        prepared = prepare()
        assert prepared.status_code == 201
        upload_id = prepared.json()["upload_id"]
        assert prepare().json() == prepared.json()
        assert submit(client, key, data={}).status_code == 409
        assert client.get("/api/v0/runs").json()["items"] == []
        assert client.get(f"/api/v0/runs/{upload_id}").status_code == 404

        def start():
            return client.post(f"/api/v0/runs/uploads/{upload_id}/start")

        with ThreadPoolExecutor(max_workers=2) as executor:
            started, replay = executor.submit(start), executor.submit(start)
            first, second = started.result(), replay.result()
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json() == {"run_id": upload_id, "status": "queued"}
        assert first.headers["Location"] == f"/api/v0/runs/{upload_id}"
        assert client.delete(f"/api/v0/runs/uploads/{upload_id}").status_code == 204
        assert client.get(first.headers["Location"]).json()["status"] == "queued"
        assert (root / upload_id).is_dir()


def test_replaced_and_expired_prepared_packages_release_files(database_url, tmp_path):
    root = tmp_path / "runs"
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:

        def prepare():
            response = client.post(
                "/api/v0/runs/uploads",
                headers={"Idempotency-Key": str(uuid4())},
                files=[REPORT, DOCUMENT],
            )
            assert response.status_code == 201
            return response.json()["upload_id"]

        discarded = prepare()
        assert client.delete(f"/api/v0/runs/uploads/{discarded}").status_code == 204
        assert client.delete(f"/api/v0/runs/uploads/{discarded}").status_code == 204
        assert not (root / discarded).exists()

        expired = prepare()
        with client.app.state.engine.begin() as connection:
            connection.execute(
                update(Run)
                .where(Run.id == UUID(expired))
                .values(prepared_at=datetime.now(UTC) - timedelta(hours=2))
            )
        refused = client.post(f"/api/v0/runs/uploads/{expired}/start")
        assert refused.status_code == 410
        assert refused.json()["code"] == "upload_expired"
        assert prepare() != expired
        assert not (root / expired).exists()
        assert client.get("/api/v0/runs").json()["items"] == []


def test_package_revision_reuses_verified_originals_without_changing_source(database_url, tmp_path):
    root = tmp_path / "runs"
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        source = submit(client, uuid4()).json()["run_id"]
        pack_url = f"/api/v0/runs/{source}/pack"
        assert client.get(pack_url).status_code == 409
        with client.app.state.engine.begin() as connection:
            connection.execute(update(Run).where(Run.id == UUID(source)).values(status="completed"))
        documents = client.get(pack_url).json()["documents"]
        report = next(item for item in documents if item["role"] == "report")
        original = root / source / report["id"]
        payload = {"source_run_id": source, "retained_document_id": report["id"]}
        changed = ("documents", ("replacement.png", DOCUMENT[1][1]))

        def prepare(files):
            return client.post(
                "/api/v0/runs/uploads",
                headers={"Idempotency-Key": str(uuid4())},
                data=payload,
                files=files,
            )

        assert prepare([REPORT, changed]).status_code == 422
        prepared = prepare([changed])
        assert prepared.status_code == 201
        upload_id = prepared.json()["upload_id"]
        assert upload_id != source
        assert client.post(f"/api/v0/runs/uploads/{upload_id}/start").status_code == 202
        with client.app.state.engine.connect() as connection:
            row = (
                connection.execute(select(Run.__table__).where(Run.id == UUID(upload_id)))
                .mappings()
                .one()
            )
        assert row["scope"] == {}
        assert row["documents"][0]["id"] != report["id"]
        assert [item["name"] for item in row["documents"]] == [report["name"], "replacement.png"]
        assert (root / upload_id / row["documents"][0]["id"]).read_bytes() == original.read_bytes()
        assert client.get(pack_url).json()["documents"] == documents
        assert client.get(f"/api/v0/runs/{source}").json()["status"] == "completed"


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
            # Digest produced by the original upload implementation for these fixture bytes.
            assert row["request_digest"] == LEGACY_DIGEST
            assert [doc["role"] for doc in row["documents"]] == ["report", "supporting"]
            assert list(root.iterdir()) == [root / run_id]
            for file, item in zip((REPORT, DOCUMENT), row["documents"], strict=True):
                stored = root / run_id / item["id"]
                assert stored.read_bytes() == file[1][1]
    finally:
        engine.dispose()


def test_files_only_upload_replay_and_conflict(database_url, tmp_path):
    root = tmp_path / "runs"
    key = uuid4()
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            created, replay = executor.map(lambda _: submit(client, key, data={}), range(2))
        assert created.status_code == replay.status_code == 202
        assert created.json() == replay.json()
        run_id = created.json()["run_id"]
        assert created.headers["Location"] == replay.headers["Location"] == f"/api/v0/runs/{run_id}"
        assert client.get(f"/api/v0/runs/{run_id}").json()["progress"] == {
            "processed_documents": 0,
            "total_documents": 2,
        }
        assert client.get(f"/api/v0/runs/{run_id}/findings").json()["code"] == "result_pending"

        assert submit(client, key).status_code == 409
        changed = ("documents", ("support.png", DOCUMENT[1][1] + b" changed"))
        assert submit(client, key, data={}, files=(REPORT, changed)).status_code == 409
        with client.app.state.engine.connect() as connection:
            row = connection.execute(select(Run.__table__)).mappings().one()
        assert row["id"] == UUID(run_id)
        assert row["scope"] == {}
        assert [doc["role"] for doc in row["documents"]] == ["report", "supporting"]
        assert list(root.iterdir()) == [root / run_id]
        for upload, document in zip((REPORT, DOCUMENT), row["documents"], strict=True):
            content = upload[1][1]
            assert document["sha256"] == sha256(content).hexdigest()
            assert (root / run_id / document["id"]).read_bytes() == content


@pytest.mark.parametrize(
    ("data", "files", "status", "code"),
    [
        ({**FIELDS, "period_start": "2025-02-01"}, (REPORT, DOCUMENT), 422, "invalid_input"),
        ({"contract_number": "DEMO-1"}, (REPORT, DOCUMENT), 422, "invalid_input"),
        (
            {name: value for name, value in FIELDS.items() if name != "report_row_locator"},
            (REPORT, DOCUMENT),
            422,
            "invalid_input",
        ),
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


def test_malformed_multipart_header_returns_invalid_request(tmp_path):
    root = tmp_path / "runs"
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=root)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "multipart/form-data; boundary=doccheck",
            },
            content=b"--doccheck\r\nBAD HEADER\r\n\r\nvalue\r\n--doccheck--\r\n",
        )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert not root.exists()


def test_incomplete_multipart_does_not_queue_a_run(database_url, tmp_path):
    root = tmp_path / "runs"
    key = uuid4()
    encoded = Request(
        "POST", "http://testserver/api/v0/runs", data=FIELDS, files=[REPORT, DOCUMENT]
    )
    body = encoded.read()
    incomplete = body.removesuffix(b"--\r\n") + b"\r\n"
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        response = client.post(
            "/api/v0/runs",
            headers={"Idempotency-Key": str(key), "Content-Type": encoded.headers["Content-Type"]},
            content=incomplete,
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_request"
        assert not root.exists()
        assert submit(client, key).status_code == 202


def test_incomplete_multipart_closes_unfinished_upload(tmp_path, monkeypatch):
    opened = []

    def track_upload(*args, **kwargs):
        upload = SpooledTemporaryFile(*args, **kwargs)
        opened.append(upload)
        return upload

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", track_upload)
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={
                "Idempotency-Key": str(uuid4()),
                "Content-Type": "multipart/form-data; boundary=doccheck",
            },
            content=(
                b'--doccheck\r\nContent-Disposition: form-data; name="report"; '
                b'filename="report.pdf"\r\n\r\n%PDF-1.4 synthetic report'
            ),
        )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_request"
    assert len(opened) == 1
    assert opened[0].closed


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({**FIELDS, "contract_number": "DEMO\x00-1"}, "contract_number"),
        (
            {**FIELDS, "report_row_locator": r'{"kind":"page","page":1,"fragment_id":"f\u0000"}'},
            "report_row_locator",
        ),
    ],
)
def test_null_character_in_scope_is_invalid_input(database_url, tmp_path, data, field):
    root = tmp_path / "runs"
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        response = submit(client, uuid4(), data=data)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"
    assert response.json()["field"] == field
    assert not root.exists()


def test_null_character_in_filename_is_invalid_input(tmp_path):
    root = tmp_path / "runs"
    encoded = Request(
        "POST", "http://testserver/api/v0/runs", data=FIELDS, files=[REPORT, DOCUMENT]
    )
    body = encoded.read().replace(b'filename="support.png"', b'filename="sup\x00port.png"')
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=root)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v0/runs",
            headers={
                "Idempotency-Key": str(uuid4()),
                "Content-Type": encoded.headers["Content-Type"],
            },
            content=body,
        )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_input"
    assert response.json()["field"] == "documents"
    assert not root.exists()


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
            patch.setattr(uploads, "_copy_file", fail_write)
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


def test_ooxml_with_unsupported_zip_version_is_saved_for_processing(database_url, tmp_path):
    from io import BytesIO
    from zipfile import ZipFile, ZipInfo

    member = ZipInfo("word/document.xml")
    member.extract_version = 255
    with BytesIO() as buffer:
        with ZipFile(buffer, "w") as archive:
            archive.writestr(member, "<document />")
        damaged = buffer.getvalue()

    root = tmp_path / "runs"
    with TestClient(create_app(Settings(database_url, upload_root=root))) as client:
        response = submit(client, uuid4(), files=(REPORT, ("documents", ("damaged.docx", damaged))))

    assert response.status_code == 202
    run_id = UUID(response.json()["run_id"])
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            documents = connection.execute(
                select(Run.documents).where(Run.id == run_id)
            ).scalar_one()
        document = documents[1]
        assert document["format"] == "docx"
        assert (root / str(run_id) / document["id"]).read_bytes() == damaged
    finally:
        engine.dispose()

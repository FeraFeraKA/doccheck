import asyncio
import os
import subprocess
from datetime import UTC, datetime, timedelta
from io import BytesIO
from urllib.parse import quote
from uuid import UUID, uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect
from test_run_upload import DOCUMENT, REPORT, submit
from test_run_worker import _synthetic_result

from doccheck_backend import run_reads
from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckJob, CheckResult
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


def _complete(client, run_id, *, evidence_id: str = "amount-7") -> CheckResult:
    run = _manifest(client, run_id)
    result = _synthetic_result(run, partial=True).model_dump(mode="json")
    result["evidence"] = [
        {
            "id": evidence_id,
            "document_id": run.documents[0]["id"],
            "kind": "reported_value",
            "raw_value": "12 345,67",
            "normalized_value": "12345.67",
            "unit": "RUB",
            "method": "synthetic",
            "locator": {"kind": "page", "page": 1, "line": 3, "fragment_id": "demo-7"},
        }
    ]
    job = CheckJob.model_validate(
        {
            "run_id": run_id,
            "status": "completed_with_issues",
            "result": result,
            "error": {"code": "processing_completed_with_issues", "message": "Тестовая причина"},
        }
    )
    assert job.result is not None and job.error is not None
    _update_run(
        client,
        run_id,
        status=job.status,
        result=job.result.model_dump(mode="json"),
        error=job.error.model_dump(mode="json"),
    )
    return job.result


def test_archive_changes_membership_and_preserves_result(client):
    first, second, pending = (_create(client) for _ in range(3))
    result = _complete(client, first)
    _complete(client, second)
    assert client.put(f"{RUNS}/{pending}/archive").status_code == 409
    assert client.put(f"{RUNS}/{uuid4()}/archive").status_code == 404

    first_response = client.put(f"{RUNS}/{first}/archive")
    assert first_response.status_code == 200
    archived_at = first_response.json()["archived_at"]
    assert datetime.fromisoformat(archived_at).tzinfo is not None
    assert client.put(f"{RUNS}/{first}/archive").json() == {"archived_at": archived_at}
    assert client.put(f"{RUNS}/{second}/archive").status_code == 200
    assert client.get(f"{RUNS}/{first}").json()["archived_at"] == archived_at
    assert client.get(f"{RUNS}/{first}/findings").json() == result.model_dump(mode="json")
    assert [item["run_id"] for item in client.get(RUNS).json()["items"]] == [pending]
    page = client.get(RUNS, params={"view": "archive", "limit": 1}).json()
    assert [item["run_id"] for item in page["items"]] == [second]
    older = client.get(RUNS, params={"view": "archive", "cursor": page["next_cursor"]}).json()
    assert [item["run_id"] for item in older["items"]] == [first]

    assert client.delete(f"{RUNS}/{first}/archive").json() == {"archived_at": None}
    assert client.delete(f"{RUNS}/{first}/archive").json() == {"archived_at": None}
    assert {item["run_id"] for item in client.get(RUNS).json()["items"]} == {first, pending}
    remaining = client.get(RUNS, params={"view": "archive"}).json()["items"]
    assert [item["run_id"] for item in remaining] == [second]


def test_readers_return_verified_original_structure_and_page(client, tmp_path):
    docx = Document()
    docx.add_heading("Синтетический акт", 1)
    table = docx.add_table(rows=1, cols=3)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Итого"
    table.cell(0, 2).text = "12 345,67"
    docx.add_paragraph("Второй абзац")
    word = BytesIO()
    docx.save(word)

    book = Workbook()
    book.active.title = "Титул"
    ledger = book.create_sheet("Итоги")
    ledger["D71"] = 12345.67
    ledger["E71"] = "=SUM(D71:D72)"
    sheet = BytesIO()
    book.save(sheet)

    pdf = BytesIO()
    with (
        Image.new("RGB", (100, 120), "white") as first,
        Image.new("RGB", (100, 120), "black") as second,
    ):
        first.save(pdf, "PDF", save_all=True, append_images=[second])
    upload = submit(
        client,
        uuid4(),
        files=(
            ("report", ("report.pdf", pdf.getvalue())),
            ("documents", ("act.docx", word.getvalue())),
            ("documents", ("ledger.xlsx", sheet.getvalue())),
        ),
    )
    assert upload.status_code == 202
    run_id = upload.json()["run_id"]
    report_id, act_id, sheet_id = [item["id"] for item in _manifest(client, run_id).documents]
    base = f"{RUNS}/{run_id}/documents"

    office = client.get(f"{base}/{act_id}/preview")
    assert office.status_code == 200
    assert office.headers["cache-control"] == "no-store"
    assert office.json() == {
        "blocks": [
            {"paragraph": 1, "text": "Синтетический акт", "heading": True},
            {
                "table": 1,
                "rows": [
                    [
                        {"column": 1, "span": 2, "text": "Итого"},
                        {"column": 3, "span": 1, "text": "12 345,67"},
                    ]
                ],
            },
            {"paragraph": 2, "text": "Второй абзац", "heading": False},
        ],
        "truncated": False,
    }
    ledger_response = client.get(
        f"{base}/{sheet_id}/preview",
        params={
            "sheet": "Итоги",
            "row": 71,
            "column": 4,
        },
    )
    assert ledger_response.status_code == 200
    assert ledger_response.json() == {
        "sheet": "Итоги",
        "sheets": ["Титул", "Итоги"],
        "row": 71,
        "column": 4,
        "last_row": 71,
        "last_column": 5,
        "rows": [["12345.67", "=SUM(D71:D72)"]],
    }
    raster = client.get(f"{base}/{report_id}/page-preview", params={"page": 2})
    assert raster.status_code == 200
    assert raster.headers["content-type"] == "image/png"
    assert raster.headers["x-document-pages"] == "2"
    with Image.open(BytesIO(raster.content)) as rasterized:
        assert rasterized.convert("RGB").getpixel((10, 10)) == (0, 0, 0)
    assert client.get(f"{base}/{report_id}/page-preview", params={"page": 3}).status_code == 404
    assert client.get(f"{base}/{act_id}/page-preview").status_code == 415

    other_run = _create(client)
    assert client.get(f"{RUNS}/{other_run}/documents/{act_id}/preview").status_code == 404
    path = tmp_path / run_id / act_id
    changed = word.getvalue()
    path.write_bytes(bytes([changed[0] ^ 1]) + changed[1:])
    assert client.get(f"{base}/{act_id}/preview").status_code == 404


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
    assert set(page["items"][0]) == {"run_id", "status", "created_at", "error", "document_count"}
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


@pytest.mark.parametrize("replace", [False, True])
def test_changed_original_is_unavailable_for_document_and_fragments(client, tmp_path, replace):
    run_id = _create(client)
    report = _manifest(client, run_id).documents[0]["id"]
    _complete(client, run_id)
    base_url = f"{RUNS}/{run_id}/documents/{report}"
    endpoints = (
        (base_url, {}),
        (f"{base_url}/fragments/amount-7", {}),
        (f"{base_url}/fragments", {"evidence_id": "amount-7"}),
    )
    for url, params in endpoints:
        assert client.get(url, params=params).status_code == 200

    original = tmp_path / run_id / report
    original_bytes = original.read_bytes()
    changed = original_bytes[:-1] + b"!"
    if replace:
        replacement = original.with_suffix(".temporary")
        replacement.write_bytes(changed)
        replacement.replace(original)
    else:
        original.write_bytes(changed)

    for url, params in endpoints:
        response = client.get(url, params=params)
        assert (response.status_code, response.json()["code"]) == (404, "document_not_found")
    assert client.get(f"{RUNS}/{run_id}/findings").status_code == 200


def test_evidence_ids_round_trip_through_both_fragment_routes(client):
    run_id = _create(client)
    other_id = _create(client)
    report, support = [document["id"] for document in _manifest(client, run_id).documents]
    foreign = _manifest(client, other_id).documents[0]["id"]
    run_url = f"{RUNS}/{run_id}"
    fragments = f"{run_url}/documents/{report}/fragments"
    cases = (
        ("строка-1", True),
        ("formula.amount", True),
        ("сумма + 100%?#", True),
        # TestClient decodes the ASGI path twice. The literal percent pair is
        # verified through the query route here and through Uvicorn separately.
        ("prefix%2Fsuffix", False),
        ("section/subsection", False),
        ("section\\subsection", False),
        (".", False),
        ("..", False),
    )
    pending = client.get(fragments, params={"evidence_id": cases[0][0]})
    assert (pending.status_code, pending.json()["code"]) == (409, "result_pending")
    for evidence_id, common_path in cases:
        _complete(client, run_id, evidence_id=evidence_id)
        saved = client.get(f"{run_url}/findings").json()["evidence"][0]
        assert saved["id"] == evidence_id
        query = client.get(fragments, params={"evidence_id": evidence_id})
        assert query.status_code == 200
        assert query.json() == saved
        if common_path:
            path = client.get(f"{fragments}/{quote(evidence_id, safe='')}")
            assert path.status_code == 200
            assert path.json() == saved

    for document_id, code in ((support, "fragment_not_found"), (foreign, "document_not_found")):
        response = client.get(
            f"{run_url}/documents/{document_id}/fragments", params={"evidence_id": ".."}
        )
        assert (response.status_code, response.json()["code"]) == (404, code)

    for params in ({}, {"evidence_id": ""}):
        response = client.get(fragments, params=params)
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_input"
        assert response.json()["field"] == "evidence_id"


def test_missing_runs_and_corrupt_result_use_contract_errors(client):
    for run_id in (str(uuid4()), "not-a-uuid"):
        for suffix in ("", "/findings", "/documents/unknown", "/documents/unknown/fragments/a"):
            response = client.get(f"{RUNS}/{run_id}{suffix}")
            assert (response.status_code, response.json()["code"]) == (404, "run_not_found")
    run_id = _create(client)
    _update_run(client, run_id, status="completed")
    response = client.get(f"{RUNS}/{run_id}/findings")
    assert (response.status_code, response.json()["code"]) == (503, "service_unavailable")


def test_fragment_preview_reads_only_the_addressed_original_text(client, tmp_path, monkeypatch):
    docx = Document()
    context = "Работа 🧮: 12 345,67 руб."
    docx.add_paragraph(context)
    docx.add_paragraph("Другое место в документе")
    file = BytesIO()
    docx.save(file)
    response = submit(client, uuid4(), files=(REPORT, ("documents", ("act.docx", file.getvalue()))))
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    run = _manifest(client, run_id)
    report, act = (item["id"] for item in run.documents)
    url = f"{RUNS}/{run_id}/documents/{act}/fragment-preview"
    evidence_id = "act/сумма"
    query = {"evidence_id": evidence_id}
    assert client.get(url, params=query).status_code == 409
    assert client.get(url).json() == {
        "code": "invalid_input",
        "message": "Некорректный параметр",
        "field": "evidence_id",
    }
    result = _synthetic_result(run).model_dump(mode="json")
    result["evidence"] = [
        {
            "id": evidence_id,
            "document_id": act,
            "kind": "amount",
            "raw_value": "12 345,67",
            "normalized_value": "12345.67",
            "unit": "RUB",
            "method": "synthetic",
            "locator": {"kind": "paragraph", "paragraph": 1},
        }
    ]
    saved = CheckResult.model_validate(result)
    _update_run(client, run_id, status="completed", result=saved.model_dump(mode="json"))
    preview = client.get(url, params=query)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert preview.json()["text"] == context
    highlight = preview.json()["highlight"]
    raw = context.encode("utf-8")[highlight["start_byte"] : highlight["end_byte"]]
    assert raw.decode("utf-8") == "12 345,67"
    other = client.get(f"{RUNS}/{run_id}/documents/{report}/fragment-preview", params=query)
    assert (other.status_code, other.json()["code"]) == (404, "fragment_not_found")
    path = tmp_path / run_id / act
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    changed = client.get(url, params=query)
    assert (changed.status_code, changed.json()["code"]) == (404, "document_not_found")

    path.write_bytes(original)
    open_original = run_reads._open_original

    def rewrite_after_verification(*args):
        stream, size = open_original(*args)
        with path.open("r+b") as replacement:
            replacement.write(bytes([original[0] ^ 1]))
        return stream, size

    monkeypatch.setattr(run_reads, "_open_original", rewrite_after_verification)
    changed_after_open = client.get(url, params=query)
    assert (changed_after_open.status_code, changed_after_open.json()["code"]) == (
        404,
        "document_not_found",
    )


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


@pytest.mark.parametrize("failure", ["read", "disconnect", "cancel"])
def test_download_closes_original_when_streaming_stops(monkeypatch, tmp_path, failure):
    class Original(BytesIO):
        def read(self, size: int = -1) -> bytes:
            if failure == "read":
                raise OSError("test read error")
            return super().read(size)

    async def receive():
        raise AssertionError("ASGI 2.4 detects disconnect on send")

    sent = []

    async def send(message):
        sent.append(message["type"])
        if message["type"] == "http.response.body":
            if failure == "disconnect":
                raise BrokenPipeError
            if failure == "cancel":
                raise asyncio.CancelledError

    original = Original(b"data")
    monkeypatch.setattr(run_reads, "get_run_document", lambda *args: (original, 4, "example.pdf"))
    settings = Settings("postgresql+psycopg://localhost/doccheck_unused", upload_root=tmp_path)
    application = create_app(settings)
    with TestClient(application):
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "method": "GET",
            "scheme": "http",
            "path": f"{RUNS}/example/documents/original",
            "headers": [],
            "query_string": b"",
        }
        expected = asyncio.CancelledError if failure == "cancel" else ClientDisconnect
        with pytest.raises(expected):
            asyncio.run(application(scope, receive, send))

    assert sent[0] == "http.response.start"
    assert original.closed


def test_history_finding_filters_use_saved_counts_before_pagination(client):
    mixed, complete, empty, pending = [_create(client) for _ in range(4)]
    for run_id, counts in (
        (mixed, {"verified": 0, "discrepancy": 1, "unverified": 2}),
        (complete, {"verified": 2, "discrepancy": 0, "unverified": 0}),
        (empty, {"verified": 0, "discrepancy": 0, "unverified": 0}),
    ):
        # The history projection reads only these keys. Full result validation
        # and document bindings are covered by tests of the findings endpoint.
        _update_run(
            client,
            run_id,
            status="completed",
            result={"summary": {"counts": counts}, "synthetic": True},
        )

    cases = [("discrepancy", mixed), ("unverified", mixed), ("verified", complete)]
    for finding, expected in cases:
        page = client.get(RUNS, params={"finding": finding, "limit": 1})
        assert page.status_code == 200
        assert page.json()["next_cursor"] is None
        assert [item["run_id"] for item in page.json()["items"]] == [expected]
        assert page.json()["items"][0]["report_number"] is None
        assert page.json()["items"][0]["synthetic"] is True

    history = client.get(RUNS).json()["items"]
    assert {item["run_id"] for item in history} == {mixed, complete, empty, pending}
    assert "counts" not in next(item for item in history if item["run_id"] == pending)

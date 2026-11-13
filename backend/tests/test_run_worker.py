import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_run_upload import DOCUMENT, REPORT, submit

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.contracts import RESULT_SCHEMA_VERSION, CheckJob, CheckResult
from doccheck_backend.database import create_database_engine
from doccheck_backend.models import Run
from doccheck_backend.run_worker import StoredRun, WorkerSessionLost, run_document_worker


@pytest.fixture
def engine(database_url):
    engine = create_database_engine(database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def queue(database_url, tmp_path):
    with TestClient(create_app(Settings(database_url, upload_root=tmp_path))) as client:
        yield client


def _enqueue(queue, *, infer_scope=False):
    response = submit(queue, uuid4(), data={}) if infer_scope else submit(queue, uuid4())
    assert response.status_code == 202
    return UUID(response.json()["run_id"])


def _read_run(engine: Engine, run_id: UUID) -> Run:
    with Session(engine) as session:
        return session.scalars(select(Run).where(Run.id == run_id)).one()


def _synthetic_result(run: StoredRun, *, partial: bool = False) -> CheckResult:
    documents = []
    for item in run.documents:
        damaged = partial and item["role"] == "supporting"
        errors = (
            [{"id": "read-error", "code": "unreadable", "message": "Синтетическая ошибка чтения"}]
            if damaged
            else []
        )
        documents.append(
            {
                "id": item["id"],
                "name": item["name"],
                "sha256": item["sha256"],
                "format": item["format"],
                "role": "report" if item["role"] == "report" else "support",
                "parse_status": "error" if damaged else "parsed",
                "decision": {
                    "state": "parse_error" if damaged else "include",
                    "reason_code": "unreadable" if damaged else "synthetic",
                    "message": "Тест проверки сохранённого результата",
                    "evidence_refs": [],
                },
                "errors": errors,
            }
        )
    return CheckResult.model_validate(
        {
            "schema_version": RESULT_SCHEMA_VERSION,
            "run_id": str(run.id),
            "synthetic": True,
            "scope": run.scope
            if run.scope is not None
            else {
                # Synthetic adapter output, independent of the upload request.
                "report_document_id": run.report_document_id,
                "contract_number": "INFERRED-SYNTHETIC",
                "period_start": "2025-03-01",
                "period_end": "2025-03-31",
                "report_row_locator": {"kind": "page", "page": 1, "line": 2},
            },
            "versions": {
                "code_revision": "test",
                "rules_version": "test",
                "ml_module_version": None,
                "ml_policy_version": None,
                "model_revision": None,
            },
            "documents": documents,
            "evidence": [],
            "rows": [],
            "summary": {
                "counts": {"verified": 0, "discrepancy": 0, "unverified": 0},
                "primary_issues": [],
                "conclusion": "Синтетический результат теста сохранения",
            },
        }
    )


@pytest.mark.parametrize("partial", [False, True])
def test_persists_processor_outcome(engine, queue, tmp_path, partial):
    run_id = _enqueue(queue)
    status = "completed_with_issues" if partial else "completed"

    def process(run, directory):
        assert run.id == run_id
        assert directory == tmp_path / str(run_id)
        for item, (_, (_, content)) in zip(run.documents, (REPORT, DOCUMENT), strict=True):
            assert (directory / str(item["id"])).read_bytes() == content
        assert _read_run(engine, run.id).status == "processing"
        return CheckJob(
            run_id=str(run.id),
            status=status,
            result=_synthetic_result(run, partial=partial),
            error=None,
        )

    assert run_document_worker(engine, tmp_path, process, once=True)
    stored = _read_run(engine, run_id)
    saved = CheckJob.model_validate(
        {
            "run_id": str(run_id),
            "status": stored.status,
            "result": stored.result,
            "error": stored.error,
        }
    )
    assert saved.status == status
    assert saved.result.synthetic is True
    assert bool(saved.result.documents[1].errors) is partial
    assert stored.created_at <= stored.started_at <= stored.finished_at


def test_accepts_inferred_scope_and_serves_saved_result(engine, queue, tmp_path):
    run_id = _enqueue(queue, infer_scope=True)

    def process(run, directory):
        assert run.scope is None
        assert run.report_document_id == run.documents[0]["id"]
        assert (directory / run.report_document_id).read_bytes() == REPORT[1][1]
        return successful_test_processor(run, directory)

    assert run_document_worker(engine, tmp_path, process, once=True)
    saved = _read_run(engine, run_id)
    assert saved.status == "completed"
    assert saved.scope == {}
    assert saved.result["scope"]["report_document_id"] == saved.documents[0]["id"]
    assert saved.result["scope"]["contract_number"] == "INFERRED-SYNTHETIC"
    assert queue.get(f"/api/v0/runs/{run_id}").json()["status"] == "completed"
    assert queue.get(f"/api/v0/runs/{run_id}/findings").json() == saved.result


def test_rejects_inferred_scope_for_a_different_report(engine, queue, tmp_path):
    run_id = _enqueue(queue, infer_scope=True)

    def process(run, directory):
        result = _synthetic_result(run)
        result.documents[0].role = "support"
        result.documents[1].role = "report"
        result.scope.report_document_id = result.documents[1].id
        return CheckJob(run_id=str(run.id), status="completed", result=result, error=None)

    assert run_document_worker(engine, tmp_path, process, once=True)
    saved = _read_run(engine, run_id)
    assert saved.status == "failed"
    assert saved.result is None
    assert saved.error["code"] == "processing_failed"


def test_rejects_inferred_address_for_a_falsely_relabelled_report(engine, queue, tmp_path):
    run_id = _enqueue(queue, infer_scope=True)

    def process(run, directory):
        data = _synthetic_result(run).model_dump(mode="json")
        # This result validates against its own format and keeps all original IDs and hashes.
        data["documents"][0]["format"] = "xlsx"
        data["scope"]["report_row_locator"] = {"kind": "sheet", "sheet": "Synthetic", "range": "A1"}
        return CheckJob(
            run_id=str(run.id),
            status="completed",
            result=CheckResult.model_validate(data),
            error=None,
        )

    assert run_document_worker(engine, tmp_path, process, once=True)
    saved = _read_run(engine, run_id)
    assert saved.status == "failed"
    assert saved.result is None
    assert saved.error["code"] == "processing_failed"


def test_keeps_unsupported_format_as_a_partial_file_error(engine, queue, tmp_path):
    run_id = _enqueue(queue, infer_scope=True)

    def process(run, directory):
        data = _synthetic_result(run, partial=True).model_dump(mode="json")
        unsupported = data["documents"][1]
        unsupported["format"] = None
        unsupported["errors"][0]["code"] = "unsupported_format"
        return CheckJob(
            run_id=str(run.id),
            status="completed_with_issues",
            result=CheckResult.model_validate(data),
            error=None,
        )

    assert run_document_worker(engine, tmp_path, process, once=True)
    saved = _read_run(engine, run_id)
    assert saved.status == "completed_with_issues"
    assert saved.result["documents"][1]["format"] is None


def test_rejects_changed_explicit_scope(engine, queue, tmp_path):
    run_id = _enqueue(queue)

    def process(run, directory):
        result = _synthetic_result(run)
        result.scope.contract_number = "NOT-THE-UPLOADED-CONTRACT"
        return CheckJob(run_id=str(run.id), status="completed", result=result, error=None)

    assert run_document_worker(engine, tmp_path, process, once=True)
    saved = _read_run(engine, run_id)
    assert saved.status == "failed"
    assert saved.result is None
    assert saved.error["code"] == "processing_failed"


def test_processor_failure_records_safe_error(engine, queue, tmp_path, caplog):
    run_id = _enqueue(queue)

    def fail(run, directory):
        raise RuntimeError("private adapter detail")

    assert run_document_worker(engine, tmp_path, fail, once=True)
    stored = _read_run(engine, run_id)
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error["code"] == "processing_failed"
    assert "private adapter detail" not in repr(stored.error)
    assert "private adapter detail" not in caplog.text


def test_partial_outcome_keeps_safe_top_level_indicator(engine, queue, tmp_path):
    run_id = _enqueue(queue)

    def process(run, directory):
        return CheckJob.model_validate(
            {
                "run_id": str(run.id),
                "status": "completed_with_issues",
                "result": _synthetic_result(run),
                "error": {"code": "private_code", "message": "private adapter detail"},
            }
        )

    assert run_document_worker(engine, tmp_path, process, once=True)
    stored = _read_run(engine, run_id)
    assert stored.status == "completed_with_issues"
    assert stored.result is not None
    assert stored.error["code"] == "processing_completed_with_issues"
    assert "private" not in repr(stored.error)


@pytest.mark.parametrize("infer_scope", [False, True])
def test_rejects_result_for_a_different_document_version(engine, queue, tmp_path, infer_scope):
    run_id = _enqueue(queue, infer_scope=infer_scope)

    def process(run, directory):
        result = _synthetic_result(run)
        result.documents[1].sha256 = "0" * 64
        return CheckJob(run_id=str(run.id), status="completed", result=result, error=None)

    assert run_document_worker(engine, tmp_path, process, once=True)
    stored = _read_run(engine, run_id)
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error["code"] == "processing_failed"


def test_rejects_contract_text_that_postgresql_cannot_store(engine, queue, tmp_path):
    run_id = _enqueue(queue)

    def process(run, directory):
        result = _synthetic_result(run)
        result.summary.conclusion = "invalid\x00text"
        return CheckJob(run_id=str(run.id), status="completed", result=result, error=None)

    assert run_document_worker(engine, tmp_path, process, once=True)
    stored = _read_run(engine, run_id)
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error["code"] == "processing_failed"


@pytest.mark.parametrize("different_search_path", [False, True])
def test_live_worker_owns_queue_until_its_processing_finishes(
    engine, queue, tmp_path, database_url, different_search_path
):
    active = _enqueue(queue)
    waiting = _enqueue(queue)
    running = Event()
    release = Event()

    def process(run, directory):
        assert run.id == active
        running.set()
        assert release.wait(10)
        return CheckJob(
            run_id=str(run.id), status="completed", result=_synthetic_result(run), error=None
        )

    contender = engine
    if different_search_path:
        empty_schema = f"worker_prefix_{uuid4().hex}"
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {empty_schema}"))
        url = make_url(database_url)
        options = url.query["options"].replace("search_path=", f"search_path={empty_schema},")
        contender = create_database_engine(url.update_query_dict({"options": options}))
        with contender.connect() as connection:
            assert connection.scalar(text("SELECT current_schema()")) == empty_schema

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            owner = executor.submit(run_document_worker, engine, tmp_path, process, once=True)
            try:
                assert running.wait(5)
                assert run_document_worker(contender, tmp_path, process, once=True) is False
                assert _read_run(engine, active).status == "processing"
                assert _read_run(engine, waiting).status == "queued"
            finally:
                release.set()
            assert owner.result(timeout=5) is True
    finally:
        if different_search_path:
            contender.dispose()
            with engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {empty_schema}"))
    assert _read_run(engine, active).status == "completed"


def test_invalidated_worker_session_cannot_reconnect_and_write(engine, queue, tmp_path):
    run_id = _enqueue(queue)
    worker_connection = None

    def capture(conn, cursor, statement, parameters, context, executemany):
        nonlocal worker_connection
        if "pg_try_advisory_lock" in statement:
            worker_connection = conn

    def process(run, directory):
        assert worker_connection is not None
        worker_connection.invalidate()
        return successful_test_processor(run, directory)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(WorkerSessionLost):
            run_document_worker(engine, tmp_path, process, once=True)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert _read_run(engine, run_id).status == "processing"
    assert run_document_worker(engine, tmp_path, successful_test_processor, once=True)
    stored = _read_run(engine, run_id)
    assert stored.status == "failed"
    assert stored.error["code"] == "worker_interrupted"


def test_disconnect_leaves_recovery_to_next_owner(engine, queue, tmp_path):
    abandoned = _enqueue(queue)
    waiting = _enqueue(queue)
    worker_pid = None

    def capture(conn, clause, multiparams, params, execution_options):
        nonlocal worker_pid
        if "pg_try_advisory_lock" in str(clause):
            worker_pid = conn.connection.dbapi_connection.info.backend_pid

    def process(run, directory):
        assert run.id == abandoned
        assert worker_pid is not None
        with engine.begin() as connection:
            assert connection.scalar(select(func.pg_terminate_backend(worker_pid, 5000)))
        assert run_document_worker(engine, tmp_path, successful_test_processor, once=True)
        return successful_test_processor(run, directory)

    event.listen(engine, "before_execute", capture)
    try:
        with pytest.raises(DBAPIError):
            run_document_worker(engine, tmp_path, process, once=True)
    finally:
        event.remove(engine, "before_execute", capture)
    stored = _read_run(engine, abandoned)
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error["code"] == "worker_interrupted"
    assert _read_run(engine, waiting).status == "completed"


def blocking_test_processor(run, directory):
    time.sleep(60)


def successful_test_processor(run, directory):
    return CheckJob(
        run_id=str(run.id), status="completed", result=_synthetic_result(run), error=None
    )


def failing_test_processor(run, directory):
    raise RuntimeError("private test adapter detail")


@pytest.mark.parametrize("succeeds", [True, False])
def test_explicit_processor_cli_exposes_saved_outcome(queue, tmp_path, database_url, succeeds):
    run_id = _enqueue(queue, infer_scope=True)
    location = f"/api/v0/runs/{run_id}"
    assert queue.get(location).json()["status"] == "queued"
    assert queue.get(f"{location}/findings").json()["code"] == "result_pending"

    function = "successful_test_processor" if succeeds else "failing_test_processor"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "doccheck_backend.run_worker",
            "--once",
            "--processor",
            f"test_run_worker:{function}",
        ],
        env={
            **os.environ,
            "DATABASE_URL": database_url,
            "DOCCHECK_UPLOAD_ROOT": str(tmp_path),
            "PYTHONPATH": os.path.dirname(__file__),
        },
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    state = queue.get(location).json()
    findings = queue.get(f"{location}/findings")
    if succeeds:
        assert state["status"] == "completed"
        assert state["error"] is None
        assert findings.status_code == 200
        assert findings.json()["run_id"] == str(run_id)
        assert findings.json()["synthetic"] is True
        assert findings.json()["rows"] == []
    else:
        assert state["status"] == "failed"
        assert state["error"]["code"] == "processing_failed"
        assert findings.status_code == 409
        assert findings.json()["code"] == "run_failed"
        assert "private test adapter detail" not in completed.stderr + findings.text


def test_restart_marks_abandoned_claim_failed(engine, queue, tmp_path, database_url):
    abandoned = _enqueue(queue)
    waiting = _enqueue(queue)
    command = [sys.executable, "-m", "doccheck_backend.run_worker", "--once"]
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "DOCCHECK_UPLOAD_ROOT": str(tmp_path),
        "PYTHONPATH": os.path.dirname(__file__),
    }
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for flags in ([], ["--processor", "missing_module:process"]):
        missing = subprocess.run(
            [*command, *flags], env=environment, creationflags=creationflags, timeout=15
        )
        assert missing.returncode != 0
        assert _read_run(engine, abandoned).status == "queued"

    process = subprocess.Popen(
        [*command, "--processor", "test_run_worker:blocking_test_processor"],
        env=environment,
        creationflags=creationflags,
    )
    try:
        deadline = time.monotonic() + 15
        while _read_run(engine, abandoned).status != "processing":
            assert process.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)

    # PostgreSQL may still be closing the dead process's socket after wait() returns.
    deadline = time.monotonic() + 5
    while True:
        restarted = subprocess.run(
            [*command, "--processor", "test_run_worker:successful_test_processor"],
            env=environment,
            creationflags=creationflags,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if restarted.returncode == 0:
            break
        assert "Another document worker owns this queue" in restarted.stderr, restarted.stderr
        assert time.monotonic() < deadline
        time.sleep(0.05)

    stored = _read_run(engine, abandoned)
    assert stored.status == "failed"
    assert stored.result is None
    assert stored.error["code"] == "worker_interrupted"
    assert stored.finished_at >= stored.started_at
    assert _read_run(engine, waiting).status == "completed"

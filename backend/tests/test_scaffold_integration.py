"""Real PostgreSQL + HTTP + separate worker checks; no OCR or financial fixture."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import httpx
import psycopg
import pytest
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def process_environment(database_url: str) -> dict[str, str]:
    return {
        **os.environ,
        "DATABASE_URL": database_url,
        "SYNTHETIC_DELAY_SECONDS": "3",
        "WORKER_POLL_SECONDS": "0.05",
    }


@contextmanager
def running_process(
    arguments: list[str], environment: dict[str, str]
) -> Iterator[subprocess.Popen[bytes]]:
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(
            [sys.executable, *arguments],
            cwd=BACKEND,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=NO_WINDOW,
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


@contextmanager
def running_api(
    database_url: str, expected_health: int = 200, *, environment: Mapping[str, str] | None = None
) -> Iterator[httpx.Client]:
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    arguments = [
        "-m",
        "uvicorn",
        "doccheck_backend.api:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-access-log",
    ]
    with running_process(
        arguments, {**process_environment(database_url), **(environment or {})}
    ) as process:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
        ) as client:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                assert process.poll() is None, "API exited before accepting HTTP requests"
                try:
                    response = client.get("/health")
                except httpx.ConnectError:
                    time.sleep(0.05)
                    continue
                if response.status_code == expected_health:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("API did not reach expected health state")
            yield client


def wait_for_status(client: httpx.Client, job_id: str, expected: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/synthetic-jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] == expected:
            return job
        assert job["status"] != "failed", "Synthetic worker unexpectedly failed"
        time.sleep(0.03)
    pytest.fail(f"Job did not reach {expected}")


def test_persistent_job_lifecycle_with_separate_worker_and_responsive_api(
    run_migrations,
    database_url: str,
) -> None:
    with running_api(database_url) as client:
        assert client.get("/health").json() == {"status": "ok", "database": "ok"}
        started = time.monotonic()
        response = client.post("/api/synthetic-jobs")
        assert time.monotonic() - started < 2
        assert response.status_code == 201
        queued = response.json()
        assert queued["status"] == "queued"
        assert queued["synthetic"] is True
        assert queued["result"] is None and queued["error"] is None
        assert queued["started_at"] is None and queued["finished_at"] is None
        job_id = queued["id"]
        # Waiting without a worker must not execute a job inside the API process.
        time.sleep(0.2)
        assert client.get(f"/api/synthetic-jobs/{job_id}").json()["status"] == "queued"

    # Restart API and re-run initialization: the same PostgreSQL job must survive both.
    run_migrations(database_url)
    with running_api(database_url) as client:
        assert client.get(f"/api/synthetic-jobs/{job_id}").json() == queued
        with running_process(
            ["-m", "doccheck_backend.worker", "--once"], process_environment(database_url)
        ) as worker:
            processing = wait_for_status(client, job_id, "processing")
            assert processing["started_at"] is not None
            assert processing["result"] is None and processing["finished_at"] is None
            started = time.monotonic()
            assert client.get("/health").status_code == 200
            next_response = client.post("/api/synthetic-jobs")
            assert next_response.status_code == 201
            assert time.monotonic() - started < 2
            next_job = next_response.json()
            assert next_job["status"] == "queued"
            completed = wait_for_status(client, job_id, "completed")
            assert worker.wait(timeout=5) == 0
        assert completed["synthetic"] is True
        assert completed["result"]["synthetic"] is True
        assert isinstance(completed["result"]["message"], str)
        assert completed["finished_at"] is not None and completed["error"] is None
        assert client.get(f"/api/synthetic-jobs/{next_job['id']}").json()["status"] == "queued"

    # Inspect PostgreSQL independently of the API and confirm persistence after another restart.
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        assert connection.execute(
            "SELECT status FROM synthetic_jobs WHERE id = %s", (job_id,)
        ).fetchone() == ("completed",)
    with running_api(database_url) as client:
        assert client.get(f"/api/synthetic-jobs/{job_id}").json() == completed


def test_job_lookup_rejects_invalid_or_missing_ids(database_url: str) -> None:
    with running_api(database_url) as client:
        assert client.get("/api/synthetic-jobs/not-a-uuid").status_code == 422
        assert client.get(f"/api/synthetic-jobs/{uuid4()}").status_code == 404


def test_worker_with_empty_queue_exits_without_creating_results(database_url: str) -> None:
    with running_process(
        ["-m", "doccheck_backend.worker", "--once"], process_environment(database_url)
    ) as worker:
        assert worker.wait(timeout=10) == 0
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn) as connection:
        assert connection.execute("SELECT count(*) FROM synthetic_jobs").fetchone() == (0,)


def test_unavailable_database_returns_safe_service_error() -> None:
    # A held, non-listening socket prevents accidental connection to a real service.
    with socket.socket() as unavailable:
        unavailable.bind(("127.0.0.1", 0))
        port = unavailable.getsockname()[1]
        dsn = f"postgresql+psycopg://synthetic_user:synthetic-secret@127.0.0.1:{port}/missing"
        with running_api(dsn, expected_health=503) as client:
            for method, path in [
                ("GET", "/health"),
                ("POST", "/api/synthetic-jobs"),
                ("GET", f"/api/synthetic-jobs/{uuid4()}"),
            ]:
                response = client.request(method, path)
                assert response.status_code == 503
                assert isinstance(response.json()["detail"], str)
                assert "synthetic-secret" not in response.text
                assert "synthetic_user" not in response.text
                assert "127.0.0.1" not in response.text

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.render_demo import _environment

_RUNS = "/api/v0/runs"
_UNUSED_DB = "postgresql+psycopg://unused:unused@127.0.0.1:1/unused"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", _RUNS),
        ("GET", _RUNS),
        ("GET", f"{_RUNS}/run"),
        ("GET", f"{_RUNS}/run/findings"),
        ("GET", f"{_RUNS}/run/exports/xlsx"),
        ("GET", f"{_RUNS}/run/documents/file"),
        ("GET", f"{_RUNS}/run/documents/file/fragments/evidence"),
        ("GET", f"{_RUNS}/run/documents/file/fragments?evidence_id=evidence"),
        ("GET", f"{_RUNS}/run/documents/file/fragment-preview?evidence_id=evidence"),
    ],
)
def test_public_demo_blocks_document_routes_without_opening_storage(
    tmp_path: Path, method: str, path: str
) -> None:
    root = tmp_path / "never-created"
    with TestClient(create_app(Settings(_UNUSED_DB, upload_root=root, public_demo=True))) as client:
        response = client.request(
            method, path, content=b"invalid multipart", headers={"Idempotency-Key": str(uuid4())}
        )

    assert response.status_code == 503
    assert response.json() == {
        "code": "service_unavailable",
        "message": "Операции с документами доступны в локальной установке",
    }
    assert not root.exists()


def test_render_bootstrap_requires_explicit_demo_mode_and_dedicated_url(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _UNUSED_DB)
    monkeypatch.delenv("DOCCHECK_PUBLIC_DEMO", raising=False)
    monkeypatch.delenv("DOCCHECK_RENDER_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="requires DOCCHECK_PUBLIC_DEMO=1"):
        _environment()
    monkeypatch.setenv("DOCCHECK_PUBLIC_DEMO", "1")
    with pytest.raises(ValueError, match="dedicated PostgreSQL URL"):
        _environment()
    monkeypatch.setenv("DOCCHECK_RENDER_DATABASE_URL", "postgresql://demo:u%40x@db/demo")
    assert _environment()["DATABASE_URL"] == "postgresql+psycopg://demo:u%40x@db/demo"


def test_invalid_demo_mode_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _UNUSED_DB)
    monkeypatch.setenv("DOCCHECK_PUBLIC_DEMO", "yes")
    with pytest.raises(ValueError, match="must be 0 or 1"):
        Settings.from_env()

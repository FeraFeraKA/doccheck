"""Public trial backed only by a local, preinstalled synthetic package."""

import hashlib
import json
import os
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.datastructures import FormData, Headers, UploadFile

from doccheck_backend.api import create_app
from doccheck_backend.config import Settings
from doccheck_backend.models import Run
from doccheck_backend.uploads import MAX_FILE_SIZE, MAX_PACKAGE_SIZE, UploadError, store_run

app = create_app()
_api_lifespan = app.router.lifespan_context
_BUCKET_SECONDS = 120


@asynccontextmanager
async def _trial_lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    if (
        settings.public_demo
        or settings.upload_root.name != "public-trial-uploads"
        or settings.database_url != "postgresql+psycopg:///doccheck_public_trial"
    ):
        raise ValueError("The public trial requires its separate database and storage")
    with _package():
        pass
    async with _api_lifespan(application):
        yield


app.router.lifespan_context = _trial_lifespan
_FORMATS = {".pdf", ".xlsx", ".docx", ".png"}


@contextmanager
def _package() -> Iterator[FormData]:
    package = Path(os.environ["DOCCHECK_TRIAL_PACKAGE"]).resolve(strict=True)
    originals = (package / "inputs").resolve(strict=True)
    manifest = json.loads((package / "inputs.json").read_text(encoding="utf-8"))
    entries = manifest["files"]
    if manifest.get("synthetic") is not True or not 2 <= len(entries) <= 24:
        raise ValueError("Expected a prepared synthetic package")
    form = []
    total = 0
    with ExitStack() as stack:
        for entry in entries:
            path = (package / entry["file"]).resolve(strict=True)
            if not path.is_relative_to(originals) or path.suffix not in _FORMATS:
                raise ValueError("The fixture is outside its inputs directory")
            size = path.stat().st_size
            total += size
            if not 0 < size <= MAX_FILE_SIZE or total > MAX_PACKAGE_SIZE:
                raise ValueError("The fixture exceeds the upload limit")
            stream = stack.enter_context(path.open("rb"))
            if hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]:
                raise ValueError("The prepared synthetic file changed")
            stream.seek(0)
            role = {"report": "report", "supporting": "documents"}[entry["role"]]
            file = UploadFile(
                stream,
                filename=path.name,
                size=size,
                headers=Headers({"content-type": "application/octet-stream"}),
            )
            form.append((role, file))
        yield FormData(form)


@app.middleware("http")
async def restrict_routes(request: Request, call_next):
    path = request.url.path
    allowed = (
        request.method == "GET" and (path == "/health" or path.startswith("/api/v0/runs/"))
    ) or (request.method == "POST" and path == "/api/v0/trial")
    if not allowed:
        return JSONResponse({"code": "not_found"}, status_code=404)
    response = await call_next(request)
    if path == "/health" and response.status_code == 200:
        return JSONResponse({"status": "ok", "public_trial": True})
    return response


@app.post("/api/v0/trial", status_code=202)
def start_trial(request: Request) -> JSONResponse:
    """Use one shared job per two-minute window; the client sends no files."""
    if request.headers.get("content-length") not in (None, "0") or request.headers.get(
        "transfer-encoding"
    ):
        return JSONResponse({"code": "trial_requires_empty_request"}, status_code=400)
    bucket = int(time.time()) // _BUCKET_SECONDS
    key = uuid5(NAMESPACE_URL, f"doccheck-synthetic-trial:{bucket}")
    try:
        with Session(request.app.state.engine) as session:
            active = session.scalar(
                select(Run.id)
                .where(Run.status.in_(("queued", "processing")))
                .order_by(Run.created_at)
                .limit(1)
            )
            if active is not None:
                return JSONResponse({"run_id": str(active), "status": "queued"}, status_code=202)
            if session.scalar(select(func.count()).select_from(Run)) >= 200:
                completed = session.scalar(
                    select(Run.id)
                    .where(Run.status.in_(("completed", "completed_with_issues")))
                    .order_by(Run.created_at.desc())
                    .limit(1)
                )
                if completed is not None:
                    return JSONResponse(
                        {"run_id": str(completed), "status": "queued"}, status_code=202
                    )
                return JSONResponse({"code": "trial_unavailable"}, status_code=503)
        with _package() as form:
            run_id = store_run(request.app.state.engine, request.app.state.upload_root, key, form)
    except (OSError, KeyError, ValueError, SQLAlchemyError, UploadError):
        return JSONResponse({"code": "trial_unavailable"}, status_code=503)
    return JSONResponse({"run_id": str(run_id), "status": "queued"}, status_code=202)

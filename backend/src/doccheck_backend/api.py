from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Message

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.jobs import create_job, get_job
from doccheck_backend.models import SyntheticJob
from doccheck_backend.schemas import HealthResponse, JobResponse
from doccheck_backend.uploads import (
    MAX_DOCUMENTS,
    MAX_MULTIPART_SIZE,
    UploadError,
    size_error,
    store_run,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings or Settings.from_env()
        application.state.upload_root = configured.upload_root
        application.state.engine = create_database_engine(configured.database_url)
        try:
            yield
        finally:
            application.state.engine.dispose()

    application = FastAPI(
        title="DocCheck synthetic scaffold",
        version="0.1.0",
        description="Synthetic lifecycle only. No OCR or financial reconciliation.",
        lifespan=lifespan,
    )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Do not put a DSN, SQL parameters or raw driver error in an HTTP response.
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @application.post("/api/v0/runs", status_code=202)
    async def post_run(request: Request) -> JSONResponse:
        try:
            media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
            if media_type != "multipart/form-data":
                raise UploadError(415, "unsupported_media_type", "Ожидается multipart/form-data")
            key = request.headers.get("idempotency-key")
            if not key:
                raise UploadError(400, "invalid_request", "Требуется Idempotency-Key")
            try:
                parsed_key = UUID(key)
            except ValueError:
                raise UploadError(422, "invalid_input", "Некорректный Idempotency-Key") from None

            received = 0

            async def bounded_receive() -> Message:
                nonlocal received
                message = await request.receive()
                received += len(message.get("body", b""))
                if received > MAX_MULTIPART_SIZE:
                    raise size_error()
                return message

            bounded_request = Request(request.scope, receive=bounded_receive)
            async with bounded_request.form(max_files=MAX_DOCUMENTS + 1, max_fields=8) as form:
                run_id = await run_in_threadpool(
                    store_run,
                    request.app.state.engine,
                    request.app.state.upload_root,
                    parsed_key,
                    form,
                )
        except StarletteHTTPException as exc:
            if exc.detail.startswith(("Too many files.", "Too many fields.")):
                return JSONResponse(
                    status_code=422,
                    content={"code": "invalid_input", "message": "Слишком много частей формы"},
                )
            return JSONResponse(
                status_code=400,
                content={"code": "invalid_request", "message": "Некорректная multipart-форма"},
            )
        except UploadError as exc:
            content = {"code": exc.code, "message": str(exc)}
            if exc.field is not None:
                content["field"] = exc.field
            return JSONResponse(status_code=exc.status, content=content)
        except (OSError, SQLAlchemyError):
            return JSONResponse(
                status_code=503,
                content={"code": "service_unavailable", "message": "Хранилище недоступно"},
            )

        return JSONResponse(
            status_code=202,
            content={"run_id": str(run_id), "status": "queued"},
            headers={"Location": f"/api/v0/runs/{run_id}"},
        )

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        with request.app.state.engine.connect() as connection:
            # Also verifies migration readiness, without reading document data.
            connection.execute(select(SyntheticJob.id).limit(1))
        return HealthResponse()

    @application.post("/api/synthetic-jobs", response_model=JobResponse, status_code=201)
    def post_job(request: Request) -> JobResponse:
        return create_job(request.app.state.engine)

    @application.get("/api/synthetic-jobs/{job_id}", response_model=JobResponse)
    def read_job(job_id: UUID, request: Request) -> JobResponse:
        job = get_job(request.app.state.engine, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    return application


app = create_app()

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Annotated, BinaryIO
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.types import Receive, Scope, Send

from doccheck_backend import run_reads
from doccheck_backend.config import Settings
from doccheck_backend.contracts import CheckResult
from doccheck_backend.contracts.result import Evidence
from doccheck_backend.database import create_database_engine
from doccheck_backend.fragment_preview import FragmentPreview
from doccheck_backend.jobs import create_job, get_job
from doccheck_backend.models import SyntheticJob
from doccheck_backend.result_summary import build_rub_coverage
from doccheck_backend.run_xlsx import XLSX_MEDIA_TYPE, XlsxReportLimitError, export_check_result
from doccheck_backend.schemas import HealthResponse, JobResponse
from doccheck_backend.uploads import (
    MAX_DOCUMENTS,
    MAX_MULTIPART_SIZE,
    UploadError,
    size_error,
    store_run,
)


class _RunMultipartParser(MultiPartParser):
    complete = False

    def on_end(self) -> None:
        # The underlying parser can return finished parts without a closing boundary.
        self.complete = True


class _OriginalFileResponse(StreamingResponse):
    def __init__(self, stream: BinaryIO, size: int, name: str) -> None:
        self._stream = stream
        encoded = quote(name, safe="")
        disposition = (
            f'attachment; filename="{name}"'
            if name == encoded
            else f"attachment; filename*=utf-8''{encoded}"
        )
        super().__init__(
            iter(lambda: stream.read(64 * 1024), b""),
            media_type="application/octet-stream",
            headers={"Content-Disposition": disposition, "Content-Length": str(size)},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._stream.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings or Settings.from_env()
        application.state.upload_root = configured.upload_root
        application.state.public_demo = configured.public_demo
        application.state.engine = create_database_engine(configured.database_url)
        try:
            yield
        finally:
            application.state.engine.dispose()

    application = FastAPI(
        title="DocCheck",
        version="0.1.0",
        description="Saved document runs and the standalone synthetic lifecycle.",
        lifespan=lifespan,
    )

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        # Do not put a DSN, SQL parameters or raw driver error in an HTTP response.
        if request.scope["path"].startswith("/api/v0/runs"):
            return await run_read_error(request, run_reads.unavailable())
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @application.exception_handler(run_reads.RunReadError)
    async def run_read_error(request: Request, exc: run_reads.RunReadError) -> JSONResponse:
        content = {"code": exc.code, "message": str(exc)}
        if exc.field is not None:
            content["field"] = exc.field
        return JSONResponse(status_code=exc.status, content=content)

    @application.exception_handler(RequestValidationError)
    async def request_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        path = request.scope["path"]
        if (
            request.method == "GET"
            and path.startswith("/api/v0/runs")
            and (path == "/api/v0/runs" or path.endswith(("/fragments", "/fragment-preview")))
        ):
            field = str(exc.errors()[0]["loc"][-1])
            return await run_read_error(
                request,
                run_reads.RunReadError(422, "invalid_input", "Некорректный параметр", field),
            )
        return await request_validation_exception_handler(request, exc)

    def require_document_runs(request: Request) -> None:
        if request.app.state.public_demo:
            raise run_reads.RunReadError(
                503, "service_unavailable", "Операции с документами доступны в локальной установке"
            )

    document_runs = APIRouter(prefix="/api/v0/runs", dependencies=[Depends(require_document_runs)])

    @document_runs.post("", status_code=202)
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

            async def bounded_stream() -> AsyncGenerator[bytes, None]:
                received = 0
                async with aclosing(request.stream()) as stream:
                    async for chunk in stream:
                        received += len(chunk)
                        if received > MAX_MULTIPART_SIZE:
                            raise size_error()
                        yield chunk
                if not parser.complete:
                    # Fail inside parsing so Starlette closes any unfinished uploads.
                    raise MultiPartException("Missing closing boundary in multipart.")

            async with aclosing(bounded_stream()) as stream:
                parser = _RunMultipartParser(
                    request.headers, stream, max_files=MAX_DOCUMENTS + 1, max_fields=8
                )
                form = await parser.parse()
            try:
                run_id = await run_in_threadpool(
                    store_run,
                    request.app.state.engine,
                    request.app.state.upload_root,
                    parsed_key,
                    form,
                )
            finally:
                await form.close()
        except MultiPartException as exc:
            if exc.message.startswith(("Too many files.", "Too many fields.")):
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

    @document_runs.get("", response_model_exclude_unset=True)
    def list_runs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: str | None = None,
        finding: run_reads.FindingFilter | None = None,
    ) -> run_reads.RunPage:
        return run_reads.list_runs(request.app.state.engine, limit, cursor, finding)

    @document_runs.get("/{run_id}")
    def get_run(request: Request, run_id: str) -> run_reads.RunState:
        return run_reads.get_run_state(request.app.state.engine, run_id)

    @document_runs.get("/{run_id}/findings")
    def get_findings(request: Request, run_id: str) -> CheckResult:
        result = run_reads.get_run_findings(request.app.state.engine, run_id)
        result.summary.rub_coverage = build_rub_coverage(result)
        return result

    @document_runs.get(
        "/{run_id}/exports/xlsx",
        response_class=Response,
        responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}},
    )
    def export_run(request: Request, run_id: str) -> Response:
        result = run_reads.get_run_findings(request.app.state.engine, run_id)
        try:
            payload = export_check_result(result)
        except XlsxReportLimitError:
            raise run_reads.RunReadError(
                503, "service_unavailable", "Результат превышает пределы формата XLSX"
            ) from None
        filename = f"doccheck-{UUID(result.run_id)}.xlsx"
        return Response(
            payload,
            media_type=XLSX_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @document_runs.get(
        "/{run_id}/documents/{document_id}",
        response_class=StreamingResponse,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def get_document(request: Request, run_id: str, document_id: str) -> StreamingResponse:
        stream, size, name = run_reads.get_run_document(
            request.app.state.engine, request.app.state.upload_root, run_id, document_id
        )
        return _OriginalFileResponse(stream, size, name)

    @document_runs.get("/{run_id}/documents/{document_id}/fragments/{evidence_id}")
    def get_fragment(request: Request, run_id: str, document_id: str, evidence_id: str) -> Evidence:
        return run_reads.get_run_fragment(
            request.app.state.engine,
            request.app.state.upload_root,
            run_id,
            document_id,
            evidence_id,
            path_segment=True,
        )

    @document_runs.get("/{run_id}/documents/{document_id}/fragments")
    def get_fragment_by_id(
        request: Request,
        run_id: str,
        document_id: str,
        evidence_id: Annotated[str, Query(min_length=1)],
    ) -> Evidence:
        return run_reads.get_run_fragment(
            request.app.state.engine,
            request.app.state.upload_root,
            run_id,
            document_id,
            evidence_id,
        )

    @document_runs.get("/{run_id}/documents/{document_id}/fragment-preview")
    def get_fragment_preview(
        request: Request,
        response: Response,
        run_id: str,
        document_id: str,
        evidence_id: Annotated[str, Query(min_length=1)],
    ) -> FragmentPreview:
        response.headers["Cache-Control"] = "no-store"
        return run_reads.get_run_fragment_preview(
            request.app.state.engine,
            request.app.state.upload_root,
            run_id,
            document_id,
            evidence_id,
        )

    application.include_router(document_runs)

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

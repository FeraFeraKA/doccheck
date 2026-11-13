from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.jobs import create_job, get_job
from doccheck_backend.models import SyntheticJob
from doccheck_backend.schemas import HealthResponse, JobResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured = settings or Settings.from_env()
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

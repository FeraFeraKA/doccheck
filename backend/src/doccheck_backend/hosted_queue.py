"""Isolated synthetic work queue, accessed by an authenticated local worker."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from doccheck_backend import run_reads
from doccheck_backend.contracts import CheckJob
from doccheck_backend.contracts.result import Issue
from doccheck_backend.models import HostedClaim, Run
from doccheck_backend.run_worker import RunIdentity, StoredRun

router = APIRouter(prefix="/api/worker/v1")
_LEASE_DURATION = timedelta(seconds=60)
_RUN_DEADLINE = timedelta(minutes=15)
_RESULT_LIMIT = 1024**2
_TERMINAL = {"completed", "completed_with_issues", "failed"}


class Lease(BaseModel):
    lease_id: UUID
    run_id: UUID
    attempt: int
    expires_at: datetime
    scope: dict | None
    documents: list[dict]


def _authenticate(request: Request) -> None:
    expected = request.app.state.hosted_worker_digest
    if expected is None or not request.app.state.public_demo:
        raise HTTPException(404, "Worker queue unavailable")
    scheme, _, secret = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not 32 <= len(secret) <= 256 or not secret.isascii():
        raise HTTPException(401, "Invalid worker credentials")
    supplied = hashlib.sha256(secret.encode("ascii")).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(401, "Invalid worker credentials")


Auth = Annotated[None, Depends(_authenticate)]


def _clock(session: Session) -> datetime:
    return session.scalar(select(func.clock_timestamp()))


def _lease_rows(session: Session, lease_id: UUID) -> tuple[HostedClaim, Run]:
    row = session.execute(
        select(HostedClaim, Run)
        .join(Run, HostedClaim.run_id == Run.id)
        .where(HostedClaim.lease_id == lease_id)
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "Worker lease not found")
    claim, run = row
    return claim, run


def _require_current(claim: HostedClaim, run: Run, now: datetime) -> None:
    if (
        run.status != "processing"
        or claim.expires_at is None
        or claim.deadline_at is None
        or now >= min(claim.expires_at, claim.deadline_at)
    ):
        raise HTTPException(409, "Worker lease expired")


def expire_terminal_runs(session: Session, *, viewer: UUID | None = None) -> None:
    """Persist terminal expiration even when a worker never returns."""
    now = _clock(session)
    expired = (
        select(HostedClaim, Run)
        .join(Run, HostedClaim.run_id == Run.id)
        .where(
            Run.status == "processing",
            (HostedClaim.deadline_at <= now)
            | ((HostedClaim.attempt >= 3) & (HostedClaim.expires_at <= now)),
        )
        .with_for_update(skip_locked=True)
    )
    if viewer is not None:
        expired = expired.where(HostedClaim.viewer_id == viewer)
    for _, run in session.execute(expired):
        run.status = "failed"
        run.finished_at = now
        run.error = Issue(
            code="worker_interrupted", message="Истекло время обработки пакета."
        ).model_dump(mode="json")


def _noncache() -> dict[str, str]:
    return {"Cache-Control": "no-store"}


@router.post("/claims", response_model=Lease)
def claim_run(request: Request, response: Response, _auth: Auth) -> Lease | Response:
    with Session(request.app.state.engine) as session, session.begin():
        expire_terminal_runs(session)
        now = _clock(session)
        candidates = session.execute(
            select(HostedClaim, Run)
            .join(Run, HostedClaim.run_id == Run.id)
            .where(
                (Run.status == "queued")
                | ((Run.status == "processing") & (HostedClaim.expires_at <= now))
            )
            .order_by(Run.created_at, Run.id)
            .with_for_update(skip_locked=True)
            .limit(16)
        ).all()
        for attempt, run in candidates:
            if attempt.attempt >= 3 or (attempt.deadline_at and attempt.deadline_at <= now):
                run.status = "failed"
                run.finished_at = now
                run.error = Issue(
                    code="worker_interrupted",
                    message="Истекло время обработки пакета.",
                ).model_dump(mode="json")
                continue
            attempt.attempt += 1
            attempt.lease_id = uuid4()
            if attempt.deadline_at is None:
                attempt.deadline_at = now + _RUN_DEADLINE
            attempt.expires_at = min(now + _LEASE_DURATION, attempt.deadline_at)
            run.status = "processing"
            if run.started_at is None:
                run.started_at = now
            response.headers.update(_noncache())
            return Lease(
                lease_id=attempt.lease_id,
                run_id=run.id,
                attempt=attempt.attempt,
                expires_at=attempt.expires_at,
                scope=run.scope or None,
                documents=run.documents,
            )
    return Response(status_code=204, headers=_noncache())


@router.get("/claims/{lease_id}/files/{file_id}")
def get_file(request: Request, lease_id: UUID, file_id: str, _auth: Auth) -> Response:
    with Session(request.app.state.engine) as session, session.begin():
        attempt, run = _lease_rows(session, lease_id)
        _require_current(attempt, run, _clock(session))
        document = run_reads._stored_document(run, file_id)
        run_id = run.id
    stream, size = run_reads.open_run_original(
        request.app.state.upload_root, run_id, file_id, document
    )

    def chunks():
        with stream:
            yield from iter(lambda: stream.read(64 * 1024), b"")

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={**_noncache(), "Content-Length": str(size)},
    )


@router.post("/claims/{lease_id}/heartbeat", status_code=204)
def heartbeat(request: Request, lease_id: UUID, _auth: Auth) -> Response:
    with Session(request.app.state.engine) as session, session.begin():
        attempt, run = _lease_rows(session, lease_id)
        now = _clock(session)
        _require_current(attempt, run, now)
        attempt.expires_at = min(now + _LEASE_DURATION, attempt.deadline_at)
    return Response(status_code=204, headers=_noncache())


def _validate_completion(run: Run, data: CheckJob) -> dict:
    identity = RunIdentity.from_run(StoredRun(run.id, run.scope or None, run.documents))
    if data.result is not None:
        if any(doc.format != identity.formats.get(doc.id) for doc in data.result.documents):
            raise ValueError("Result does not match original file manifest")
    return identity.validate(data, synthetic=True).model_dump(mode="json")


def _complete(request: Request, lease_id: UUID, result: CheckJob) -> Response:
    with Session(request.app.state.engine) as session, session.begin():
        claim, run = _lease_rows(session, lease_id)
        try:
            result_payload = _validate_completion(run, result)
        except ValueError:
            raise HTTPException(422, "Invalid worker result") from None
        receipt = hashlib.sha256(
            json.dumps(result_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if run.status in _TERMINAL and claim.receipt == receipt:
            return Response(status_code=204, headers=_noncache())
        now = _clock(session)
        _require_current(claim, run, now)
        run.status = result.status
        run.result = result_payload["result"]
        run.error = result_payload["error"]
        run.finished_at = now
        claim.receipt = receipt
        claim.expires_at = None
    return Response(status_code=204, headers=_noncache())


@router.put("/claims/{lease_id}/result", status_code=204)
async def complete(request: Request, lease_id: UUID, _auth: Auth) -> Response:
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > _RESULT_LIMIT:
            raise HTTPException(413, "Worker result too large")
        payload.extend(chunk)
    try:
        result = CheckJob.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(422, "Invalid worker result") from None
    return await run_in_threadpool(_complete, request, lease_id, result)

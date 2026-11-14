"""Restricted browser reads for already admitted synthetic runs."""

import hashlib
import hmac
import time
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from doccheck_backend import run_reads
from doccheck_backend.contracts import CheckResult
from doccheck_backend.contracts.result import Evidence
from doccheck_backend.fragment_preview import FragmentPreview
from doccheck_backend.hosted_queue import expire_terminal_runs
from doccheck_backend.models import HostedClaim, Run
from doccheck_backend.run_xlsx import XLSX_MEDIA_TYPE, XlsxReportLimitError, export_check_result

router = APIRouter(prefix="/api/preview/v1")
_COOKIE = "__Host-doccheck-preview"
_SESSION_MAX_AGE = 3600


class Invite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=256)


def _viewer_config(request: Request) -> tuple[dict[UUID, str], bytes]:
    state = request.app.state
    if not state.public_demo or not state.hosted_viewers or state.hosted_session_key is None:
        raise HTTPException(404, "Preview unavailable")
    return state.hosted_viewers, state.hosted_session_key


def _signature(key: bytes, session: str) -> str:
    return hmac.new(key, session.encode("ascii"), hashlib.sha256).hexdigest()


def _viewer(request: Request) -> UUID:
    viewers, key = _viewer_config(request)
    try:
        encoded = request.cookies.get(_COOKIE, "")
        if len(encoded) > 120 or not encoded.isascii():
            raise ValueError
        viewer, expires, signature = encoded.split(".")
        identity = UUID(hex=viewer)
        epoch = int(expires)
        if not time.time() < epoch <= time.time() + _SESSION_MAX_AGE:
            raise ValueError
        if identity not in viewers or not hmac.compare_digest(
            signature, _signature(key, f"{viewer}.{expires}.{viewers[identity]}")
        ):
            raise ValueError
        return identity
    except ValueError:
        raise HTTPException(401, "Preview session required") from None


Viewer = Annotated[UUID, Depends(_viewer)]


@router.post("/session", status_code=204)
async def open_session(request: Request) -> Response:
    viewers, key = _viewer_config(request)
    if request.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "Preview session needs JSON")
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > 512:
            raise HTTPException(413, "Preview request too large")
        payload.extend(chunk)
    try:
        token = Invite.model_validate_json(payload).token
        if not token.isascii():
            raise ValueError
    except ValueError:
        raise HTTPException(401, "Invalid preview invitation") from None
    digest = hashlib.sha256(token.encode("ascii")).hexdigest()
    viewer = next(
        (user for user, expected in viewers.items() if hmac.compare_digest(digest, expected)), None
    )
    if viewer is None:
        raise HTTPException(401, "Invalid preview invitation")
    encoded = f"{viewer.hex}.{int(time.time()) + _SESSION_MAX_AGE}"
    signature = _signature(key, f"{encoded}.{viewers[viewer]}")
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        _COOKIE,
        f"{encoded}.{signature}",
        max_age=_SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )
    return response


def _owned(request: Request, viewer: UUID, run_id: UUID) -> None:
    with Session(request.app.state.engine) as session, session.begin():
        found = session.scalar(
            select(HostedClaim.run_id).where(
                HostedClaim.run_id == run_id, HostedClaim.viewer_id == viewer
            )
        )
        if found is not None:
            expire_terminal_runs(session, viewer=viewer)
    if found is None:
        raise HTTPException(404, "Preview run not found")


@router.get("/runs", response_model=list[run_reads.RunSummary])
def runs(request: Request, response: Response, viewer: Viewer) -> list[run_reads.RunSummary]:
    with Session(request.app.state.engine) as session, session.begin():
        expire_terminal_runs(session, viewer=viewer)
        items = session.execute(
            select(Run.id, Run.status, Run.created_at, Run.error)
            .join(HostedClaim, HostedClaim.run_id == Run.id)
            .where(HostedClaim.viewer_id == viewer)
            .order_by(Run.created_at.desc(), Run.id.desc())
            .limit(20)
        )
        response.headers["Cache-Control"] = "no-store"
        return [
            run_reads.RunSummary(run_id=run_id, status=status, created_at=created, error=error)
            for run_id, status, created, error in items
        ]


@router.get("/runs/{run_id}")
def run_state(
    request: Request, response: Response, run_id: UUID, viewer: Viewer
) -> run_reads.RunState:
    _owned(request, viewer, run_id)
    response.headers["Cache-Control"] = "no-store"
    return run_reads.get_run_state(request.app.state.engine, str(run_id))


@router.get("/runs/{run_id}/findings")
def findings(request: Request, response: Response, run_id: UUID, viewer: Viewer) -> CheckResult:
    _owned(request, viewer, run_id)
    response.headers["Cache-Control"] = "no-store"
    return run_reads.get_run_findings(request.app.state.engine, str(run_id))


@router.get("/runs/{run_id}/documents/{document_id}")
def original(request: Request, run_id: UUID, document_id: str, viewer: Viewer) -> StreamingResponse:
    _owned(request, viewer, run_id)
    stream, size, name = run_reads.get_run_document(
        request.app.state.engine, request.app.state.upload_root, str(run_id), document_id
    )

    def chunks():
        with stream:
            yield from iter(lambda: stream.read(64 * 1024), b"")

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "Content-Length": str(size),
            "Content-Disposition": f"attachment; filename*=utf-8''{quote(name, safe='')}",
        },
    )


@router.get("/runs/{run_id}/exports/xlsx")
def export_run(request: Request, run_id: UUID, viewer: Viewer) -> Response:
    _owned(request, viewer, run_id)
    result = run_reads.get_run_findings(request.app.state.engine, str(run_id))
    try:
        payload = export_check_result(result)
    except XlsxReportLimitError:
        raise HTTPException(503, "Preview export exceeds XLSX limits") from None
    return Response(
        payload,
        media_type=XLSX_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="doccheck-{run_id}.xlsx"',
        },
    )


@router.get("/runs/{run_id}/documents/{document_id}/fragments")
def evidence(
    request: Request,
    response: Response,
    run_id: UUID,
    document_id: str,
    evidence_id: str,
    viewer: Viewer,
) -> Evidence:
    _owned(request, viewer, run_id)
    response.headers["Cache-Control"] = "no-store"
    return run_reads.get_run_fragment(
        request.app.state.engine,
        request.app.state.upload_root,
        str(run_id),
        document_id,
        evidence_id,
    )


@router.get("/runs/{run_id}/documents/{document_id}/fragment-preview")
def fragment_preview(
    request: Request,
    response: Response,
    run_id: UUID,
    document_id: str,
    evidence_id: str,
    viewer: Viewer,
) -> FragmentPreview:
    _owned(request, viewer, run_id)
    response.headers["Cache-Control"] = "no-store"
    return run_reads.get_run_fragment_preview(
        request.app.state.engine,
        request.app.state.upload_root,
        str(run_id),
        document_id,
        evidence_id,
    )

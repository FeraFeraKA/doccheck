"""Version 0.1.0 synthetic lifecycle only, exposed through this app's OpenAPI."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"


class SyntheticResult(BaseModel):
    synthetic: Literal[True] = True
    message: str


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    synthetic: Literal[True]
    status: Literal["queued", "processing", "completed", "failed"]
    result: SyntheticResult | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

"""Configuration shared by the API, migration command and separate worker."""

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


@dataclass(frozen=True)
class Settings:
    database_url: str
    worker_poll_seconds: float = 0.5
    synthetic_delay_seconds: float = 2.0
    upload_root: Path = Path("../data/runs")
    public_demo: bool = False
    hosted_worker_digest: str | None = None
    hosted_viewers: dict[UUID, str] | None = None
    hosted_session_key: bytes | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        # The shared repository .env is optional; process environment takes precedence.
        load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            raise ValueError("DATABASE_URL is required; see backend/README.md")
        try:
            url = make_url(database_url)
        except (ArgumentError, ValueError):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        public_demo = os.environ.get("DOCCHECK_PUBLIC_DEMO", "0")
        if public_demo not in {"0", "1"}:
            raise ValueError("DOCCHECK_PUBLIC_DEMO must be 0 or 1")
        worker_digest = _hosted_worker_digest()
        viewers, session_key = _hosted_viewer_settings(worker_digest)
        return cls(
            database_url=database_url,
            worker_poll_seconds=_seconds("WORKER_POLL_SECONDS", 0.5, 0.05, 60),
            synthetic_delay_seconds=_seconds("SYNTHETIC_DELAY_SECONDS", 2.0, 0, 60),
            upload_root=Path(
                os.environ.get(
                    "DOCCHECK_UPLOAD_ROOT",
                    str(Path(__file__).resolve().parents[3] / "data" / "runs"),
                )
            ),
            public_demo=public_demo == "1",
            hosted_worker_digest=worker_digest,
            hosted_viewers=viewers,
            hosted_session_key=session_key,
        )


def _hosted_worker_digest() -> str | None:
    value = os.environ.get("DOCCHECK_HOSTED_WORKER_SHA256")
    if value is not None and not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("DOCCHECK_HOSTED_WORKER_SHA256 must be a SHA-256 hex digest")
    return value


def _hosted_viewer_settings(
    worker_digest: str | None,
) -> tuple[dict[UUID, str] | None, bytes | None]:
    raw_viewers = os.environ.get("DOCCHECK_HOSTED_VIEWERS")
    raw_key = os.environ.get("DOCCHECK_HOSTED_SESSION_KEY")
    if raw_viewers is None and raw_key is None:
        return None, None
    try:
        if worker_digest is None or raw_viewers is None or raw_key is None:
            raise ValueError
        if not re.fullmatch(r"[a-f0-9]{64}", raw_key):
            raise ValueError
        configured = json.loads(raw_viewers)
        if not isinstance(configured, dict) or not 0 < len(configured) <= 40:
            raise ValueError
        viewers = {UUID(key): digest for key, digest in configured.items()}
        if len(viewers) != len(configured) or len(set(viewers.values())) != len(viewers):
            raise ValueError
        if any(
            not isinstance(value, str)
            or not re.fullmatch(r"[a-f0-9]{64}", value)
            or value == worker_digest
            for value in viewers.values()
        ):
            raise ValueError
        return viewers, bytes.fromhex(raw_key)
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid hosted viewer configuration") from None


def _seconds(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value

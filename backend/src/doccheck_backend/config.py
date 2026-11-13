"""Configuration shared by the API, migration command and separate worker."""

import math
import os
from dataclasses import dataclass
from pathlib import Path

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
        )


def _seconds(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value

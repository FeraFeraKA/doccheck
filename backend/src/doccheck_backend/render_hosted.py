"""Start the restricted Preview API. The document worker runs on another PC."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from doccheck_backend.config import Settings
from doccheck_backend.hosted_seed import seed
from doccheck_backend.render_demo import _environment

_MANIFEST = Path(__file__).with_name("hosted_demo_inputs") / "manifest.json"
_MANIFEST_SHA256 = "bb0d7e4d6a4ceae77f21cb0eb3676cee8c7958a4f14ce9d6c511f0fc7cc812ab"


def main() -> int:
    try:
        env = _environment()
        os.environ["DATABASE_URL"] = env["DATABASE_URL"]
        settings = Settings.from_env()
        if settings.hosted_worker_digest is None or settings.hosted_viewers is None:
            raise ValueError("Render Preview requires explicit worker and viewer settings")
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    try:
        with open(os.devnull, "wb") as output:
            subprocess.run(["alembic", "upgrade", "head"], check=True, stdout=output, stderr=output)
    except subprocess.CalledProcessError:
        print("Render Preview migrations failed", file=sys.stderr)
        return 1
    try:
        seed_demo(settings)
    except Exception:
        print("Render Preview could not prepare synthetic packages", file=sys.stderr)
        return 1
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "doccheck_backend.api:app",
            "--host",
            "0.0.0.0",
            "--port",
            env.get("PORT", "10000"),
            "--no-access-log",
        ],
    )
    return 1


def seed_demo(settings: Settings) -> None:
    """Admit or restore only the package pinned in the built artifact."""
    for viewer in settings.hosted_viewers or {}:
        key = uuid5(NAMESPACE_URL, f"doccheck-preview:demo-001:{viewer}")
        seed(settings, _MANIFEST, _MANIFEST_SHA256, key, viewer=viewer, restore_originals=True)


if __name__ == "__main__":
    raise SystemExit(main())

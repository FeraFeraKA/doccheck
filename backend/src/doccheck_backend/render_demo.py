"""Start the synthetic web demo and its separate worker after migrating Postgres."""

import os
import signal
import subprocess
import sys
import time
from contextlib import ExitStack

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def _environment() -> dict[str, str]:
    if os.environ.get("DOCCHECK_PUBLIC_DEMO") != "1":
        raise ValueError("Render demo requires DOCCHECK_PUBLIC_DEMO=1")
    try:
        url = make_url(os.environ.get("DOCCHECK_RENDER_DATABASE_URL", ""))
    except ArgumentError:
        raise ValueError("Render demo requires its dedicated PostgreSQL URL") from None
    if url.drivername not in {"postgres", "postgresql"}:
        raise ValueError("Render demo requires a PostgreSQL URL from Render")
    return {
        **os.environ,
        "DATABASE_URL": url.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        ),
    }


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def main() -> int:
    try:
        env = _environment()
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        with open(os.devnull, "wb") as migration_output:
            subprocess.run(
                ["alembic", "upgrade", "head"],
                env=env,
                check=True,
                stdout=migration_output,
                stderr=migration_output,
            )
    except subprocess.CalledProcessError:
        print("Render demo migrations failed", file=sys.stderr)
        return 1

    def stop_on_signal(_signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_signal)
    try:
        with ExitStack() as processes:
            worker = subprocess.Popen([sys.executable, "-m", "doccheck_backend.worker"], env=env)
            processes.callback(_stop, worker)
            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "doccheck_backend.api:app",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    env.get("PORT", "10000"),
                ],
                env=env,
            )
            processes.callback(_stop, api)
            while worker.poll() is None and api.poll() is None:
                time.sleep(0.25)
            print("A Render demo subprocess exited", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Start the restricted Preview API. The document worker runs on another PC."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.hosted_seed import seed
from doccheck_backend.render_demo import _environment

_MANIFEST = Path(__file__).with_name("hosted_demo_inputs") / "manifest.json"
_MANIFEST_SHA256 = "bb0d7e4d6a4ceae77f21cb0eb3676cee8c7958a4f14ce9d6c511f0fc7cc812ab"
_PREVIEW_IDENTITY = "doccheck_hosted_preview"


def _preview_environment() -> dict[str, str]:
    shared = os.environ.get("DOCCHECK_HOSTED_SHARED_DATABASE_URL")
    public_app = os.environ.get("DOCCHECK_HOSTED_PUBLIC_DATABASE_USER")
    public_database = os.environ.get("DOCCHECK_HOSTED_PUBLIC_DATABASE_NAME")
    if shared is None:
        env = _environment()
        url = make_url(env["DATABASE_URL"])
        if (
            "DOCCHECK_HOSTED_PUBLIC_DATABASE_NAME" in env
            or "DOCCHECK_HOSTED_PUBLIC_DATABASE_USER" in env
            or not _expected_preview_url(url)
        ):
            raise ValueError("Render dedicated Preview requires its dedicated database and login")
        return env
    if (
        os.environ.get("DOCCHECK_PUBLIC_DEMO") != "1"
        or "DOCCHECK_RENDER_DATABASE_URL" in os.environ
    ):
        raise ValueError("Render shared Preview requires exclusive database settings")
    if (
        not public_database
        or public_database == _PREVIEW_IDENTITY
        or not public_app
        or public_app == _PREVIEW_IDENTITY
    ):
        raise ValueError("Render shared Preview requires the separate public database and app user")
    try:
        url = make_url(shared)
    except ArgumentError:
        raise ValueError("Invalid Render shared Preview database URL") from None
    if url.drivername not in {"postgres", "postgresql"} or not _expected_preview_url(url):
        raise ValueError("Render shared Preview requires its dedicated database and login")
    return {
        **os.environ,
        "DATABASE_URL": url.set(drivername="postgresql+psycopg").render_as_string(
            hide_password=False
        ),
    }


def _expected_preview_url(url: URL) -> bool:
    return bool(
        (url.database, url.username) == (_PREVIEW_IDENTITY, _PREVIEW_IDENTITY)
        and url.host
        and url.password
        and not url.query
    )


def _check_preview_database(
    database_url: str, public_database: str | None = None, public_app: str | None = None
) -> None:
    # Only read catalog metadata, even if a service identity is misconfigured.
    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            allowed = connection.execute(
                text("""
                    SELECT current_database() = :preview
                       AND current_user = :preview
                       AND session_user = :preview
                       AND NOT (role.rolsuper OR role.rolcreatedb OR role.rolcreaterole
                                OR role.rolreplication OR role.rolbypassrls)
                       AND database.datdba = role.oid
                       AND has_schema_privilege(current_user, 'public', 'USAGE')
                       AND has_schema_privilege(current_user, 'public', 'CREATE')
                       AND NOT EXISTS (
                           SELECT 1 FROM pg_auth_members WHERE member = role.oid
                       )
                       AND NOT EXISTS (
                           SELECT 1 FROM pg_database AS other
                           WHERE other.datdba = role.oid AND other.datname <> :preview
                       )
                       AND (
                           CAST(:public_database AS text) IS NULL OR EXISTS (
                               SELECT 1
                               FROM pg_database AS other
                               CROSS JOIN pg_roles AS public_role
                               WHERE other.datname = :public_database
                                 AND other.datdba <> role.oid
                                 AND public_role.rolname = :public_app
                                 AND NOT (
                                     public_role.rolsuper OR public_role.rolcreaterole
                                     OR public_role.rolcreatedb OR public_role.rolreplication
                                     OR public_role.rolbypassrls
                                 )
                                 AND NOT EXISTS (
                                     SELECT 1 FROM pg_auth_members
                                     WHERE member = public_role.oid
                                 )
                                 AND has_database_privilege(public_role.oid, other.oid, 'CONNECT')
                                 AND NOT has_database_privilege(role.oid, other.oid, 'CONNECT')
                                 AND NOT has_database_privilege(
                                     public_role.oid, database.oid, 'CONNECT'
                                 )
                           )
                       )
                    FROM pg_roles AS role
                    JOIN pg_database AS database ON database.datname = current_database()
                    WHERE role.rolname = current_user
                """),
                {
                    "preview": _PREVIEW_IDENTITY,
                    "public_database": public_database,
                    "public_app": public_app,
                },
            ).scalar_one()
    except SQLAlchemyError:
        raise ValueError("Render Preview database isolation could not be verified") from None
    finally:
        engine.dispose()
    if not allowed:
        raise ValueError("Render Preview database isolation could not be verified")


def main() -> int:
    try:
        env = _preview_environment()
        os.environ["DATABASE_URL"] = env["DATABASE_URL"]
        settings = Settings.from_env()
        if settings.hosted_worker_digest is None or settings.hosted_viewers is None:
            raise ValueError("Render Preview requires explicit worker and viewer settings")
        _check_preview_database(
            settings.database_url,
            env.get("DOCCHECK_HOSTED_PUBLIC_DATABASE_NAME"),
            env.get("DOCCHECK_HOSTED_PUBLIC_DATABASE_USER"),
        )
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
        key = uuid5(NAMESPACE_URL, f"doccheck-preview:{_MANIFEST_SHA256}:{viewer}")
        seed(settings, _MANIFEST, _MANIFEST_SHA256, key, viewer=viewer, restore_originals=True)


if __name__ == "__main__":
    raise SystemExit(main())

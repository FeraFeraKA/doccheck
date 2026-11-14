import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

from doccheck_backend.render_hosted import _check_shared_database, _preview_environment, main

_SHARED = "DOCCHECK_HOSTED_SHARED_DATABASE_URL"
_PUBLIC = "DOCCHECK_HOSTED_PUBLIC_DATABASE_NAME"
_IDENTITY = "doccheck_hosted_preview"


@pytest.mark.parametrize(
    ("url", "public"),
    [
        ("postgres://doccheck_hosted_preview:secret@localhost/public_demo", "public_demo"),
        ("postgres://administrator:secret@localhost/doccheck_hosted_preview", "public_demo"),
        ("postgres://doccheck_hosted_preview:secret@localhost/doccheck_hosted_preview", None),
        (
            "postgres://doccheck_hosted_preview:secret@localhost/doccheck_hosted_preview?options=-crole%3Dpostgres",
            "public_demo",
        ),
    ],
)
def test_shared_config_rejects_wrong_database_or_role_before_startup(monkeypatch, url, public):
    monkeypatch.setenv("DOCCHECK_PUBLIC_DEMO", "1")
    monkeypatch.setenv(_SHARED, url)
    monkeypatch.delenv("DOCCHECK_RENDER_DATABASE_URL", raising=False)
    monkeypatch.delenv(_PUBLIC, raising=False)
    if public is not None:
        monkeypatch.setenv(_PUBLIC, public)
    with pytest.raises(ValueError, match="shared Preview requires"):
        _preview_environment()


def test_shared_preflight_failure_stops_before_migration(monkeypatch, capsys):
    monkeypatch.setenv("DOCCHECK_PUBLIC_DEMO", "1")
    monkeypatch.delenv("DOCCHECK_RENDER_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        _SHARED, "postgres://doccheck_hosted_preview:secret@localhost/doccheck_hosted_preview"
    )
    monkeypatch.setenv(_PUBLIC, "public_demo")
    monkeypatch.setenv("DOCCHECK_HOSTED_WORKER_SHA256", "1" * 64)
    monkeypatch.setenv("DOCCHECK_HOSTED_VIEWERS", f'{{"{uuid4()}":"{"2" * 64}"}}')
    monkeypatch.setenv("DOCCHECK_HOSTED_SESSION_KEY", "3" * 64)

    def failed_preflight(*args):
        raise ValueError("Render shared Preview database identity could not be verified")

    monkeypatch.setattr("doccheck_backend.render_hosted._check_shared_database", failed_preflight)
    monkeypatch.setattr(
        "doccheck_backend.render_hosted.subprocess.run",
        lambda *args, **kwargs: pytest.fail("Unexpected migration"),
    )
    assert main() == 1
    assert "secret" not in capsys.readouterr().err


def test_shared_database_preflight_preserves_public_database():
    configured = os.environ.get("DOCCHECK_SHARED_DB_TEST_ADMIN_URL")
    if configured is None:
        pytest.skip("Requires an intentionally isolated PostgreSQL cluster administrator")
    url = make_url(configured)
    if url.host != "127.0.0.1" or url.port in (None, 5432, 15432):
        pytest.fail("Use a separate non-default local test instance")
    owner = sql.Identifier(_IDENTITY)
    public_name = f"public_demo_test_{uuid4().hex}"
    public = sql.Identifier(public_name)
    password = uuid4().hex
    with psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    ) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(owner, sql.Literal(password))
        )
        try:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(public))
            try:
                admin.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(owner, owner))
                try:
                    with psycopg.connect(
                        url.set(drivername="postgresql", database=public_name).render_as_string(
                            hide_password=False
                        )
                    ) as public_db:
                        public_db.execute("CREATE TABLE existing_demo (value text NOT NULL)")
                        public_db.execute("INSERT INTO existing_demo VALUES ('guard')")
                    dedicated = url.set(
                        drivername="postgresql+psycopg",
                        username=_IDENTITY,
                        password=password,
                        database=_IDENTITY,
                    ).render_as_string(hide_password=False)
                    _check_shared_database(dedicated, public_name)
                    with psycopg.connect(
                        url.set(
                            drivername="postgresql",
                            database=public_name,
                            username=_IDENTITY,
                            password=password,
                        ).render_as_string(hide_password=False)
                    ) as restricted:
                        with pytest.raises(psycopg.errors.InsufficientPrivilege):
                            restricted.execute("SELECT * FROM existing_demo").fetchall()
                    with pytest.raises(ValueError, match="could not be verified"):
                        _check_shared_database(dedicated, _IDENTITY)
                    wrong_db = make_url(dedicated).set(database=public_name)
                    with pytest.raises(ValueError, match="could not be verified"):
                        _check_shared_database(
                            wrong_db.render_as_string(hide_password=False), public_name
                        )
                    admin.execute(sql.SQL("ALTER ROLE {} CREATEDB").format(owner))
                    with pytest.raises(ValueError, match="could not be verified"):
                        _check_shared_database(dedicated, public_name)
                    with psycopg.connect(
                        url.set(drivername="postgresql", database=public_name).render_as_string(
                            hide_password=False
                        )
                    ) as public_db:
                        assert public_db.execute("SELECT value FROM existing_demo").fetchone() == (
                            "guard",
                        )
                finally:
                    admin.execute(sql.SQL("DROP DATABASE {}").format(owner))
            finally:
                admin.execute(sql.SQL("DROP DATABASE {}").format(public))
        finally:
            admin.execute(sql.SQL("DROP ROLE {}").format(owner))

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@pytest.fixture
def run_migrations():
    return upgrade_schema


def upgrade_schema(database_url: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=NO_WINDOW,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def database_url() -> Iterator[str]:
    """Only create/drop this test's random schema, never shared tables/databases."""
    configured = os.environ.get("DOCCHECK_TEST_DATABASE_URL")
    if not configured:
        pytest.skip("Set DOCCHECK_TEST_DATABASE_URL to run real PostgreSQL integration")
    base = make_url(configured)
    if base.get_backend_name() != "postgresql":
        pytest.fail("Integration tests require a real PostgreSQL database")
    schema = f"nrt8_test_{uuid4().hex}"
    admin_dsn = base.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = base.set(drivername="postgresql+psycopg").update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    try:
        url = isolated.render_as_string(hide_password=False)
        upgrade_schema(url)
        yield url
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

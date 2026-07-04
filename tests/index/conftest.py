"""Postgres gating for the ``tests/index/`` suite.

Design constraints (Task 4 brief):

- ``tests/domain`` and ``tests/persistence`` must keep running with NO Postgres. They use
  no ``db``/``django_db`` fixture, so pytest-django never creates a test database for them
  even though ``DJANGO_SETTINGS_MODULE`` is set project-wide (in ``pyproject.toml`` — it
  must be set before pytest-django's plugin configure runs ``django.setup()``, which a
  package-local conftest is too late for; ``django.setup()`` itself is DB-free).

- Index tests REQUIRE Postgres. If the DB is unreachable, the DB-touching tests FAIL (not
  skip) with a message naming the fix, so a missing container never masquerades as green.
  The probe (``_pg_guard``) is session-scoped and wired as the FIRST dependency of our
  ``django_db_setup`` override, so it runs before pytest-django creates the test database —
  a down container reports the actionable hint instead of a raw ``OperationalError`` deep
  inside test-database creation. (An autouse function-scoped guard would NOT work: session
  fixtures like ``django_db_setup`` are instantiated before any function-scoped fixture.)
  The pure architecture checks in this directory still run without Postgres.

- Escape hatch: ``BUNDESARCHIV_SKIP_PG=1`` skips this whole directory explicitly (for
  domain-only work without a running Postgres).
"""

import os
from pathlib import Path

import pytest

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

_UNREACHABLE_HINT = (
    "Index tests require a running Postgres on localhost:5434. Start it with:\n"
    "  container build -t bundesarchiv-postgres docker/postgres/\n"
    "  container run -d --name bundesarchiv-pg -p 5434:5432 "
    "-e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres\n"
    "or (Docker VPS path): docker compose up -d\n"
    "To skip the whole tests/index/ suite instead: BUNDESARCHIV_SKIP_PG=1"
)

_HERE = Path(__file__).parent


def _is_index_item(item: pytest.Item) -> bool:
    path = Path(str(item.fspath))
    return path == _HERE or _HERE in path.parents


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Honor BUNDESARCHIV_SKIP_PG=1: skip every test collected under this directory."""
    if os.environ.get("BUNDESARCHIV_SKIP_PG") != "1":
        return
    skip = pytest.mark.skip(reason="BUNDESARCHIV_SKIP_PG=1 (Postgres-backed index tests skipped)")
    for item in items:
        if _is_index_item(item):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def _pg_guard() -> None:
    """Fail (never skip) with an actionable hint when Postgres is unreachable.

    Probes with raw psycopg (independent of Django) once per session. Wired ahead of
    test-database creation via the ``django_db_setup`` override below.
    """
    import psycopg

    dsn = os.environ.get("BUNDESARCHIV_PG_DSN", _DEFAULT_PG_DSN)
    try:
        with psycopg.connect(dsn, connect_timeout=5):
            pass
    except psycopg.OperationalError as exc:
        pytest.fail(f"cannot reach Postgres: {exc}\n\n{_UNREACHABLE_HINT}", pytrace=False)


@pytest.fixture(scope="session")
def django_db_setup(_pg_guard: None, django_db_setup: None) -> None:
    """pytest-django's ``django_db_setup``, guarded by the reachability probe.

    Standard fixture-override pattern: the ``django_db_setup`` parameter resolves to the
    plugin's fixture. ``_pg_guard`` is listed first so it is instantiated first — every
    ``db``/``django_db`` test therefore hits the probe before test-DB creation can raise
    a raw connection error.
    """


@pytest.fixture
def pg_connection(_pg_guard: None, db: None) -> object:
    """A live Django default connection, on the created test DB. For connectivity tests."""
    from django.db import connection

    return connection

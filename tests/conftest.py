"""Shared Postgres gating for every DB-touching suite (``tests/index/``, ``tests/app/``).

Design constraints (Task 4 / 4.2 brief):

- ``tests/domain`` and ``tests/persistence`` must keep running with NO Postgres. They use no
  ``db``/``django_db`` fixture, so the session-scoped ``django_db_setup`` override below is never
  instantiated for them and pytest-django never creates a test database — even though
  ``DJANGO_SETTINGS_MODULE`` is set project-wide (it must be set before pytest-django's plugin
  configure runs ``django.setup()``, which is DB-free).

- DB-touching tests REQUIRE Postgres. If the DB is unreachable they FAIL (not skip) with an
  actionable hint, so a missing container never masquerades as green. The probe (``_pg_guard``) is
  session-scoped and wired as the FIRST dependency of the ``django_db_setup`` override, so it runs
  before pytest-django creates the test database — a down container reports the fix instead of a
  raw ``OperationalError`` deep inside test-database creation.

- Which tests need Postgres is DERIVED, never listed: ``pytest_collection_modifyitems`` marks every
  item whose (transitive) fixture closure pulls in a pytest-django database fixture with
  ``requires_pg``. Run without a container via ``uv run pytest -m "not requires_pg"``. A test that
  reaches Postgres out of band — a subprocess, say — is invisible to the derivation and carries the
  marker explicitly.

This lives at the repo-test root so BOTH the index adapter tests and the app-service tests inherit
the same guarded ``django_db_setup``.
"""

import os

import pytest

_DB_FIXTURES = frozenset({"db", "transactional_db", "django_db_reset_sequences", "live_server"})

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

_UNREACHABLE_HINT = (
    "DB-backed tests require a running Postgres on localhost:5434. Start it with:\n"
    "  container build -t bundesarchiv-postgres docker/postgres/\n"
    "  container run -d --name bundesarchiv-pg -p 5434:5432 "
    "-e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres\n"
    "or (Docker VPS path): docker compose up -d\n"
    "No container runtime (cloud sandbox)? bash scripts/dev-pg-cloud.sh (idempotent — also\n"
    "the fix when a sandbox reclaimed a previously running server mid-session).\n"
    "To run only the DB-free tests instead: mise run test:nodb"
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark every item that reaches the database through pytest-django with ``requires_pg``.

    ``fixturenames`` is the resolved closure, so a test using only a conftest fixture that itself
    depends on ``db`` is caught too. The ``django_db`` marker is checked separately: pytest-django
    grants DB access for it through a fixture it injects in its own (tryfirst) collection hook, so
    the closure this hook sees does not yet mention any database fixture.
    """
    for item in items:
        by_fixture = _DB_FIXTURES.intersection(getattr(item, "fixturenames", ()))
        if by_fixture or item.get_closest_marker("django_db") is not None:
            item.add_marker(pytest.mark.requires_pg)


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

    Standard fixture-override pattern: the ``django_db_setup`` parameter resolves to the plugin's
    fixture. ``_pg_guard`` is listed first so it is instantiated first — every ``db``/``django_db``
    test therefore hits the probe before test-DB creation can raise a raw connection error.
    """

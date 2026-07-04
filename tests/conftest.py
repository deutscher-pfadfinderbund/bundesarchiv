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

- Escape hatch: ``BUNDESARCHIV_SKIP_PG=1`` (honored per-directory by the ``tests/index`` and
  ``tests/app`` conftests, which own their own collection-skip scoping).

This lives at the repo-test root so BOTH the index adapter tests and the app-service tests inherit
the same guarded ``django_db_setup``; the pure architecture checks still run without Postgres.
"""

import os

import pytest

_DEFAULT_PG_DSN = "postgresql://postgres:postgres@localhost:5434/bundesarchiv"

_UNREACHABLE_HINT = (
    "DB-backed tests require a running Postgres on localhost:5434. Start it with:\n"
    "  container build -t bundesarchiv-postgres docker/postgres/\n"
    "  container run -d --name bundesarchiv-pg -p 5434:5432 "
    "-e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres\n"
    "or (Docker VPS path): docker compose up -d\n"
    "To skip the DB-backed suites instead: BUNDESARCHIV_SKIP_PG=1"
)


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

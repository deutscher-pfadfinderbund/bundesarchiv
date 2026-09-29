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
import re
from pathlib import Path
from typing import cast

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


_DESELECTED_PG = pytest.StashKey[int]()


def pytest_deselected(items: list[pytest.Item]) -> None:
    if items:
        stash = items[0].config.stash
        stash[_DESELECTED_PG] = stash.get(_DESELECTED_PG, 0) + sum(map(_runs_under_test_db, items))


def _runs_under_test_db(item: pytest.Item) -> bool:
    return item.get_closest_marker("requires_pg") is not None and not any(
        item.get_closest_marker(name) for name in ("e2e", "gallery")
    )


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    if count := config.stash.get(_DESELECTED_PG, 0):
        terminalreporter.write_line(
            f"{count} Postgres-backed tests not run: mise run test:db runs them"
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


def _checkout_suffix(checkout: Path) -> str:
    """The checkout's directory name as a Postgres identifier fragment; empty when nothing is left."""
    return re.sub(r"[^a-z0-9_]+", "_", checkout.name.lower()).strip("_")


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings: None) -> None:
    """One test database per checkout, so Postgres-backed runs in two worktrees never collide."""
    from django.db import connection

    suffix = _checkout_suffix(Path(__file__).resolve().parents[1])
    if suffix:
        db = connection.settings_dict
        # 63 bytes: Postgres truncates longer identifiers.
        db["TEST"]["NAME"] = f"test_{db['NAME']}_{suffix}"[:63]


@pytest.fixture(scope="session")
def django_db_setup(_pg_guard: None, django_db_setup: None) -> None:
    """pytest-django's ``django_db_setup``, guarded by the reachability probe.

    Standard fixture-override pattern: the ``django_db_setup`` parameter resolves to the plugin's
    fixture. ``_pg_guard`` is listed first so it is instantiated first — every ``db``/``django_db``
    test therefore hits the probe before test-DB creation can raise a raw connection error.
    """


class _MissingVariable(str):
    def __mod__(self, name: object) -> str:
        raise NameError(f"template variable missing: {name}")


def pytest_configure(config: pytest.Config) -> None:
    """Every suite renders templates strictly: a missing ``{{ var }}`` raises, naming it.

    Prod and dev keep Django's lenient empty string. A value that is optional by design says so
    with ``{% firstof var %}``; a ``|default`` filter does not escape this, ``{% if %}`` does.
    """
    from django.conf import settings

    options = cast("dict[str, object]", settings.TEMPLATES[0]["OPTIONS"])
    options["string_if_invalid"] = _MissingVariable("%s")

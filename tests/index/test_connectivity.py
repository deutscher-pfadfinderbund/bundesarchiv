"""Trivial DB connectivity smoke test against the running Postgres container.

Proves the pytest-django wiring reaches a real Postgres (not sqlite, not a mock) and that
the test database is usable. Real FTS / schema work lands in Tasks 5-8.
"""

import pytest


@pytest.mark.django_db
def test_default_connection_is_postgres_and_alive(pg_connection: object) -> None:
    from django.db import connection

    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)

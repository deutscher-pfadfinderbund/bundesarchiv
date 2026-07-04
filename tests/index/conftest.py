"""Postgres gating specific to the ``tests/index/`` suite.

The shared reachability probe (``_pg_guard``) and the guarded ``django_db_setup`` override live in
the repo-test-root ``tests/conftest.py`` (inherited by every DB-touching suite). This module keeps
only what is index-directory-specific:

- the ``BUNDESARCHIV_SKIP_PG=1`` collection-skip, scoped to THIS directory's items, and
- the ``pg_connection`` connectivity fixture used by ``test_connectivity.py``.

The pure architecture checks in this directory still run without Postgres.
"""

import os
from pathlib import Path

import pytest

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


@pytest.fixture
def pg_connection(_pg_guard: None, db: None) -> object:
    """A live Django default connection, on the created test DB. For connectivity tests."""
    from django.db import connection

    return connection

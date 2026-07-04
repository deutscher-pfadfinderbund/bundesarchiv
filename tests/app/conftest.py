"""Postgres gating specific to the ``tests/app/`` suite.

App-service tests drive synchronous index writes, so they need Postgres. The shared reachability
probe and guarded ``django_db_setup`` come from the repo-test-root ``tests/conftest.py``; this
module only scopes the ``BUNDESARCHIV_SKIP_PG=1`` collection-skip to THIS directory's items.

Exception: the ``web/`` subtree (Part 4.4 request→Viewer boundary + dev switcher) is pure
request-handling — it never touches Postgres — so those items are deliberately NOT skipped by
``SKIP_PG`` and keep running with no container.
"""

import os
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
_WEB = _HERE / "web"


def _is_app_item(item: pytest.Item) -> bool:
    path = Path(str(item.fspath))
    if path == _WEB or _WEB in path.parents:
        return False  # DB-free web tests must run even under BUNDESARCHIV_SKIP_PG=1
    return path == _HERE or _HERE in path.parents


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Honor BUNDESARCHIV_SKIP_PG=1: skip every test collected under this directory."""
    if os.environ.get("BUNDESARCHIV_SKIP_PG") != "1":
        return
    skip = pytest.mark.skip(reason="BUNDESARCHIV_SKIP_PG=1 (Postgres-backed app tests skipped)")
    for item in items:
        if _is_app_item(item):
            item.add_marker(skip)

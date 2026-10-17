"""The patch scanner (``scripts/quality/patches.py``) sees every way a test can patch our code."""

import ast
import textwrap

import pytest
from scripts.quality.patches import patch_sites

_IMPORTS = """
import time
from unittest import mock
from bundesarchiv.app import after_write, tasks
"""

_CASES = {
    "simple alias": (
        """
        aw = after_write
        def test_a(monkeypatch):
            monkeypatch.setattr(aw, "index_article", None)
        """,
        {("test_a", "bundesarchiv.app.after_write.index_article")},
    ),
    "patch.multiple": (
        """
        def test_a():
            mock.patch.multiple(tasks, run=None, defer=None)
        """,
        {("test_a", "bundesarchiv.app.tasks.run"), ("test_a", "bundesarchiv.app.tasks.defer")},
    ),
    "mocker patcher kind": (
        """
        def test_a(mocker):
            mocker.patch.object(tasks, "run")
        """,
        {("test_a", "bundesarchiv.app.tasks.run")},
    ),
    "attribute name not readable": (
        """
        def test_a(monkeypatch, name):
            monkeypatch.setattr(after_write, name, None)
        """,
        {("test_a", "<unresolved>")},
    ),
    "target not readable": (
        """
        def test_a(monkeypatch):
            monkeypatch.setattr(make_target(), "run", None)
        """,
        {("test_a", "<unresolved>")},
    ),
    "method scope carries its class": (
        """
        class TestX:
            def test_a(self, monkeypatch):
                monkeypatch.setattr("bundesarchiv.app.tasks.run", None)
        """,
        {("TestX.test_a", "bundesarchiv.app.tasks.run")},
    ),
    "external name": (
        """
        def test_a(monkeypatch):
            monkeypatch.setattr(time, "time", lambda: 0)
            mock.patch("httpx.get")
        """,
        set(),
    ),
}


@pytest.mark.parametrize(("source", "sites"), _CASES.values(), ids=_CASES.keys())
def test_patch_sites(source: str, sites: set[tuple[str, str]]) -> None:
    tree = ast.parse(_IMPORTS + textwrap.dedent(source))
    assert set(patch_sites(tree)) == sites

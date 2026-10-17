"""The index and queue stubs never raise, so ``after_write.run`` reports the index current."""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from itertools import count
from pathlib import Path
from typing import cast

import pytest
from django.test import override_settings
from procrastinate.contrib.django import app
from procrastinate.testing import InMemoryConnector
from tests.app.web._fixtures import Corpus, KeyRecordingStore, settings_for, standard_corpus

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence.objectstore import ObjectStore


@pytest.fixture
def corpus(tmp_path: Path) -> Iterator[Corpus]:
    """The frozen standard corpus (see ``_fixtures``), live for the test's duration."""
    built = standard_corpus(tmp_path / "canonical")
    with override_settings(**settings_for(built)):
        yield built


@pytest.fixture
def make_corpus(tmp_path: Path) -> Iterator[Callable[..., Corpus]]:
    """Build a fresh ROOT-only corpus to fill with bespoke content, or with ``template`` a copy of
    that corpus's files. Each call gets its own store and becomes the canonical root, so a test
    that needs two archives builds them in the order it wants to query them."""
    roots = count()
    with ExitStack() as stack:

        def build(template: Corpus | None = None) -> Corpus:
            root = tmp_path / f"canonical-{next(roots)}"
            built = Corpus(root) if template is None else template.copy(root)
            stack.enter_context(override_settings(**settings_for(built)))
            return built

        yield build


@pytest.fixture(scope="session")
def _templates() -> dict[Callable[[Corpus], None], Corpus]:
    return {}


@pytest.fixture
def copy_of(
    make_corpus: Callable[..., Corpus],
    tmp_path_factory: pytest.TempPathFactory,
    _templates: dict[Callable[[Corpus], None], Corpus],
) -> Callable[[Callable[[Corpus], None]], Corpus]:
    """``copy_of(fill)``: ``fill`` writes its content once per session into a template archive no
    test receives; each call returns a ``make_corpus`` copy of the template's files."""

    def build(fill: Callable[[Corpus], None]) -> Corpus:
        if fill not in _templates:
            _templates[fill] = Corpus(tmp_path_factory.mktemp("template") / "canonical")
            fill(_templates[fill])
        return make_corpus(_templates[fill])

    return build


@pytest.fixture
def recording_store(monkeypatch: pytest.MonkeyPatch) -> KeyRecordingStore:
    """Every view's ``Archive.canonical`` goes through a recorder over the real LocalFs store of
    whichever corpus is live, so a deny test can assert no blob was probed."""
    store = KeyRecordingStore(Archive.canonical)
    monkeypatch.setattr(
        Archive, "canonical", classmethod(lambda _: Archive.of(cast("ObjectStore", store)))
    )
    return store


@pytest.fixture(scope="session", autouse=True)
def _collect_static_assets() -> None:
    """Build STATIC_ROOT + the manifest once per session — the web tests run under prod settings,
    where {% static %} RAISES without one (ADR 0016). ``--clear`` drops a prior asset set's orphans."""
    from django.core.management import call_command

    call_command("collectstatic", "--no-input", "--clear", verbosity=0)


@pytest.fixture(autouse=True)
def _stub_service_boundaries(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No-op the index writes and the worker enqueues for the duration of a web test; a job that
    still reaches the queue lands in Procrastinate's in-memory connector. The canonical write
    (repository + README + CAS) stays real."""
    from bundesarchiv.app import after_write, articles

    for name in (
        "index_article",
        "index_subtree",
        "enqueue_mirror_push",
        "enqueue_mirror_delete_article",
        "enqueue_reindex_article",
        "enqueue_reindex_subtree",
    ):
        monkeypatch.setattr(after_write, name, lambda *a, **k: None)
    monkeypatch.setattr(articles, "enqueue_generate_thumbnail", lambda *a, **k: None)
    with app.replace_connector(InMemoryConnector()):
        yield

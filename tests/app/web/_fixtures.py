"""Shared corpus builders and the signed-viewer client for the web suite.

This is the whole wiring for ``tests/app/web/``, held once so no file clones another's: the
``corpus`` / ``make_corpus`` fixtures in ``conftest.py`` hand it out with the settings override
already applied.

**The standard corpus is FROZEN.** ``standard_corpus`` is ROOT → PUB (PUBLIC) with exactly two
articles, ``PUBLISHED_ULID`` and ``DRAFT_ULID``. Never extend it: a test that asserts a global
count, a listing or a facet total reads the whole store, so one added record silently rewrites
another file's expectations. Such a test builds its own content with ``make_corpus``.
"""

import io
import re
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from django.core import signing
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import Client
from django.urls import reverse
from tests import _articles

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web.viewers import _DEV_VIEWER_SALT, encode_viewer
from bundesarchiv.domain.models import (
    Article,
    Audience,
    AudienceTier,
    Collection,
    Lifecycle,
    Ulid,
    Version,
)
from bundesarchiv.domain.viewer import Viewer
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore
from bundesarchiv.persistence.collections import CollectionRepository
from bundesarchiv.persistence.repository import ArticleRepository

DEV_KEY = "test-web-dev-viewer-key"

ROOT = "ROOT"
# A real ULID: the collection routes validate their ``<ulid>`` in-view, so a mnemonic literal
# would 404 there instead of failing loudly.
PUB = "01KX7YT9E3VX0CP3A5Q49RZMPB"
PUBLISHED_ULID = "01KX7YT9E3VX0CP3A5Q49RZMWK"
DRAFT_ULID = "01KX7YT9E3VX0CP3A5Q49RZMVH"


def draft_mark() -> str:
    """The Entwurf mark as production renders it."""
    return render_to_string("components/mark_lifecycle.html", {"draft": True}).strip()


class _PageForms(HTMLParser):
    """The POST forms and their controls, a control's ``form=`` attribute included: it rides the
    named form's submit wherever it sits on the page."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[tuple[str, dict[str, str]]] = []
        self._by_id: dict[str, dict[str, str]] = {}
        self._elsewhere: list[tuple[str, dict[str, str]]] = []  # (form id, its controls)
        self._form: dict[str, str] | None = None
        self._fields: dict[str, str] | None = None  # where the current control writes
        self._select: str | None = None
        self._textarea: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self._form = {} if a.get("method") == "post" else None
            if self._form is not None:
                self.forms.append((a.get("action", ""), self._form))
                self._by_id[a.get("id", "")] = self._form
            self._fields = self._form
            return
        if a.get("form") and tag in ("input", "select", "textarea"):
            self._fields = {}
            self._elsewhere.append((a["form"], self._fields))
        elif tag in ("input", "select", "textarea"):
            self._fields = self._form
        if self._fields is None or (not a.get("name") and tag != "option"):
            return
        if tag == "input" and (a.get("type") not in ("checkbox", "radio") or "checked" in a):
            self._fields[a["name"]] = a.get("value", "")
        elif tag == "select":
            self._select = a["name"]
        elif tag == "option" and self._select is not None:
            if self._select not in self._fields or "selected" in a:
                self._fields[self._select] = a.get("value", "")
        elif tag == "textarea":
            self._textarea = a["name"]
            self._fields[self._textarea] = ""

    def handle_data(self, data: str) -> None:
        if self._textarea is not None and self._fields is not None:
            self._fields[self._textarea] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._form = self._fields = None
        elif tag == "select":
            self._select = None
        elif tag == "textarea":
            self._textarea = None

    def close(self) -> None:
        super().close()
        for form_id, controls in self._elsewhere:
            if form_id in self._by_id:
                self._by_id[form_id].update(controls)


def page_forms(body: str) -> list[tuple[str, dict[str, str]]]:
    """Every POST form a page hands out: its action and the values it would submit as rendered."""
    parser = _PageForms()
    parser.feed(body)
    parser.close()
    return parser.forms


def page_hrefs(body: str) -> list[str]:
    """Every link target on a page, unescaped."""
    return [unescape(href) for href in re.findall(r'href="([^"]*)"', body)]


def download_hrefs(body: str) -> list[str]:
    """Every link target on a page that the browser saves rather than opens (``download``)."""
    tags = (tag for tag in re.findall(r"<a\b[^>]*>", body) if re.search(r"\sdownload\b", tag))
    return [unescape(href) for tag in tags for href in re.findall(r'href="([^"]*)"', tag)]


def list_url(**params: str) -> str:
    """The list's address, ``params`` as its query."""
    return f"{reverse('workbench')}?{urlencode(params)}" if params else reverse("workbench")


def client_as(viewer: Viewer | None, *, enforce_csrf: bool = False) -> Client:
    """A test client carrying the signed ``dev_viewer`` cookie for ``viewer`` — or, for ``None``,
    no cookie at all (an anonymous visitor)."""
    client = Client(enforce_csrf_checks=enforce_csrf)
    if viewer is not None:
        signer = signing.TimestampSigner(key=DEV_KEY, salt=_DEV_VIEWER_SALT)
        client.cookies["dev_viewer"] = signer.sign(encode_viewer(viewer))
    return client


def make_collection(
    ulid: Ulid,
    name: str = "Sammlung",
    parent_id: Ulid | None = ROOT,
    audience: Audience | None = None,
) -> Collection:
    """A Collection under ROOT — pass only what the test asserts about."""
    return Collection(ulid, name, parent_id, audience)


# ``ulid`` stays explicit: the views reject anything that is not a real ULID (``is_valid_ulid``),
# so a literal like ``"A1"`` would 404 instead of failing loudly.
make_article = partial(_articles.make_article, collection_id=PUB)


class KeyRecordingStore:
    """The canonical store, resolved per call as production resolves it, recording the key of
    every port call — so a test sees whether a blob was probed. See the ``recording_store``
    fixture."""

    def __init__(self, canonical: Callable[[], Archive]) -> None:
        self._canonical = canonical
        self.keys: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., object]:
        method = getattr(self._canonical().store, name)

        def recorded(key: str = "", *args: object, **kwargs: object) -> object:
            self.keys.append(key)
            return method(key, *args, **kwargs)

        return recorded


class Corpus:
    """A local-FS archive rooted at ``root``, holding only the ROOT collection, with its store and
    both repositories ready for a test to add content through."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = LocalFsObjectStore(root)
        self.collections = CollectionRepository(self.store)
        self.articles = ArticleRepository(self.store)
        self.collections.save(Collection(ROOT, "Wurzel", None), 0, changed_by="tester")

    def add_collection(self, collection: Collection) -> Version:
        return self.collections.save(collection, 0, changed_by="tester")

    def add_article(self, article: Article) -> Version:
        return self.articles.save(article, 0, changed_by="tester")


def standard_corpus(root: Path) -> Corpus:
    """The frozen standard shape: ROOT → PUB (PUBLIC) with one published and one draft article.
    See the module docstring before adding anything to it."""
    corpus = Corpus(root)
    corpus.add_collection(
        make_collection(PUB, "Öffentlich", audience=Audience(AudienceTier.PUBLIC))
    )
    corpus.add_article(make_article(PUBLISHED_ULID, title="Sommerfahrt 1962", ref_code="F12"))
    corpus.add_article(
        make_article(
            DRAFT_ULID,
            lifecycle=Lifecycle.DRAFT,
            title="Entwurf Lagerchronik",
            ref_code="F9",
        )
    )
    return corpus


def settings_for(corpus: Corpus) -> dict[str, object]:
    """The settings a web test runs under: the prod urlconf, the dev-viewer signing key
    ``client_as`` signs with, and ``corpus`` as the canonical store.

    The ADR 0018 anonymous gate is OFF here, as it is in ``settings_dev``: these tests assert what
    each tier — anonymous included — is ANSWERED, which is the contract behind the gate and the one
    dev and the browser suites browse under. The gate itself is pinned by
    ``test_anonymous_gate.py`` and by the leak matrix's own gated walk, both of which turn it on."""
    return {
        "ROOT_URLCONF": "bundesarchiv.app.web.urls",
        "DEV_VIEWER_SIGNING_KEY": DEV_KEY,
        "ANONYMOUS_GATE_ENABLED": False,
        "BUNDESARCHIV_CANONICAL_ROOT": str(corpus.root),
    }


# --- every write route, by route name --------------------------------------------------
#
# The request half of the suites that enumerate the write routes (``test_changed_by.py``,
# ``test_index_lag.py``): each row performs its route's POST on the standard corpus and returns the
# response unfollowed. A new write route needs one row here and one in each of those suites.


def _version(corpus: Corpus, ulid: str) -> str:
    return str(corpus.articles.load(ulid).version)


def with_two_media(corpus: Corpus) -> tuple[str, str]:
    """Two files on the draft; their content hashes."""
    stored = corpus.articles.load(DRAFT_ULID)
    first = corpus.articles.add_media(DRAFT_ULID, "a.pdf", io.BytesIO(b"a"))
    second = corpus.articles.add_media(DRAFT_ULID, "b.pdf", io.BytesIO(b"b"))
    corpus.articles.save(
        replace(stored.article, media=(first, second)), stored.version, changed_by="tester"
    )
    return first.content_hash, second.content_hash


def _marked(corpus: Corpus, ulid: str) -> str:
    stored = corpus.articles.load(ulid)
    return str(corpus.articles.mark_deleted(stored.article, stored.version, changed_by="tester"))


_BLANK_FORM = dict.fromkeys(
    (
        "ref_code",
        "document_type",
        "tags",
        "date",
        "creator",
        "subject_place",
        "physical_location",
        "body",
        "sichtbarkeit",
        "gruppen",
    ),
    "",
)


def _create(client: Client, corpus: Corpus) -> Any:
    return client.post("/articles/new", {"title": "Neu", "collection_id": PUB})


def _edit(client: Client, corpus: Corpus) -> Any:
    return client.post(
        f"/articles/{DRAFT_ULID}/edit",
        {
            **_BLANK_FORM,
            "title": "Umbenannt",
            "collection_id": PUB,
            "media_type": "Foto(s)",
            "expected_version": _version(corpus, DRAFT_ULID),
        },
    )


def _copy(client: Client, corpus: Corpus) -> Any:
    return client.post(f"/articles/{PUBLISHED_ULID}/copy")


def _publish(client: Client, corpus: Corpus) -> Any:
    return client.post(
        f"/articles/{DRAFT_ULID}/publish", {"expected_version": _version(corpus, DRAFT_ULID)}
    )


def _delete(client: Client, corpus: Corpus) -> Any:
    return client.post(
        f"/articles/{PUBLISHED_ULID}/delete",
        {"expected_version": _version(corpus, PUBLISHED_ULID)},
    )


def _delete_permanently(client: Client, corpus: Corpus) -> Any:
    return client.post(
        f"/articles/{PUBLISHED_ULID}/delete-permanently",
        {"expected_version": _marked(corpus, PUBLISHED_ULID)},
    )


def _restore(client: Client, corpus: Corpus) -> Any:
    return client.post(
        f"/articles/{PUBLISHED_ULID}/restore",
        {"expected_version": _marked(corpus, PUBLISHED_ULID)},
    )


def _upload(client: Client, corpus: Corpus) -> Any:
    upload = SimpleUploadedFile("scan.pdf", b"%PDF-1.4", content_type="application/pdf")
    return client.post(f"/articles/{DRAFT_ULID}/media/upload", {"dateien": upload})


def _reorder(client: Client, corpus: Corpus) -> Any:
    first, _ = with_two_media(corpus)
    return client.post(f"/articles/{DRAFT_ULID}/media/move", {"hash": first, "richtung": "runter"})


def _remove(client: Client, corpus: Corpus) -> Any:
    first, _ = with_two_media(corpus)
    return client.post(
        f"/articles/{DRAFT_ULID}/media/remove", {"entfernen": first, "bestaetigt": "1"}
    )


def _bulk(client: Client, corpus: Corpus) -> Any:
    return client.post(
        "/articles/bulk-edit",
        {"auswahl": [DRAFT_ULID], "feld": "creator", "wert_text": "Kurt", "bestaetigt": "1"},
    )


def _create_bestand(client: Client, corpus: Corpus) -> Any:
    return client.post("/collections/new", {"name": "Karten", "parent_id": "", "sichtbarkeit": ""})


def _rename_bestand(client: Client, corpus: Corpus) -> Any:
    version = str(corpus.collections.load(PUB).version)
    return client.post(
        f"/collections/{PUB}/edit", {"name": "Umbenannt", "expected_version": version}
    )


WRITES: dict[str, Callable[[Client, Corpus], Any]] = {
    "artikel-neu": _create,
    "artikel-bearbeiten": _edit,
    "artikel-kopieren": _copy,
    "artikel-veroeffentlichen": _publish,
    "artikel-loeschen": _delete,
    "article-delete-permanently": _delete_permanently,
    "article-restore": _restore,
    "artikel-medien-hochladen": _upload,
    "artikel-medien-verschieben": _reorder,
    "artikel-medien-entfernen": _remove,
    "artikel-sammelbearbeitung": _bulk,
    "bestand-neu": _create_bestand,
    "bestand-bearbeiten": _rename_bestand,
}

"""The README re-encode (ADR 0019, amended 2026-10-16): a README gets the current writer's bytes only
when they read back as the same record, version and change, and hold everything the old bytes
held."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from tests._readmes import HAND_SAVED, OLD_ARTICLE, OLD_COLLECTION, UNREADABLE_README

from bundesarchiv.domain.models import Article, Change, Version
from bundesarchiv.persistence import readme
from bundesarchiv.persistence._front_matter import HEAD
from bundesarchiv.persistence.readme_relayout import ARTICLE, COLLECTION, Codec, relaid

_CHANGE = Change(datetime(2026, 9, 25, 10, 30, tzinfo=UTC), "anna")
_ULID = {"title": "01J0", "name": "01BESTAND"}


@pytest.mark.parametrize(
    ("old", "codec"),
    [
        pytest.param(OLD_ARTICLE, ARTICLE, id="article"),
        pytest.param(OLD_ARTICLE.replace("Ein Foto.", "# Ein Foto"), ARTICLE, id="body-heading"),
        pytest.param(OLD_ARTICLE.replace("Ein Foto.\n", ""), ARTICLE, id="body-opens-blank"),
        pytest.param(OLD_ARTICLE.split("---\nEin")[0] + "---\n", ARTICLE, id="empty-body"),
        pytest.param(OLD_COLLECTION, COLLECTION, id="collection"),
    ],
)
def test_an_old_readme_gets_the_writers_bytes(old: str, codec: Codec[Any]) -> None:
    ulid = _ULID[codec.title_key]
    new = relaid(ulid, old.encode(), codec)
    assert isinstance(new, bytes)
    record, version, change = codec.decode(ulid, old)
    assert change is not None
    assert new == codec.encode(record, version, change).encode()
    assert new.startswith(HEAD.encode())
    assert relaid(ulid, new, codec) is None


@pytest.mark.parametrize("saved", HAND_SAVED)
def test_a_hand_saved_readme_in_the_new_layout_gets_the_writers_bytes(
    saved: Callable[[str], bytes],
) -> None:
    text = readme.encode(Article("01J0", "Brief", "c", body="Text\n"), 2, _CHANGE)
    assert relaid("01J0", saved(text), ARTICLE) == text.encode()


@pytest.mark.parametrize(
    "data",
    [
        *UNREADABLE_README,
        pytest.param(b"---\nulid: 01J0\nversion: 1\n---\nBrief\n", id="new-layout-no-heading"),
        pytest.param(
            b"<!-- Notiz -->\n" + OLD_ARTICLE.encode().split(b"\n", 1)[1], id="foreign-html-comment"
        ),
    ],
)
def test_an_unreadable_readme_is_left(data: bytes) -> None:
    assert relaid("01J0", data, ARTICLE) == "unreadable"


def test_a_readme_without_a_change_record_is_left() -> None:
    old = "---\nulid: 01J0\nversion: 3\ntitle: t\ncollection_id: c\nlifecycle: draft\n---\n"
    assert relaid("01J0", old.encode(), ARTICLE) == "no change record"


def _other_title(article: Article, version: Version, change: Change) -> str:
    return readme.encode(replace(article, title="Anders"), version, change)


def _unreadable(article: Article, version: Version, change: Change) -> str:
    heading = f"# {article.title}\n"
    return readme.encode(article, version, change).replace(f"{heading}\n", heading)


_DRAFT = "lifecycle: draft\n"


@pytest.mark.parametrize(
    ("old", "codec"),
    [
        pytest.param(OLD_ARTICLE, replace(ARTICLE, encode=_other_title), id="reads-differently"),
        pytest.param(OLD_ARTICLE, replace(ARTICLE, encode=_unreadable), id="reads-not-at-all"),
        pytest.param(OLD_ARTICLE.replace(_DRAFT, f"{_DRAFT}zustand: gut\n"), ARTICLE, id="key"),
        pytest.param(OLD_ARTICLE.replace(_DRAFT, f"{_DRAFT}# Notiz\n"), ARTICLE, id="comment"),
        pytest.param(
            OLD_ARTICLE.replace(_DRAFT, "lifecycle: draft  # Notiz\n"), ARTICLE, id="inline"
        ),
        pytest.param(OLD_ARTICLE.replace(_DRAFT, _DRAFT * 2), ARTICLE, id="duplicate-key"),
        pytest.param(OLD_COLLECTION + "Notiz\n", COLLECTION, id="collection-body"),
    ],
)
def test_a_readme_the_writer_cannot_reproduce_in_full_is_left(old: str, codec: Codec[Any]) -> None:
    ulid = _ULID[codec.title_key]
    assert relaid(ulid, old.encode(), codec) == "would not read the same"


def test_a_title_the_writer_refuses_is_named_as_such() -> None:
    old = OLD_ARTICLE.replace("Zeltlager 1955: Fahrt", "")
    assert relaid(_ULID["title"], old.encode(), ARTICLE) == "title the writer refuses"


def test_the_old_marker_reads_with_whitespace_around_it() -> None:
    first, rest = OLD_ARTICLE.split("\n", 1)
    old = f"  {first} \t\n{rest}"
    assert isinstance(relaid(_ULID["title"], old.encode(), ARTICLE), bytes)

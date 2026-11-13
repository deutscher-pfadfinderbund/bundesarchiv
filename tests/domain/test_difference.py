"""What one Article version changed against the one before it: ``difference``."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from bundesarchiv.domain.history import Act, Difference, difference
from bundesarchiv.domain.models import (
    ULID,
    Article,
    Change,
    Lifecycle,
    MediaRef,
)

_PHOTO = MediaRef("zelt.jpg", "a" * 64, "image/jpeg", 10, caption="Zeltlager")
_LETTER = MediaRef("brief.pdf", "b" * 64, "application/pdf", 20)
_TRASHED = Change(datetime(2026, 3, 1, tzinfo=UTC), "anna.k")
_BASE = Article(
    ULID("01BASE"),
    "Titel",
    ULID("01COLL"),
    media=(_PHOTO,),
    custom=(("Kiste", "3"),),
    added_at=datetime(2026, 1, 1, tzinfo=UTC),
)

#: One other value for a field, and what that one change makes ``difference`` report: a plain field,
#: and each field with its own logic.
_ONE_FIELD = [
    ("title", "Anders", Difference(fields=frozenset({"title"}))),
    (
        "lifecycle",
        Lifecycle.PUBLISHED,
        Difference(fields=frozenset({"lifecycle"}), acts=frozenset({Act.PUBLISHED})),
    ),
    (
        "media",
        (_PHOTO, _LETTER),
        Difference(fields=frozenset({"media"}), added=((_LETTER.content_hash, "brief.pdf"),)),
    ),
    ("custom", (("Kiste", "4"),), Difference(custom=frozenset({"Kiste"}))),
    (
        "deleted",
        _TRASHED,
        Difference(fields=frozenset({"deleted"}), acts=frozenset({Act.TRASHED})),
    ),
]


@pytest.mark.parametrize(("name", "value", "expected"), _ONE_FIELD, ids=[n for n, *_ in _ONE_FIELD])
def test_one_changed_field_is_reported_and_nothing_else(
    name: str, value: Any, expected: Difference
) -> None:
    assert difference(_BASE, replace(_BASE, **{name: value})) == expected


def test_an_article_differs_from_itself_in_nothing() -> None:
    assert difference(_BASE, _BASE) == Difference()


def test_tags_in_a_new_order_are_no_difference() -> None:
    before = replace(_BASE, tags=("fahrt", "sommer"))
    assert difference(before, replace(before, tags=("sommer", "fahrt"))) == Difference()
    assert difference(before, replace(before, tags=("fahrt",))) == Difference(
        fields=frozenset({"tags"})
    )


def test_the_free_fields_are_named_by_key_and_only_where_they_differ() -> None:
    before = replace(_BASE, custom=(("Kiste", "3"), ("Ordner", "A"), ("Mappe", "1")))
    after = replace(_BASE, custom=(("Kiste", "3"), ("Ordner", "B"), ("Regal", "7")))
    assert difference(before, after) == Difference(custom=frozenset({"Ordner", "Mappe", "Regal"}))


_ADDED = MediaRef("plan.png", "c" * 64)


@pytest.mark.parametrize(
    ("after", "expected"),
    [
        pytest.param(
            (_PHOTO, _ADDED),
            Difference(fields=frozenset({"media"}), added=((_ADDED.content_hash, "plan.png"),)),
            id="added",
        ),
        pytest.param(
            (),
            Difference(fields=frozenset({"media"}), removed=((_PHOTO.content_hash, "zelt.jpg"),)),
            id="removed",
        ),
        pytest.param(
            (_ADDED,),
            Difference(
                fields=frozenset({"media"}),
                added=((_ADDED.content_hash, "plan.png"),),
                removed=((_PHOTO.content_hash, "zelt.jpg"),),
            ),
            id="replaced",
        ),
        pytest.param(
            (replace(_PHOTO, filename="lager.jpg"),),
            Difference(fields=frozenset({"media"})),
            id="the same bytes attached again under another name",
        ),
        pytest.param(
            (replace(_PHOTO, caption="Sommerlager"),),
            Difference(fields=frozenset({"media"})),
            id="the same bytes with another caption",
        ),
        pytest.param(
            (_LETTER, _PHOTO),
            Difference(fields=frozenset({"media"}), added=((_LETTER.content_hash, "brief.pdf"),)),
            id="added in front: the cover changes",
        ),
    ],
)
def test_files_are_added_or_removed_by_their_bytes(
    after: tuple[MediaRef, ...], expected: Difference
) -> None:
    assert difference(_BASE, replace(_BASE, media=after)) == expected


def test_a_new_order_of_the_same_files_names_the_files_and_adds_none() -> None:
    before = replace(_BASE, media=(_PHOTO, _LETTER))
    after = replace(_BASE, media=(_LETTER, _PHOTO))
    assert difference(before, after) == Difference(fields=frozenset({"media"}))


_DRAFT = replace(_BASE, lifecycle=Lifecycle.DRAFT)
_PUBLISHED = replace(_BASE, lifecycle=Lifecycle.PUBLISHED)
_IN_TRASH = replace(_BASE, deleted=_TRASHED)


@pytest.mark.parametrize(
    ("before", "after", "acts"),
    [
        pytest.param(_DRAFT, _PUBLISHED, {Act.PUBLISHED}, id="published"),
        pytest.param(_PUBLISHED, _DRAFT, {Act.UNPUBLISHED}, id="set back to draft"),
        pytest.param(_BASE, _IN_TRASH, {Act.TRASHED}, id="moved to the trash"),
        pytest.param(_IN_TRASH, _BASE, {Act.RESTORED}, id="restored"),
        pytest.param(
            _IN_TRASH,
            replace(_IN_TRASH, deleted=Change(datetime(2026, 4, 1, tzinfo=UTC), "ben.m")),
            set(),
            id="still in the trash, under another mark",
        ),
        pytest.param(
            replace(_IN_TRASH, lifecycle=Lifecycle.PUBLISHED),
            _DRAFT,
            {Act.RESTORED, Act.UNPUBLISHED},
            id="restored as a draft",
        ),
    ],
)
def test_the_acts_tell_the_direction_a_field_name_does_not(
    before: Article, after: Article, acts: set[Act]
) -> None:
    assert difference(before, after).acts == acts

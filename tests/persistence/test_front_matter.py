"""The README's title line (ADR 0019, amended 2026-10-16): `dump` writes it, `split_title` reads it
back, by a plain line rule rather than Markdown."""

import pytest

from bundesarchiv.domain.models import ULID
from bundesarchiv.persistence._front_matter import dump, parse, split_title
from bundesarchiv.persistence.errors import UnreadableReadme

ID_01J0 = ULID("01J0")

_OLD_MARKER = "<!-- Managed by bundesarchiv — do not edit by hand. -->"

_FRONT_MATTER = {"ulid": "01J0", "version": 1}


def test_the_title_is_the_first_line_of_the_body_then_one_blank_line() -> None:
    assert parse(ID_01J0, dump(_FRONT_MATTER, "Zeltlager", "Text"))[1] == "# Zeltlager\n\nText"


@pytest.mark.parametrize(
    "title",
    [
        "C# Kurs",
        "Titel #",
        "#",
        "*fett* _kursiv_ `code`",
        "Grüße 李明 100 %",
        " führend",
        "endend ",
        "Steuer\x07zeichen",
    ],
)
def test_any_one_line_title_round_trips(title: str) -> None:
    text = dump(_FRONT_MATTER, title, "Text")
    assert split_title(ID_01J0, text, "title") == (_FRONT_MATTER, title, "Text")


@pytest.mark.parametrize(
    "body",
    ["", "\n\nopens blank", "# Auch ein Titel\n\nText", "Text\n\nZeltlager\n", "ends\n---"],
)
def test_any_body_round_trips_after_the_title(body: str) -> None:
    text = dump(_FRONT_MATTER, "Zeltlager", body)
    assert split_title(ID_01J0, text, "title") == (_FRONT_MATTER, "Zeltlager", body)


@pytest.mark.parametrize(
    "title", ["", " ", "\t", "a\nb", "a\rb", "a\n", "a\x85b", "a\u2028b", "a\u2029b"]
)
def test_the_writer_refuses_a_title_the_line_cannot_hold(title: str) -> None:
    with pytest.raises(ValueError):
        dump(_FRONT_MATTER, title, "Text")


@pytest.mark.parametrize("body", ["", "Text", "# Something\n\nText", "\n# Titel\n\nText"])
def test_a_front_matter_holding_the_title_key_is_the_old_layout_with_its_body_verbatim(
    body: str,
) -> None:
    text = f"---\ntitle: t\n---\n{body}"
    assert split_title(ID_01J0, text, "title") == ({"title": "t"}, None, body)


@pytest.mark.parametrize("marker", [_OLD_MARKER, f"  {_OLD_MARKER} \t"])
def test_the_old_marker_line_opens_an_old_layout_readme(marker: str) -> None:
    text = f"{marker}\n---\ntitle: t\n---\nText"
    assert split_title(ID_01J0, text, "title") == ({"title": "t"}, None, "Text")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty"),
        pytest.param("Text", id="no-heading"),
        pytest.param("#Titel\n\nText", id="no-space"),
        pytest.param("  # Titel\n\nText", id="indented"),
        pytest.param("Titel\n=====\n\nText", id="setext"),
        pytest.param("\n# Titel\n\nText", id="blank-first"),
        pytest.param("# Titel\nText", id="no-blank-line"),
        pytest.param("# Titel", id="no-line-end"),
    ],
)
def test_a_new_layout_body_without_the_exact_heading_line_is_unreadable(body: str) -> None:
    with pytest.raises(UnreadableReadme):
        split_title(ID_01J0, f"---\nulid: 01J0\n---\n{body}", "title")

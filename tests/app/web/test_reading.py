"""The Lesesaal's why line: which field a hit names as where the query matched (pure, no DB)."""

from bundesarchiv.app.web import card
from bundesarchiv.app.web.reading import why
from bundesarchiv.index.query import Headline, HeadlineField

_LABELS = {f.name: f.label for f in card.FIELDS}


def _headline(field: HeadlineField, *, cut_start: bool = False, cut_end: bool = False) -> Headline:
    return Headline(field, (("am ", False), ("Lager", True)), cut_start, cut_end)


def test_a_title_holding_the_word_needs_no_why_line() -> None:
    assert why((_headline("title"), _headline("tags"))) is None
    assert why(()) is None


def test_the_why_line_names_the_heaviest_field_holding_the_word() -> None:
    order: tuple[HeadlineField, ...] = ("tags", "creator", "subject_place", "body")
    for at, field in enumerate(order):
        line = why(tuple(_headline(f) for f in reversed(order[at:])))
        assert line is not None
        assert (line.label, line.runs) == (_LABELS[field], _headline(field).runs)


def test_an_excerpt_cut_from_its_field_says_so_at_that_end() -> None:
    line = why((_headline("body", cut_start=True, cut_end=True),))
    assert line is not None
    assert "".join(text for text, _ in line.runs) == "… am Lager …"
    assert [text for text, marked in line.runs if marked] == ["Lager"]

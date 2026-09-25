"""The push record (ADR 0020): what the app last pushed to each key of the system of record. Both
implementations answer the same contract; a record that claims a key it never noted would keep
that key off the system of record for good."""

import pytest

from bundesarchiv.app.mirror import Pushed, PushRecord
from bundesarchiv.app.push_record import InMemoryPushRecord, PostgresPushRecord


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.django_db)])
def record(request: pytest.FixtureRequest) -> PushRecord:
    return InMemoryPushRecord() if request.param == "memory" else PostgresPushRecord()


def test_a_note_is_held_until_the_next_note_of_its_key_replaces_it(record: PushRecord) -> None:
    first, later = Pushed("a" * 64, "1"), Pushed("b" * 64, "2")
    record.note("articles/01A/README.md", first)
    assert record.held(["articles/01A/README.md"]) == {"articles/01A/README.md": first}
    record.note("articles/01A/README.md", later)
    assert record.held(["articles/01A/README.md"]) == {"articles/01A/README.md": later}
    assert record.entries() == {"articles/01A/README.md": later}


def test_held_answers_for_the_keys_asked_and_holds_nothing_it_was_not_told(
    record: PushRecord,
) -> None:
    pushed = Pushed("c" * 64, "7")
    record.note("articles/01A/history/1.md", pushed)
    record.note("articles/01B/history/1.md", pushed)
    assert record.held(["articles/01A/history/1.md", "articles/01A/README.md"]) == {
        "articles/01A/history/1.md": pushed
    }
    assert record.held([]) == {}


def test_keys_and_tokens_come_back_exactly_as_noted(record: PushRecord) -> None:
    keys = [
        "articles/01A/media/100% _Straße_.pdf",  # LIKE wildcards
        "articles/01A/media/ lead and trail ",
        "articles/01A/media/quote'\"back\\slash",
        "articles/01A/media/Müller.pdf",  # NFC and NFD are two keys
        "articles/01A/media/Müller.pdf",
    ]
    for index, key in enumerate(keys):
        record.note(key, Pushed(f"{index:064}", f' "etag/{index}%" '))
    assert record.entries() == {
        key: Pushed(f"{index:064}", f' "etag/{index}%" ') for index, key in enumerate(keys)
    }
    assert record.held(keys[3:4]) == {keys[3]: Pushed(f"{3:064}", ' "etag/3%" ')}


def test_forget_prefix_drops_exactly_the_folder(record: PushRecord) -> None:
    """What a hard delete took off the system of record. ``01A2`` shares the folder's name as a
    string prefix and stays."""
    pushed = Pushed("d" * 64, "3")
    gone = ["articles/01A/README.md", "articles/01A/history/1.md", "articles/01A/media/Scan.pdf"]
    kept = ["articles/01A2/README.md", "collections/01A/README.md"]
    for key in [*gone, *kept]:
        record.note(key, pushed)
    record.forget_prefix("articles/01A")
    assert record.entries() == dict.fromkeys(kept, pushed)

"""The Bestand chooser (debt #7) — the one per-request answer to "which Bestände are there?".

Pure: the chooser is driven by a plain loader here, exactly as the views drive it with the
archive's ``load_all``. What is pinned is what used to be spelled several ways — the ONE option
ordering, the two role placeholders (verbatim user contract), and the fail-closed membership rule
that gives an unknown ulid the same answer as an empty value.
"""

import pytest

from bundesarchiv.app.web.collection_chooser import TOP_LEVEL_LABEL, CollectionChooser
from bundesarchiv.domain.models import Collection

#: Two Bestände whose load order (the store lists by ulid) is the REVERSE of their name order, so
#: any test that passes under load order fails under name order and vice versa.
_LOAD_ORDER = (
    Collection(ulid="01ZEITUNGSAUSSCHNITTE00000", name="Zeitungsausschnitte"),
    Collection(ulid="02FOTOGRAFIEN0000000000000", name="Fotografien"),
)


def _chooser(*collections: Collection) -> CollectionChooser:
    return CollectionChooser(lambda: collections)


# --- the option lists --------------------------------------------------------------


def test_options_lead_with_the_placeholder_then_every_collection_by_name() -> None:
    assert _chooser(*_LOAD_ORDER).options() == (
        ("", "— Bestand wählen —"),
        ("02FOTOGRAFIEN0000000000000", "Fotografien"),
        ("01ZEITUNGSAUSSCHNITTE00000", "Zeitungsausschnitte"),
    )


def test_parent_options_lead_with_the_top_level_marker_then_the_same_order() -> None:
    chooser = _chooser(*_LOAD_ORDER)
    assert chooser.parent_options() == (("", TOP_LEVEL_LABEL), *chooser.options()[1:])


def test_an_empty_archive_still_offers_the_placeholder() -> None:
    assert _chooser().options() == (("", "— Bestand wählen —"),)


# --- membership: no existence oracle -----------------------------------------------


def test_accepts_a_saved_collection_and_ignores_surrounding_whitespace() -> None:
    chooser = _chooser(*_LOAD_ORDER)
    assert chooser.accepts("02FOTOGRAFIEN0000000000000")
    assert chooser.accepts("  02FOTOGRAFIEN0000000000000  ")


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "01UNBEKANNTERBESTAND000000",  # well-formed, names nothing
        "02fotografien0000000000000",  # ULIDs are upper-case
        "../../etc/passwd",
        "02FOTOGRAFIEN0000000000000 X",
    ],
)
def test_empty_malformed_and_unknown_are_the_same_refusal(raw: str) -> None:
    assert not _chooser(*_LOAD_ORDER).accepts(raw)


# --- resolving names ---------------------------------------------------------------


def test_name_of_resolves_a_saved_collection_and_yields_none_otherwise() -> None:
    chooser = _chooser(*_LOAD_ORDER)
    assert chooser.name_of("02FOTOGRAFIEN0000000000000") == "Fotografien"
    assert chooser.name_of("01UNBEKANNTERBESTAND000000") is None
    assert chooser.name_of("") is None


def test_the_loaded_set_is_addressable_by_ulid_and_by_name() -> None:
    chooser = _chooser(*_LOAD_ORDER)
    assert chooser.by_ulid() == {c.ulid: c for c in _LOAD_ORDER}
    assert chooser.names() == {c.ulid: c.name for c in _LOAD_ORDER}


# --- the chain: the one fail-closed resolution ---------------------------------------


def test_chain_of_is_the_collection_chain_leaf_first() -> None:
    root = Collection(ulid="ROOT", name="Archiv")
    leaf = Collection(ulid="LEAF", name="Fotografien", parent_id="ROOT")
    chain = _chooser(root, leaf).chain_of("LEAF")
    assert chain is not None and chain.collections == (leaf, root)


@pytest.mark.parametrize(
    "collection_id",
    [
        "UNKNOWN",  # names no Bestand
        "WAISE",  # its parent is missing
        "",
    ],
)
def test_chain_of_an_unresolvable_collection_is_none(collection_id: str) -> None:
    waise = Collection(ulid="WAISE", name="Waise", parent_id="FEHLT")
    assert _chooser(waise).chain_of(collection_id) is None

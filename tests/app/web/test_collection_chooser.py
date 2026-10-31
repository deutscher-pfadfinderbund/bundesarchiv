"""The Bestand chooser; its placeholder is verbatim user contract."""

import pytest

from bundesarchiv.app.web.collection_chooser import CollectionChooser
from bundesarchiv.domain.models import ULID, Collection

#: Two Bestände whose load order (the store lists by ulid) is the REVERSE of their name order, so
#: any test that passes under load order fails under name order and vice versa.
_LOAD_ORDER = (
    Collection(ulid=ULID("01ZEITUNGSAUSSCHNITTE00000"), name="Zeitungsausschnitte"),
    Collection(ulid=ULID("02FOTOGRAFIEN0000000000000"), name="Fotografien"),
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


def test_an_empty_archive_still_offers_the_placeholder() -> None:
    assert _chooser().options() == (("", "— Bestand wählen —"),)


# --- membership: no existence oracle -----------------------------------------------


@pytest.mark.parametrize("raw", ["02FOTOGRAFIEN0000000000000", "  02FOTOGRAFIEN0000000000000  "])
def test_resolve_gives_the_stored_ulid_of_a_saved_collection(raw: str) -> None:
    assert _chooser(*_LOAD_ORDER).resolve(raw) == _LOAD_ORDER[1].ulid


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
    chooser = _chooser(*_LOAD_ORDER)
    assert chooser.resolve(raw) is None
    assert not chooser.accepts(raw)


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
    root = Collection(ulid=ULID("ROOT"), name="Archiv")
    leaf = Collection(ulid=ULID("LEAF"), name="Fotografien", parent_id=ULID("ROOT"))
    chain = _chooser(root, leaf).chain_of(ULID("LEAF"))
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
    waise = Collection(ulid=ULID("WAISE"), name="Waise", parent_id=ULID("FEHLT"))
    assert _chooser(waise).chain_of(ULID(collection_id)) is None

"""domain.viewer — inert value objects describing *who is asking* (construction + equality)."""

import dataclasses

import pytest

from bundesarchiv.domain.viewer import Archivist, Member, Public, Viewer


def test_archivist_construction_and_equality() -> None:
    assert Archivist() == Archivist()


def test_public_construction_and_equality() -> None:
    assert Public() == Public()


def test_member_holds_its_keycloak_group_names() -> None:
    member = Member(groups=("vorstand", "stamm-koeln"))
    assert member.groups == ("vorstand", "stamm-koeln")


def test_member_defaults_to_no_groups() -> None:
    assert Member().groups == ()


def test_member_equality_by_groups() -> None:
    assert Member(groups=("a", "b")) == Member(groups=("a", "b"))
    assert Member(groups=("a",)) != Member(groups=("b",))


def test_member_groups_are_immutable() -> None:
    member = Member(groups=("vorstand",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        member.groups = ("admin",)  # type: ignore[misc]


def test_the_three_viewer_kinds_are_distinct_types() -> None:
    # Each kind is its own type and a member of the Viewer union; none is an
    # instance of another, so they can be dispatched on by type.
    kinds: tuple[Viewer, ...] = (Archivist(), Member(), Public())
    assert {type(k) for k in kinds} == {Archivist, Member, Public}
    assert isinstance(Archivist(), Archivist)
    assert not isinstance(Archivist(), Member | Public)
    assert not isinstance(Member(), Archivist | Public)
    assert not isinstance(Public(), Archivist | Member)

"""``viewer_from_claims`` — validated OIDC claims → domain ``Viewer`` (ADR 0018 claims contract).

The mapping is the whole authorization decision of a login: everything after it (cookie, gate,
domain policy) trusts the ``Viewer`` this returns. So the table below is exhaustive about the three
claims it reads — the realm role that grants Archivist, the username that names one, and the
forward-compat ``groups`` claim — including the shapes a hostile or merely misconfigured token can
carry: wrong types, wrong case, empty entries. Anything unrecognized must degrade to the LEAST
privileged authenticated viewer, ``Member(groups=())``, never to Archivist and never to an
exception; an archivist without a usable username is ``unbekannt`` (owner, 2026-09-24).
"""

from typing import Any

import pytest

from bundesarchiv.app.web.oidc import viewer_from_claims
from bundesarchiv.domain.viewer import Archivist, Member, Viewer

_ARCHIVIST = {"realm_access": {"roles": ["Bundesarchiv"]}}
_UNNAMED = Archivist(username="unbekannt")


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        pytest.param(
            {**_ARCHIVIST, "preferred_username": "anna.schmidt"},
            Archivist(username="anna.schmidt"),
            id="realm-role-present",
        ),
        pytest.param(_ARCHIVIST, _UNNAMED, id="username-absent"),
        pytest.param({**_ARCHIVIST, "preferred_username": None}, _UNNAMED, id="username-null"),
        pytest.param({**_ARCHIVIST, "preferred_username": ""}, _UNNAMED, id="username-empty"),
        pytest.param({**_ARCHIVIST, "preferred_username": "  "}, _UNNAMED, id="username-blank"),
        pytest.param(
            {**_ARCHIVIST, "preferred_username": ["anna"]}, _UNNAMED, id="username-not-a-string"
        ),
        pytest.param(
            {"realm_access": {"roles": ["offline_access", "Bundesarchiv", "uma_authorization"]}},
            Archivist(),
            id="realm-role-among-others",
        ),
        pytest.param(
            {"realm_access": {"roles": ["Bundesarchiv"]}, "groups": ["Orden St. Georg"]},
            Archivist(),
            id="archivist-ignores-groups",
        ),
        pytest.param(
            {},
            Member(groups=()),
            id="empty-claims",
        ),
        pytest.param(
            {"realm_access": {"roles": ["offline_access"]}},
            Member(groups=()),
            id="other-roles-only",
        ),
        pytest.param(
            {"realm_access": {"roles": ["bundesarchiv"]}},
            Member(groups=()),
            id="role-match-is-case-sensitive",
        ),
        pytest.param(
            {"realm_access": {"roles": "Bundesarchiv"}},
            Member(groups=()),
            id="roles-as-bare-string-is-not-a-role",
        ),
        pytest.param(
            {"realm_access": "Bundesarchiv"},
            Member(groups=()),
            id="realm-access-not-an-object",
        ),
        pytest.param(
            {"realm_access": {"roles": [None, 42, {"name": "Bundesarchiv"}]}},
            Member(groups=()),
            id="non-string-roles-ignored",
        ),
        pytest.param(
            {"groups": ["Orden St. Georg", "vorstand"]},
            Member(groups=("Orden St. Georg", "vorstand")),
            id="groups-claim-parsed",
        ),
        pytest.param(
            {"preferred_username": "anna.schmidt", "groups": ["vorstand"]},
            Member(groups=("vorstand",)),
            id="username-without-the-role-is-a-member",
        ),
        pytest.param({"groups": []}, Member(groups=()), id="empty-groups-claim"),
        pytest.param(
            {"groups": ["vorstand", "", None, 7]},
            Member(groups=("vorstand",)),
            id="only-non-empty-strings-survive",
        ),
        pytest.param({"groups": "vorstand"}, Member(groups=()), id="groups-as-bare-string"),
        pytest.param({"groups": None}, Member(groups=()), id="null-groups-claim"),
    ],
)
def test_claims_map_to_viewer(claims: dict[str, Any], expected: Viewer) -> None:
    assert viewer_from_claims(claims) == expected

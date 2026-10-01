"""Viewer value objects — *who is asking* (CONTEXT.md: Archivist, Member, Public).

Inert, per-request data injected into the access model. This module never reads
Keycloak: a Member's groups arrive as already-resolved names. The Audience *logic*
lives in `audience` and `access`; here the three kinds are plain value objects.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Archivist:
    """A holder of the archive's Keycloak realm role — sees everything. ``username`` is the
    Keycloak username, ``unbekannt`` when the login carried none (ADR 0019 "History and audit")."""

    username: str = "unbekannt"


@dataclass(frozen=True, slots=True)
class Member:
    """An authenticated DPB member. `groups` holds the Keycloak group names they
    hold (immutable; injected per request, never fetched here)."""

    groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Public:
    """An unauthenticated visitor. Later the holder of a special link to one Article; today it
    never passes the door (CONTEXT.md)."""


type Viewer = Archivist | Member | Public

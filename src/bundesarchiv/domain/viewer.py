"""Viewer value objects — *who is asking* (CONTEXT.md: Archivist, Member, Public).

Inert, per-request data injected into the access model. This module never reads
Keycloak: a Member's groups arrive as already-resolved names. The Audience *logic*
(effective-audience, field floors, `can_view`) lives in later Part 2 steps; here
the three kinds are plain value objects.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Archivist:
    """A member of the designated Keycloak Archivist group — sees everything."""


@dataclass(frozen=True, slots=True)
class Member:
    """An authenticated DPB member. `groups` holds the Keycloak group names they
    hold (immutable; injected per request, never fetched here)."""

    groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Public:
    """An unauthenticated visitor."""


type Viewer = Archivist | Member | Public

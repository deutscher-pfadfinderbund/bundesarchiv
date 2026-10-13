"""Who is asking (CONTEXT.md): per-request values. A Member's groups arrive resolved;
nothing here reads Keycloak."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Archivist:
    """A holder of the archive's Keycloak realm role — sees everything. ``username`` is the
    Keycloak username, ``unbekannt`` when the login carried none (ADR 0019 "History and audit")."""

    username: str = "unbekannt"


@dataclass(frozen=True, slots=True)
class Member:
    """An authenticated DPB member; `groups` are their Keycloak group names."""

    groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Public:
    """An unauthenticated visitor. Later the holder of a special link to one Article; today it
    never passes the door (CONTEXT.md)."""


type Viewer = Archivist | Member | Public

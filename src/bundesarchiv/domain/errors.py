"""Typed exception hierarchy for the pure domain core.

This hierarchy has its **own** base and deliberately does **not** extend the
persistence layer's `ArchiveError`: the dependency runs ``persistence -> domain``,
never the reverse, so the pure core must never import `persistence`.
"""


class DomainError(Exception):
    """Base class for all pure-core domain errors."""


class BrokenCollectionTree(DomainError):
    """Raised when an Article's owning Collection chain cannot be resolved —
    a missing parent, an unknown Collection, or a cycle. The access model
    fails closed rather than walking a broken tree."""


class MisresolvedChain(DomainError):
    """Raised when a Collection chain is not a usable owning chain — either ill-formed
    (empty, not parent-linked, or not terminated at a root: caught when a `ResolvedChain`
    is constructed) or bound to the wrong Article (its leaf is not the Article's own
    Collection: caught by the effective-Audience resolver). Distinct from
    `BrokenCollectionTree` (which is about *building* the chain from the lookup): this is a
    caller wiring the *wrong* chain in. Surfaces the bug loudly; at the visibility seam it
    is caught and denied."""

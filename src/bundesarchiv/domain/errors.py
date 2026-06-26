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
    """Raised when the Collection chain handed to the effective-Audience resolver
    is not a usable owning chain for the Article — it is empty, or its leaf is not
    the Article's own Collection. Distinct from `BrokenCollectionTree` (which is
    about *building* the chain): this is a caller wiring the *wrong* chain in.
    Surfaces the bug loudly; at the visibility seam it is caught and denied."""

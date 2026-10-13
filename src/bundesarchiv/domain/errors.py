"""Their own base, not `ArchiveError`: the core never imports `persistence`."""


class DomainError(Exception):
    pass


class BrokenCollectionTree(DomainError):
    """The owning chain cannot be built from the lookup (an unknown id or a cycle); access
    fails closed."""


class MisresolvedChain(DomainError):
    """A chain that is ill-formed or bound to the wrong Article: a caller wiring bug, which the
    visibility seam denies."""

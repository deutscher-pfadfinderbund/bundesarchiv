"""Config-version currency check (ADR 0014 §3) — the deploy/startup index guard.

When the ADR-0011 FTS config changes (config, collation, wrapper functions), ``CONFIG_VERSION``
bumps, and every index row written before carries a stale ``config_version``.
``ensure_index_current`` rebuilds the index from canonical when it finds one.

Kept in the app shell (not the index adapter) because it wires the canonical store to a rebuild;
the ``ensure_index_current`` management command is a one-line shell over it.
"""

from bundesarchiv.index import indexer
from bundesarchiv.persistence.objectstore import ObjectStore


def ensure_index_current(store: ObjectStore) -> bool:
    """Rebuild the index from ``store`` iff any row's ``config_version`` differs from the current
    ``indexer.CONFIG_VERSION`` (the FTS config changed under it). Returns True if a rebuild ran,
    False if the index was already current (including an empty index — nothing stale)."""
    if not indexer.config_stale():
        return False
    indexer.rebuild(store)
    return True

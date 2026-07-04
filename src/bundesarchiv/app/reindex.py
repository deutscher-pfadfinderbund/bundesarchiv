"""Config-version currency check (ADR 0014 §3) — the deploy/startup index guard.

When the ADR-0011 FTS config changes (config, collation, wrapper functions), ``CONFIG_VERSION``
bumps; every existing index row then carries a now-stale ``config_version`` and its generated
tsvector columns no longer match the new config. ``ensure_index_current`` detects any such row and
forces a full ``rebuild`` from canonical, which restamps every row at the current version. This is
the piece Part 4.2 adds — before it, only the ``config_version`` column existed, never the compare.

Kept in the app shell (not the index adapter) because it wires the canonical store to a rebuild;
the ``ensure_index_current`` management command is a one-line shell over it.
"""

from bundesarchiv.index import indexer
from bundesarchiv.index.models import ArticleIndex
from bundesarchiv.persistence.objectstore import ObjectStore


def ensure_index_current(store: ObjectStore) -> bool:
    """Rebuild the index from ``store`` iff any row's ``config_version`` differs from the current
    ``indexer.CONFIG_VERSION`` (the FTS config changed under it). Returns True if a rebuild ran,
    False if the index was already current (including an empty index — nothing stale)."""
    if not ArticleIndex.objects.exclude(config_version=indexer.CONFIG_VERSION).exists():
        return False
    indexer.rebuild(store)
    return True

"""Deploy-startup guard: rebuild the index when its rows carry a stale FTS config version
(ADR 0014 §3)."""

from bundesarchiv.index import indexer
from bundesarchiv.persistence.objectstore import ObjectStore


def ensure_index_current(store: ObjectStore) -> bool:
    if not indexer.config_stale():
        return False
    indexer.rebuild(store)
    return True

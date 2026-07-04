"""``manage.py ensure_index_current`` — the deploy/startup config_version guard (ADR 0014 §3).

A one-line shell over ``app.reindex.ensure_index_current``: if any index row's ``config_version``
differs from the current ``indexer.CONFIG_VERSION`` (the FTS config changed under it), rebuild the
whole index from the canonical store. Run it at deploy and on worker startup. Exit is always 0;
the message reports whether a rebuild ran.
"""

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from bundesarchiv.app.reindex import ensure_index_current
from bundesarchiv.persistence.adapters.localfs import LocalFsObjectStore


class Command(BaseCommand):
    help = "Rebuild the search index if any row's config_version is stale (ADR 0014)."

    def handle(self, *args: Any, **options: Any) -> None:
        store = LocalFsObjectStore(Path(settings.BUNDESARCHIV_CANONICAL_ROOT))
        rebuilt = ensure_index_current(store)
        if rebuilt:
            self.stdout.write("config_version mismatch found — index rebuilt from canonical.")
        else:
            self.stdout.write("index is current (no config_version mismatch).")

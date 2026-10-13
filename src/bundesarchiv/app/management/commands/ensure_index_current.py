from typing import Any

from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.reindex import ensure_index_current


class Command(BaseCommand):
    help = "Rebuild the search index if any row's config_version is stale (ADR 0014)."

    def handle(self, *args: Any, **options: Any) -> None:
        rebuilt = ensure_index_current(Archive.canonical().store)
        if rebuilt:
            self.stdout.write("config_version mismatch found — index rebuilt from canonical.")
        else:
            self.stdout.write("index is current (no config_version mismatch).")

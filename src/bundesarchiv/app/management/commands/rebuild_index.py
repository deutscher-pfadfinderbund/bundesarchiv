"""``manage.py rebuild_index`` — rebuild the whole search index from the canonical store.

The index is ONE Postgres table shared by every canonical root: ``indexer.rebuild`` empties it and
refills it from the store it is handed, so whichever root was indexed last owns it. This command is
how a root takes it back — after the legacy import pointed the index at the imported tree, or when
that import's own rebuild failed (the import refuses a second run, so it has no retry of its own).

Reads ``BUNDESARCHIV_CANONICAL_ROOT`` like every other entry point; rebuilding is idempotent.
"""

from typing import Any

from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.index import indexer


class Command(BaseCommand):
    help = "Rebuild the search index from BUNDESARCHIV_CANONICAL_ROOT (wipes the shared table)."

    def handle(self, *args: Any, **options: Any) -> None:
        report = indexer.rebuild(Archive.canonical().store)
        self.stdout.write(f"index rebuilt: {report.indexed} articles")
        if report.failed_closed:
            self.stdout.write(f"failed closed (unresolvable chain): {len(report.failed_closed)}")

"""``manage.py rebuild_index`` — rebuild the search index from the canonical store and read the
page text it lacks.

The index is shared by every canonical root; the root indexed last owns it. This command is how a
root takes it back — after the legacy import, or when that import's own rebuild failed.

Reads ``BUNDESARCHIV_CANONICAL_ROOT`` like every other entry point; rebuilding is idempotent.
"""

from typing import Any

from django.core.management.base import BaseCommand

from bundesarchiv.app import media_text
from bundesarchiv.app.archive import Archive
from bundesarchiv.index import indexer


class Command(BaseCommand):
    help = "Rebuild the search index from BUNDESARCHIV_CANONICAL_ROOT (wipes the shared table)."

    def handle(self, *args: Any, **options: Any) -> None:
        store = Archive.canonical().store
        report = indexer.rebuild(store)
        self.stdout.write(f"index rebuilt: {report.indexed} articles")
        if report.failed_closed:
            self.stdout.write(f"failed closed (unresolvable chain): {len(report.failed_closed)}")
        if report.unreadable_articles:
            names = ", ".join(report.unreadable_articles)
            self.stdout.write(f"articles whose README does not decode (archivist-only): {names}")
        if report.unreadable_collections:
            names = ", ".join(report.unreadable_collections)
            self.stdout.write(f"collections whose README does not decode (absent): {names}")
        filled = sum(media_text.extract(store, ulid) for ulid in media_text.missing(store))
        self.stdout.write(f"page text read: {filled} files")

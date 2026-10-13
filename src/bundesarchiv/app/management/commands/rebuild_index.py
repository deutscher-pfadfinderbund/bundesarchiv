"""``manage.py rebuild_index``: rebuild the search index from the canonical store and read the
page text it lacks.

The index is shared by every canonical root and the root indexed last owns it; this is how a root
takes it back.
"""

from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from bundesarchiv.app import media_text
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.media_text import HashMismatch, Pages, Unreadable
from bundesarchiv.index import indexer


class Command(BaseCommand):
    help = "Rebuild the search index from BUNDESARCHIV_CANONICAL_ROOT (wipes the shared table)."

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Archive.canonical()
        report = indexer.rebuild(archive.store)
        self.stdout.write(f"index rebuilt: {report.indexed} articles")
        if report.failed_closed:
            self.stdout.write(f"failed closed (unresolvable chain): {len(report.failed_closed)}")
        if report.unreadable_articles:
            names = ", ".join(report.unreadable_articles)
            self.stdout.write(f"articles whose README does not decode (archivist-only): {names}")
        if report.unreadable_collections:
            names = ", ".join(report.unreadable_collections)
            self.stdout.write(f"collections whose README does not decode (absent): {names}")
        read = Counter(
            type(parsed)
            for ulid in media_text.missing(archive)
            for parsed in media_text.fill(archive, ulid).values()
        )
        self.stdout.write(
            f"page text read: {read[Pages]} files, {read[Unreadable]} unreadable,"
            f" {read[HashMismatch]} not matching their hash"
        )

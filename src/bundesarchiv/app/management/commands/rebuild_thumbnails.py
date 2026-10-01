"""``manage.py rebuild_thumbnails`` — derive every missing thumbnail from the canonical store.

The import and a save derive thumbnails; this derives the rest, for a new host or a pruned cache.
A file whose thumbnail exists is skipped, so a second run derives nothing; a file that is not an
image derives nothing (``thumbnails.generate_thumbnail``). Reads ``BUNDESARCHIV_CANONICAL_ROOT``
and writes into ``BUNDESARCHIV_THUMBNAIL_ROOT``.
"""

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import generate_thumbnail, thumbnail_path


class Command(BaseCommand):
    help = "Derive every missing thumbnail from BUNDESARCHIV_CANONICAL_ROOT."

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Archive.canonical()
        root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
        generated = sum(
            generate_thumbnail(archive.store, ulid, ref.content_hash, root)
            for ulid in archive.articles.list_ulids()
            for ref in archive.articles.load(ulid).article.media
            if not thumbnail_path(root, ref.content_hash).is_file()
        )
        self.stdout.write(f"thumbnails generated: {generated}")

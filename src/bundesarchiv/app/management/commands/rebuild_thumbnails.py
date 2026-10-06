"""``manage.py rebuild_thumbnails`` — derive every missing tile from the canonical store.

The import and a save derive tiles; this derives the rest, for a new host, a pruned cache or a
format change, and removes the cache files of the retired WebP format and the temp files a
crashed write left. A file whose thumbnail exists is skipped (an empty one is re-derived), so a
second run derives nothing; a file no renderer reads (text, a broken or encrypted PDF) derives
nothing and never stops the run (``thumbnails.generate_thumbnail``). Reads
``BUNDESARCHIV_CANONICAL_ROOT`` and writes into ``BUNDESARCHIV_THUMBNAIL_ROOT``.
"""

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import generate_thumbnail, is_cached


class Command(BaseCommand):
    help = "Derive every missing thumbnail from BUNDESARCHIV_CANONICAL_ROOT."

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Archive.canonical()
        root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
        for stale in (*root.glob("*.webp"), *root.glob("*.tmp")):
            stale.unlink()
        generated = sum(
            generate_thumbnail(archive.store, ulid, ref.content_hash, root)
            for ulid in archive.articles.list_ulids()
            for ref in archive.articles.load(ulid).article.media
            if not is_cached(root, ref.content_hash)
        )
        self.stdout.write(f"thumbnails generated: {generated}")

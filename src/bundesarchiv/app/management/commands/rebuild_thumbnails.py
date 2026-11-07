"""``*.webp`` is the retired tile format; ``*.tmp`` a crashed write's leftover."""

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import Size, cached, generate_thumbnail, is_cached


class Command(BaseCommand):
    help = "Derive every missing thumbnail and display version from BUNDESARCHIV_CANONICAL_ROOT."

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Archive.canonical()
        root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
        for stale in (*root.glob("*.webp"), *root.glob("*.tmp")):
            stale.unlink()
        articles = archive.articles
        files = [
            (ulid, ref)
            for ulid in articles.list_ulids()
            for ref in articles.load(ulid).article.media
        ]
        # a tile cached before the job made display versions gets its display version alone
        for ulid, ref in files:
            if is_cached(root, ref.content_hash):
                cached(articles, ulid, ref, root, Size.DISPLAY)
        generated = sum(
            generate_thumbnail(archive.store, ulid, ref.content_hash, root)
            for ulid, ref in files
            if not is_cached(root, ref.content_hash)
        )
        self.stdout.write(f"thumbnails generated: {generated}")

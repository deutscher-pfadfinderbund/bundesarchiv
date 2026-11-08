"""``*.webp`` is the retired tile format; ``*.tmp`` a crashed write's leftover."""

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand

from bundesarchiv.app.archive import Archive
from bundesarchiv.app.thumbnails import Size, cached, generate_thumbnail, is_cached
from bundesarchiv.domain.models import ULID, MediaRef


class Command(BaseCommand):
    help = "Derive every missing thumbnail and display version from BUNDESARCHIV_CANONICAL_ROOT."

    def handle(self, *args: Any, **options: Any) -> None:
        archive = Archive.canonical()
        root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
        for stale in (*root.glob("*.webp"), *root.glob("*.tmp")):
            stale.unlink()
        articles = archive.articles

        def fill(ulid: ULID, ref: MediaRef) -> tuple[bool, bool]:
            """Whether a tile and a display version were written; a tile cached before the job
            made display versions gets its display version alone."""
            had_display = is_cached(root, ref.content_hash, Size.DISPLAY)
            if is_cached(root, ref.content_hash):
                tile = False
                cached(articles, ulid, ref, root, Size.DISPLAY)
            else:
                tile = generate_thumbnail(archive.store, ulid, ref.content_hash, root)
            return tile, not had_display and is_cached(root, ref.content_hash, Size.DISPLAY)

        written = [
            fill(ulid, ref)
            for ulid in articles.list_ulids()
            for ref in articles.load(ulid).article.media
        ]
        tiles = sum(tile for tile, _ in written)
        displays = sum(display for _, display in written)
        self.stdout.write(f"thumbnails generated: {tiles}, display versions generated: {displays}")

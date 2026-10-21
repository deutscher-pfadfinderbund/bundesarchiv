"""IO only; every mapping decision is ``app.legacy``.

It writes through the repository, not the ``app.articles`` shell, so it owes that shell's
after-steps (app/CLAUDE.md): one ``indexer.rebuild`` at the end (which takes over the shared index;
``rebuild_index`` hands it back), thumbnails inline (no worker drains the queue), the mirror push
left to the periodic reconcile.
"""

import csv
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app import legacy, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import vocab
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import ULID, Collection, MediaRef
from bundesarchiv.index import indexer
from bundesarchiv.persistence.repository import cleaned_name

#: How often the run says where it is. The import takes minutes; silence looks like a hang.
_PROGRESS_EVERY = 250


class Command(BaseCommand):
    help = "Import the legacy CSV export into the canonical archive (one-time)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--csv-dir", required=True, type=Path)
        parser.add_argument("--media-root", required=True, type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        csv_dir: Path = options["csv_dir"]
        media_root: Path = options["media_root"]
        if not media_root.is_dir():
            raise CommandError(f"Media directory not found: {media_root} — is the drive mounted?")
        archive = Archive.canonical()

        items = _read(csv_dir / "items.csv", legacy.ITEM_COLUMNS)
        files = _read(csv_dir / "files.csv", legacy.FILE_COLUMNS)
        _refuse_a_media_root_without_the_files(files, media_root)
        if options["dry_run"]:
            self._report(legacy.plan(items, files, _dry_ids(items)), items, media_root)
            return

        if any(archive.articles.list_ulids()):
            raise CommandError(
                "The canonical store already holds Articles — the legacy import runs exactly once. "
                "For another run, choose an empty BUNDESARCHIV_CANONICAL_ROOT."
            )

        plan = legacy.plan(items, files, self._create_collections(archive, items))
        missing, thumbnail_count = self._write(archive, plan, media_root)
        self.stdout.write(f"Thumbnails generated: {thumbnail_count}")
        self.stdout.write("Rebuilding the index …")
        indexer.rebuild(archive.store)
        self._report(plan, items, media_root, missing=missing)
        self.stdout.write("Checking the archive …")
        call_command("verify", stdout=self.stdout)

    # --- the writes ---------------------------------------------------------------

    def _create_collections(
        self, archive: Archive, items: Sequence[dict[str, str]]
    ) -> dict[str, ULID]:
        """Create every Bestand the export needs as a top-level Collection, idempotently BY NAME.

        By name, because the run may be resumed against a root that already holds the Bestände but
        no Articles (the refusal above only guards Articles) — creating a second "Bund" would split
        the archive in two. So an unreadable Bestand, whose name is unknown, stops the run.
        """
        scan = archive.collections.scan()
        if scan.unreadable:
            raise CommandError(f"Bestand unreadable: {', '.join(scan.unreadable)}")
        existing = {c.name: c.ulid for c in scan.readable}
        for name in legacy.collection_names(items):
            if name in existing:
                continue
            collection = Collection(ulid=identity.new_ulid(), name=name, parent_id=None)
            archive.collections.save(collection, 0, changed_by=legacy.CHANGED_BY)
            existing[name] = collection.ulid
        return existing

    def _write(
        self, archive: Archive, plan: legacy.Plan, media_root: Path
    ) -> tuple[list[str], int]:
        """Blobs before the Article: the repository refuses a README naming media it lacks.
        Returns the missing paths and the tile count."""
        thumbnail_root = Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT)
        thumbnail_count = 0
        missing: list[str] = []
        for done, item in enumerate(plan.items, start=1):
            refs: list[MediaRef] = []
            for media_file in item.media:
                blob = media_root / media_file.path
                if not blob.is_file():
                    missing.append(media_file.path)
                    continue
                if cleaned_name(media_file.filename) is None:
                    continue  # reported from the plan, like the dry run does
                with blob.open("rb") as source:
                    refs.append(
                        archive.articles.add_media(
                            item.article.ulid, media_file.filename, source, media_file.media_type
                        )
                    )
            archive.articles.save(
                replace(item.article, media=tuple(refs)), 0, changed_by=legacy.CHANGED_BY
            )
            thumbnail_count += sum(
                thumbnails.generate_thumbnail(
                    archive.store, item.article.ulid, ref.content_hash, thumbnail_root
                )
                for ref in refs
            )
            if done % _PROGRESS_EVERY == 0:
                self.stdout.write(f"… {done}/{len(plan.items)}")
        return missing, thumbnail_count

    def _report(
        self,
        plan: legacy.Plan,
        rows: Sequence[dict[str, str]],
        media_root: Path,
        *,
        missing: Sequence[str] | None = None,
    ) -> None:
        """Print the report, completed with the two things only this layer knows: which blobs were
        missing (a real run was told, a dry run has to look) and which values the edit form's
        vocabulary does not contain."""
        paths = (
            tuple(missing)
            if missing is not None
            else tuple(
                media_file.path
                for item in plan.items
                for media_file in item.media
                if not (media_root / media_file.path).is_file()
            )
        )
        strangers = legacy.unknown_vocabulary(
            rows,
            known_media_types=vocab.MEDIA_TYPES,
            known_document_types=vocab.DOCUMENT_TYPES,
        )
        report = plan.report.with_missing_blobs(paths).with_unknown_vocabulary(*strangers)
        for line in report.lines():
            self.stdout.write(line)


# --- reading ------------------------------------------------------------------------


def _read(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    """Read one export file, refusing a header that is not exactly ``columns``.

    The mapping is written against a known header; a column that appeared or moved in the old
    database would otherwise be dropped in silence, which is the one failure this import cannot
    recover from — the source is deleted afterwards.
    """
    if not path.is_file():
        raise CommandError(f"Export missing: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise CommandError(
                f"{path.name}: unexpected columns.\n  expected: {columns}\n  read:     "
                f"{tuple(reader.fieldnames or ())}"
            )
        return list(reader)


def _refuse_a_media_root_without_the_files(
    files: Sequence[dict[str, str]], media_root: Path
) -> None:
    """Stop when the export references files and NOT ONE of them is under ``media_root``.

    A wrong (but existing) media path otherwise yields a complete archive with no media at all, and
    the one-time refusal then blocks the second, correct run. A single missing blob stays tolerated
    and reported — only "none of them" is a root that cannot be the right one.
    """
    if files and not any((media_root / row["path"]).is_file() for row in files):
        raise CommandError(
            f"Not one of the {len(files)} exported files is under {media_root} — "
            "probably the wrong media path."
        )


def _dry_ids(items: Sequence[dict[str, str]]) -> dict[str, ULID]:
    """Throwaway Bestand ULIDs for the dry run, which creates nothing but still maps every row."""
    return {name: identity.new_ulid() for name in legacy.collection_names(items)}

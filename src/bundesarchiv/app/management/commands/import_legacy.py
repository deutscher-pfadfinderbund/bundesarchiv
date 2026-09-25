"""``manage.py import_legacy`` — the one-time import of the legacy archive (owner ruling: deployment
1 shows the real data).

IO only: read the CSV export and the media root, write through the ``Archive`` handle, rebuild the
index. Every mapping decision lives in ``app.legacy``, which is pure — so what can go wrong here is
what IO can do (a header that moved, a blob that is not on disk, a root that already holds an
archive), and each of those stops or is reported rather than guessed.

One-time by ruling, so it refuses a canonical root that already holds Articles: re-running it would
mint fresh ULIDs for records that already exist and double the archive. It refuses an absent media
root, or one that holds not a single exported file, for the same reason: a bad run leaves a
complete, media-less archive that only a manual wipe can undo. ``--dry-run`` writes nothing and
prints the same report the real run ends with.

It writes through the repository, not the ``app.articles`` shell, so it owes that shell's after-steps
itself (the ordering law in ``app/CLAUDE.md``): the per-article index sync becomes ONE
``indexer.rebuild`` at the end, thumbnails are generated INLINE (a batch, and the local run that
browses the result has no worker), and the mirror push is left to the periodic ``mirror.reconcile``
— 2506 enqueues say no more than one sweep.

The search index is one Postgres table for every canonical root, so the rebuild here hands it to the
imported tree; ``manage.py rebuild_index`` hands it back (README, "Legacy import").
"""

import csv
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app import legacy, thumbnails
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.web import vocab
from bundesarchiv.domain import identity
from bundesarchiv.domain.models import Collection, MediaRef, Ulid
from bundesarchiv.index import indexer
from bundesarchiv.persistence.repository import cleaned_name

#: How often the run says where it is. The import takes minutes; silence looks like a hang.
_PROGRESS_EVERY = 250

#: The ``changed_by`` of every imported version (ADR 0019). Keycloak stores usernames lowercase,
#: so the capitals keep it apart from any archivist's name.
CHANGED_BY = "Legacy-Import"


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
            raise CommandError(
                f"Medienverzeichnis nicht gefunden: {media_root} — Laufwerk nicht eingehängt?"
            )
        archive = Archive.canonical()

        items = _read(csv_dir / "items.csv", legacy.ITEM_COLUMNS)
        files = _read(csv_dir / "files.csv", legacy.FILE_COLUMNS)
        _refuse_a_media_root_without_the_files(files, media_root)
        if options["dry_run"]:
            self._report(legacy.plan(items, files, _dry_ids(items)), items, media_root)
            return

        if any(archive.articles.list_ulids()):
            raise CommandError(
                "Der kanonische Speicher enthält bereits Artikel — der Legacy-Import läuft genau "
                "einmal. Für einen erneuten Lauf einen leeren BUNDESARCHIV_CANONICAL_ROOT wählen."
            )

        plan = legacy.plan(items, files, self._create_bestaende(archive, items))
        missing, thumbnail_count = self._write(archive, plan, media_root)
        self.stdout.write(f"Vorschaubilder erzeugt: {thumbnail_count}")
        self.stdout.write("Index wird neu aufgebaut …")
        indexer.rebuild(archive.store)
        self._report(plan, items, media_root, missing=missing)

    # --- the writes ---------------------------------------------------------------

    def _create_bestaende(
        self, archive: Archive, items: Sequence[dict[str, str]]
    ) -> dict[str, Ulid]:
        """Create every Bestand the export needs as a top-level Collection, idempotently BY NAME.

        By name, because the run may be resumed against a root that already holds the Bestände but
        no Articles (the refusal above only guards Articles) — creating a second "Bund" would split
        the archive in two.
        """
        existing = {c.name: c.ulid for c in archive.collections.load_all()}
        for name in legacy.bestand_names(items):
            if name in existing:
                continue
            collection = Collection(ulid=identity.new_ulid(), name=name, parent_id=None)
            archive.collections.save(collection, 0, changed_by=CHANGED_BY)
            existing[name] = collection.ulid
        return existing

    def _write(
        self, archive: Archive, plan: legacy.Plan, media_root: Path
    ) -> tuple[list[str], int]:
        """Store each Article's blobs, then the Article, then its thumbnails. Returns the paths that
        were not on disk and how many thumbnails were derived.

        Blobs first, because the repository refuses a README that references media it does not
        hold. A blob missing from the media root, or one whose name cleans to nothing (ADR 0019),
        costs its reference, never the record: the Article is saved without it and the path is
        reported for the archivist to chase. Thumbnails last and inline: nothing else derives them,
        and a 404 cover on every imported image is what enqueuing into a queue no worker is draining
        would look like.
        """
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
                replace(item.article, media=tuple(refs)), 0, changed_by=CHANGED_BY
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
            known_media_types=vocab.MEDIENARTEN,
            known_document_types=vocab.DOKUMENTTYPEN,
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
        raise CommandError(f"Export fehlt: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != columns:
            raise CommandError(
                f"{path.name}: unerwartete Spalten.\n  erwartet: {columns}\n  gelesen:  "
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
            f"Keine einzige der {len(files)} exportierten Dateien liegt unter {media_root} — "
            "vermutlich der falsche Medienpfad."
        )


def _dry_ids(items: Sequence[dict[str, str]]) -> dict[str, Ulid]:
    """Throwaway Bestand ULIDs for the dry run, which creates nothing but still maps every row."""
    return {name: identity.new_ulid() for name in legacy.bestand_names(items)}

"""``manage.py verify`` — the fixity check of the canonical archive (ADR 0019 "Fixity").

A shell over ``persistence.fixity.verify``; any finding raises ``CommandError`` (exit status 1).
"""

from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence import fixity


class Command(BaseCommand):
    help = "Check the canonical archive's files against their READMEs (reports, never repairs)."

    def handle(self, *args: Any, **options: Any) -> None:
        report = fixity.verify(Archive.canonical().store)
        for line in _lines(report):
            self.stdout.write(line)
        if report.findings:
            raise CommandError(f"Befunde: {report.findings}")
        self.stdout.write("Keine Befunde.")


def _lines(report: fixity.Report) -> Iterator[str]:
    """The report as scannable lines (German, like the import's report it ends)."""
    yield f"Geprüft: {report.readmes} README-Versionen, {report.media} Mediendateien"
    for label, keys in (
        ("Unlesbare README-Versionen", report.unreadable_readmes),
        ("Unlesbare Dateien", report.unreadable_files),
        ("Mediendateien mit abweichender Prüfsumme", report.altered),
        ("Verweise ohne Datei", report.missing),
        ("Dateien ohne Verweis", report.unreferenced),
    ):
        yield f"{label}: {len(keys)}"
        yield from (f"  {key}" for key in keys)

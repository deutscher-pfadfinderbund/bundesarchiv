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
            raise CommandError(f"Findings: {report.findings}")
        self.stdout.write("No findings.")


def _lines(report: fixity.Report) -> Iterator[str]:
    """The report as scannable lines (English, like all console output)."""
    yield f"Checked: {report.readmes} README versions, {report.media} media files"
    for label, keys in (
        ("Unreadable README versions", report.unreadable_readmes),
        ("Unreadable files", report.unreadable_files),
        ("Media files with a mismatched checksum", report.altered),
        ("References without a file", report.missing),
        ("Files without a reference", report.unreferenced),
    ):
        yield f"{label}: {len(keys)}"
        yield from (f"  {key}" for key in keys)

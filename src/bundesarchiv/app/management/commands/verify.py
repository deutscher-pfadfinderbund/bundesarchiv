"""``manage.py verify`` — the fixity check of the canonical archive (ADR 0019 "Fixity").

A shell over ``persistence.fixity.verify``; any finding raises ``CommandError`` (exit status 1).
"""

import logging
from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence import fixity

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check the canonical archive's files against their READMEs (reports, never repairs)."

    def handle(self, *args: Any, **options: Any) -> None:
        report = fixity.verify(Archive.canonical().store)
        for line in _lines(report):
            self.stdout.write(line)
        _log(report)
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


def _log(report: fixity.Report) -> None:
    """The report as one structured record (the dashboard alerts on ``checksum_mismatches`` > 0):
    INFO when clean, ERROR when anything was found."""
    ok = not report.findings
    logger.log(
        logging.INFO if ok else logging.ERROR,
        "fixity check %s",
        "ok" if ok else "failed",
        extra={
            "outcome": "ok" if ok else "failed",
            "checked_readmes": report.readmes,
            "checked_files": report.media,
            "checksum_mismatches": len(report.altered),
            "unreadable_readmes": len(report.unreadable_readmes),
            "unreadable_files": len(report.unreadable_files),
            "refs_without_file": len(report.missing),
            "files_without_ref": len(report.unreferenced),
        },
    )

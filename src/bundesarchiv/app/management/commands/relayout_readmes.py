"""``manage.py relayout_readmes`` — a shell over ``readme_relayout.relayout``. Run it with the app
stopped: it takes no lock. ``--dry-run`` writes nothing, so it may run beside the app."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence import readme_relayout


class Command(BaseCommand):
    help = "Re-encode every current README in the layout the app writes now (one-off)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing.")

    def handle(self, *args: Any, **options: Any) -> None:
        report = readme_relayout.relayout(Archive.canonical().store, dry_run=options["dry_run"])
        self.stdout.write(f"Rewritten: {report.rewritten}")
        self.stdout.write(f"Already new: {report.already_new}")
        for key, reason in report.left:
            self.stdout.write(f"Left as it is ({reason}): {key}")
        if report.left:
            raise CommandError(f"Left as it is: {len(report.left)}")

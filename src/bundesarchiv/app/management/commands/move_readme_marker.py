"""``manage.py move_readme_marker`` — a shell over ``marker_move.move_markers``. Run it with the app
stopped: it takes no lock."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from bundesarchiv.app.archive import Archive
from bundesarchiv.persistence import marker_move


class Command(BaseCommand):
    help = "Move the managed-by marker of every current README inside its front matter (one-off)."

    def handle(self, *args: Any, **options: Any) -> None:
        report = marker_move.move_markers(Archive.canonical().store)
        self.stdout.write(f"Rewritten: {report.rewritten}")
        self.stdout.write(f"Already new: {report.already_new}")
        for key in report.skipped:
            self.stdout.write(f"Not the old shape, left as it is: {key}")
        if report.skipped:
            raise CommandError(f"Skipped: {len(report.skipped)}")

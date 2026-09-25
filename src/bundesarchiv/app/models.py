"""The app's one table, behind `push_record.PostgresPushRecord` (ADR 0020)."""

from django.db import models


class PushedKey(models.Model):
    """One key the app pushed to the system of record: the SHA-256 of the local bytes and the
    version token the write returned. Derived: the next reconcile rebuilds a lost row."""

    key = models.TextField(primary_key=True)
    sha256 = models.CharField(max_length=64)
    version = models.TextField()

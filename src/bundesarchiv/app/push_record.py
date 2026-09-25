"""The push record (ADR 0020): per key on the system of record, what the app last pushed there.

Both classes are the `mirror.PushRecord` the mirror logic takes: `PostgresPushRecord` for the
worker, `InMemoryPushRecord` as the test fake. The record is derived state, like the search index.
"""

from collections.abc import Iterable

from django.db.models import QuerySet

from bundesarchiv.app.mirror import Pushed
from bundesarchiv.app.models import PushedKey


class PostgresPushRecord:
    """The push record as `PushedKey` rows. Every `note` commits on its own."""

    def held(self, keys: Iterable[str]) -> dict[str, Pushed]:
        return _pushed(PushedKey.objects.filter(key__in=list(keys)))

    def entries(self) -> dict[str, Pushed]:
        return _pushed(PushedKey.objects.all())

    def note(self, key: str, pushed: Pushed) -> None:
        PushedKey.objects.bulk_create(
            [PushedKey(key=key, sha256=pushed.sha256, version=pushed.version)],
            update_conflicts=True,
            unique_fields=["key"],
            update_fields=["sha256", "version"],
        )

    def forget_prefix(self, prefix: str) -> None:
        PushedKey.objects.filter(key__startswith=f"{prefix}/").delete()


class InMemoryPushRecord:
    """The push record in a dict."""

    def __init__(self) -> None:
        self._entries: dict[str, Pushed] = {}

    def held(self, keys: Iterable[str]) -> dict[str, Pushed]:
        return {key: self._entries[key] for key in keys if key in self._entries}

    def entries(self) -> dict[str, Pushed]:
        return dict(self._entries)

    def note(self, key: str, pushed: Pushed) -> None:
        self._entries[key] = pushed

    def forget_prefix(self, prefix: str) -> None:
        self._entries = {
            key: pushed for key, pushed in self._entries.items() if not key.startswith(f"{prefix}/")
        }


def _pushed(rows: QuerySet[PushedKey]) -> dict[str, Pushed]:
    return {
        key: Pushed(sha256, version)
        for key, sha256, version in rows.values_list("key", "sha256", "version")
    }

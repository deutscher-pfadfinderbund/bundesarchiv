"""The worker queue in a test: Procrastinate's in-memory connector, which can refuse a task,
and a one-shot worker run."""

from collections.abc import Callable

from django.test import override_settings
from procrastinate import types
from procrastinate.contrib.django import app
from procrastinate.testing import InMemoryConnector

MIRROR = "http://mirror.example/dav/"


class _Refusing(InMemoryConnector):
    def __init__(self, refused: frozenset[str]) -> None:
        super().__init__()
        self.refused = refused

    async def defer_jobs_all(self, jobs: list[types.JobToDefer]) -> list[types.JSONDict]:
        if any(job.task_name in self.refused for job in jobs):
            raise RuntimeError("queue down")
        return await super().defer_jobs_all(jobs)


def queued(
    enqueue: Callable[[], object], *, mirror: bool = False, refuse: frozenset[str] = frozenset()
) -> list[tuple[str, types.JSONDict]]:
    """The (task, args) of every job ``enqueue`` queues; the mirror jobs only when ``mirror`` says
    a system of record is configured; deferring a ``refuse``d task raises."""
    connector = _Refusing(refuse)
    with (
        override_settings(BUNDESARCHIV_MIRROR_DAV_URL=MIRROR if mirror else None),
        app.replace_connector(connector),
    ):
        enqueue()
    return [(job["task_name"], job["args"]) for job in connector.jobs.values()]


def run_worker_once_in_test(defer: Callable[[], None]) -> int:
    """Run ``defer`` to enqueue job(s), then drain the worker once (no wait, no signal handlers, no
    LISTEN/NOTIFY). Returns the number of jobs finished. The tasks still write the real database."""
    connector = InMemoryConnector()
    with app.replace_connector(connector):
        defer()
        app.run_worker(
            wait=False, install_signal_handlers=False, listen_notify=False, delete_jobs="never"
        )
    return len(connector.finished_jobs)

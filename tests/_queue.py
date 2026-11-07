"""The worker queue in a test: Procrastinate's in-memory connector, which can refuse a job, and a
one-shot worker run."""

from collections.abc import Callable

from django.test import override_settings
from procrastinate import types
from procrastinate.contrib.django import app
from procrastinate.testing import InMemoryConnector

from bundesarchiv.app.jobs import Job
from bundesarchiv.app.tasks import decoded

MIRROR = "http://mirror.example/dav/"


class _Refusing(InMemoryConnector):
    def __init__(self, refused: frozenset[type[Job]]) -> None:
        super().__init__()
        self.refused = refused

    async def defer_jobs_all(self, jobs: list[types.JobToDefer]) -> list[types.JSONDict]:
        if any(type(decoded(job.task_name, job.args)) in self.refused for job in jobs):
            raise RuntimeError("queue down")
        return await super().defer_jobs_all(jobs)


def queued_calls(
    enqueue: Callable[[], object],
    *,
    mirror: bool = False,
    refuse: frozenset[type[Job]] = frozenset(),
) -> list[tuple[str, types.JSONDict]]:
    """The (task, args) of every job ``enqueue`` queues, as Procrastinate stores them; the mirror
    jobs only when ``mirror`` says a system of record is configured; queueing a job of a
    ``refuse``d kind raises."""
    connector = _Refusing(refuse)
    with (
        override_settings(BUNDESARCHIV_MIRROR_DAV_URL=MIRROR if mirror else None),
        app.replace_connector(connector),
    ):
        enqueue()
    return [(job["task_name"], job["args"]) for job in connector.jobs.values()]


def queued(
    enqueue: Callable[[], object],
    *,
    mirror: bool = False,
    refuse: frozenset[type[Job]] = frozenset(),
) -> list[Job]:
    """The jobs ``enqueue`` queues, decoded as the worker decodes them (``queued_calls``)."""
    return [decoded(*call) for call in queued_calls(enqueue, mirror=mirror, refuse=refuse)]


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

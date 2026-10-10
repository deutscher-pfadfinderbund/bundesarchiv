"""The worker queue in a test: Procrastinate's in-memory connector, which can refuse a task."""

from collections.abc import Callable

from procrastinate import types
from procrastinate.contrib.django import app
from procrastinate.testing import InMemoryConnector


class _Refusing(InMemoryConnector):
    def __init__(self, refused: frozenset[str]) -> None:
        super().__init__()
        self.refused = refused

    async def defer_jobs_all(self, jobs: list[types.JobToDefer]) -> list[types.JSONDict]:
        if any(job.task_name in self.refused for job in jobs):
            raise RuntimeError("queue down")
        return await super().defer_jobs_all(jobs)


def queued(
    enqueue: Callable[[], object], *, refuse: frozenset[str] = frozenset()
) -> list[tuple[str, types.JSONDict]]:
    """The (task, args) of every job ``enqueue`` queues; deferring a ``refuse``d task raises."""
    connector = _Refusing(refuse)
    with app.replace_connector(connector):
        enqueue()
    return [(job["task_name"], job["args"]) for job in connector.jobs.values()]

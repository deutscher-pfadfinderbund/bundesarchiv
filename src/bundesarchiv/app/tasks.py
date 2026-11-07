"""The queue: Procrastinate's tasks, and ``enqueue``, the one place a ``jobs.Job`` meets them.
Each task decodes its job and runs it against what ``_deps`` resolves from settings.
"""

import contextlib
from collections.abc import Generator, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, get_args

import httpx2  # noqa: TID251
from django.conf import settings
from django.core.management import call_command
from procrastinate import RetryStrategy  # noqa: TID251
from procrastinate.contrib.django import app  # noqa: TID251
from procrastinate.exceptions import AlreadyEnqueued  # noqa: TID251
from procrastinate.tasks import Task  # noqa: TID251

from bundesarchiv.app import jobs
from bundesarchiv.app.archive import Archive
from bundesarchiv.app.jobs import Job
from bundesarchiv.app.mirror import RecordKind
from bundesarchiv.app.push_record import PostgresPushRecord
from bundesarchiv.app.upload_staging import STALE_AFTER_SECONDS, Staging
from bundesarchiv.persistence.adapters.webdav import WebDavObjectStore

#: Bounded exponential backoff for the mirror jobs. A down/slow WebDAV server is the EXPECTED
#: failure mode (ADR 0005): retry a handful of times with growing waits (~3s, 9s, 27s, 81s), then
#: PARK the job (max_attempts reached -> Procrastinate marks it failed); the daily reconcile pushes
#: what a parked job would have (ADR 0020 "Loss window").
_MIRROR_RETRY = RetryStrategy(max_attempts=5, exponential_wait=3)

#: ADR 0019 "Fixity".
_VERIFY_CRON = "0 4 1 * *"

#: Hourly, off the hour the reconcile takes.
_SWEEP_CRON = "30 * * * *"

#: A connect to the system of record that takes longer than 5 s is a partition, not a slow server:
#: fail the attempt then, not after the 30 s a slow answer may take, so the one worker moves on.
_MIRROR_TIMEOUT = httpx2.Timeout(30, connect=5)


@contextlib.contextmanager
def mirror_store() -> Generator[WebDavObjectStore | None]:
    """The system of record (ADR 0020) for one job, closed after it; None when none is
    configured."""
    url: str | None = settings.BUNDESARCHIV_MIRROR_DAV_URL
    if not url:
        yield None
        return
    user: str | None = settings.BUNDESARCHIV_MIRROR_DAV_USER
    password: str | None = settings.BUNDESARCHIV_MIRROR_DAV_PASSWORD
    auth: tuple[str, str] | None = (user, password or "") if user is not None else None
    client = httpx2.Client(base_url=url, auth=auth, timeout=_MIRROR_TIMEOUT)
    with contextlib.closing(WebDavObjectStore(client)) as remote:
        yield remote


def _deps() -> jobs.Deps:
    return jobs.Deps(
        archive=Archive.canonical(),
        thumbnail_root=Path(settings.BUNDESARCHIV_THUMBNAIL_ROOT),
        mirror=mirror_store,
        record=PostgresPushRecord(),
    )


# --- the jobs' tasks ---------------------------------------------------------------


type _JobTask = Task[..., None, ...]


def _task(name: str, *, retry: RetryStrategy | bool = False) -> _JobTask:
    @app.task(name=name, retry=retry)
    def task(**args: Any) -> None:
        deps = _deps()
        for job in _received(name, args):
            jobs.run(job, deps)

    return task


reindex_article = _task("reindex_article")
reindex_subtree = _task("reindex_subtree")
generate_thumbnail = _task("generate_thumbnail")
extract_media_text = _task("extract_media_text")
# A failed attempt raises, which triggers the bounded retry.
mirror_push = _task("mirror_push", retry=_MIRROR_RETRY)
mirror_delete_article = _task("mirror_delete_article", retry=_MIRROR_RETRY)

#: Each job's task, and whether a job of it already queued for the same ulid stands in for a new
#: one (a queueing lock): it reads current truth when it runs.
_TASKS: dict[type[Job], tuple[_JobTask, bool]] = {
    jobs.ReindexArticle: (reindex_article, False),
    jobs.ReindexSubtree: (reindex_subtree, False),
    jobs.Thumbnail: (generate_thumbnail, False),
    jobs.PageText: (extract_media_text, True),
    jobs.MirrorPush: (mirror_push, True),
    jobs.MirrorDelete: (mirror_delete_article, False),
}
_JOBS: dict[str, type[Job]] = {task.name: kind for kind, (task, _) in _TASKS.items()}


def enqueue(job: Job) -> None:
    """Queue ``job``; a mirror job only when a system of record is configured, asked of the
    setting: building a client in ``mirror_store`` to drop it costs an eager SSL-context load."""
    if isinstance(job, jobs.MirrorJob) and not settings.BUNDESARCHIV_MIRROR_DAV_URL:
        return
    task, locked = _TASKS[type(job)]
    args = asdict(job)
    lock = f"{task.name}:{args['ulid']}" if locked else None
    with contextlib.suppress(AlreadyEnqueued):
        task.configure(queueing_lock=lock).defer(**args)


def decoded(task_name: str, args: Mapping[str, Any]) -> Job:
    """The job a queued call of ``task_name`` with ``args`` stands for."""
    return _JOBS[task_name](**args)


def _received(task_name: str, args: Mapping[str, Any]) -> tuple[Job, ...]:
    """``decoded``, but a ``mirror_push`` queued before the job carried its kind pushes its ulid as
    either kind, as it did then: its queueing lock holds back every later push of that record."""
    if task_name == mirror_push.name and "kind" not in args:
        return tuple(jobs.MirrorPush(args["ulid"], kind) for kind in get_args(RecordKind.__value__))
    return (decoded(task_name, args),)


# --- periodic tasks ----------------------------------------------------------------


@app.periodic(cron=settings.BUNDESARCHIV_RECONCILE_CRON)
@app.task(name="reconcile")
def reconcile(timestamp: int) -> None:
    jobs.reconcile(Archive.canonical(), enqueue)


@app.periodic(cron=_VERIFY_CRON)
@app.task(name="verify")
def verify(timestamp: int) -> None:
    """A finding raises ``CommandError`` and so fails the job."""
    call_command("verify")


@app.periodic(cron=_SWEEP_CRON)
@app.task(name="sweep_upload_staging")
def sweep(timestamp: int) -> None:
    """ADR 0026: chunked uploads untouched for a day, abandoned or finished."""
    Staging.configured().sweep(older_than=timestamp - STALE_AFTER_SECONDS)


@app.periodic(cron=settings.BUNDESARCHIV_MIRROR_RECONCILE_CRON)
@app.task(name="mirror_reconcile")
def mirror_reconcile(timestamp: int = 0) -> dict[str, object]:
    with mirror_store() as remote:
        if remote is None:
            return {"skipped": True}
        return jobs.mirror_reconcile(
            Archive.canonical(), remote, PostgresPushRecord(), size=remote.root_size
        )

# DPB Bundesarchiv

A long-lived, controlled-visibility multimedia archive (photos, audio, video, scans, documents) for the Deutscher Pfadfinderbund.

- Domain glossary — [CONTEXT.md](CONTEXT.md)
- Design decisions — [docs/adr/](docs/adr/)
- v1 design overview — [docs/design/bundesarchiv-v1.md](docs/design/bundesarchiv-v1.md)
- Conventions — [docs/conventions.md](docs/conventions.md)
- Django 6 notes — [docs/django6-notes.md](docs/django6-notes.md)
- Python 3.14 notes — [docs/python314-notes.md](docs/python314-notes.md)

## Development

Python ≥ 3.14, managed with [uv](https://docs.astral.sh/uv/).

```sh
uv sync            # install dependencies
uv run pytest      # run tests
pre-commit install # enable lint + type-check + test hooks
```

### Search index (Postgres)

The derived search index needs a Postgres 18 with a German Hunspell dictionary baked in.
Local dev uses Apple's [`container`](https://github.com/apple/container) CLI (Docker is
not the dev path); build and run it, then apply migrations:

```sh
container build -t bundesarchiv-postgres docker/postgres/
container run -d --name bundesarchiv-pg -p 5434:5432 \
  -e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres
uv run manage.py migrate
```

`docker-compose.yml` is the VPS deploy artifact, not the local dev path — but
`docker compose up -d` works too and publishes the same Postgres on `localhost:5434`.
Tests connect via `BUNDESARCHIV_PG_DSN` (default
`postgresql://postgres:postgres@localhost:5434/bundesarchiv`). Index tests require a
running Postgres and **fail** (not skip) if it is unreachable; set `BUNDESARCHIV_SKIP_PG=1`
to skip the DB-backed (`tests/index/`, `tests/app/`) suites for domain-only work.

### Background worker (Procrastinate) — ADR 0014

The search index is kept current by a Postgres-backed worker
([Procrastinate](https://procrastinate.readthedocs.io/)): no broker, jobs live in
Postgres tables applied by `migrate`. Web write paths update the index synchronously
(the app-service layer); the worker is the retry net for failed synchronous updates,
plus the scheduled full reconcile.

```sh
uv run manage.py ensure_index_current   # deploy + worker-startup: rebuild if config_version drifted
uv run manage.py procrastinate worker    # run the worker (single process)
```

Runbook knobs (env vars, see `bundesarchiv/index/settings.py`):

- `BUNDESARCHIV_CANONICAL_ROOT` — the canonical files-store the worker jobs re-read
  truth from (jobs carry only references, never payloads).
- `BUNDESARCHIV_RECONCILE_CRON` — the scheduled full-rebuild cadence (default `0 * * * *`,
  hourly; bounds worst-case staleness after any missed incremental update).
- Job-table hygiene: prune finished `procrastinate_jobs` rows periodically (the worker's
  `db_cleanup` periodic task / the `procrastinate` CLI). One index-writer advisory lock
  serializes every index writer (`indexer._INDEX_WRITER_LOCK_KEY`); do not reuse that key.

Status: greenfield. Building the persistence layer first — see [docs/plans/part-1-persistence.md](docs/plans/part-1-persistence.md).

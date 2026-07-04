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
to skip the `tests/index/` suite for domain-only work.

Status: greenfield. Building the persistence layer first — see [docs/plans/part-1-persistence.md](docs/plans/part-1-persistence.md).

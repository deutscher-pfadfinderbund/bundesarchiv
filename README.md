# DPB Bundesarchiv

The digital archive of the Deutscher Pfadfinderbund: photos, documents, audio and
video, with controlled visibility (public, all members, specific groups, or
archivists only).

## What you need

- Python 3.14 or newer
- [uv](https://docs.astral.sh/uv/) — installs everything else
- Apple's [`container`](https://github.com/apple/container) CLI (or Docker) — runs
  the search database

## Setup

```sh
uv sync   # install all dependencies
```

Start the search database (a Postgres with a German dictionary) and create its tables:

```sh
container build -t bundesarchiv-postgres docker/postgres/
container run -d --name bundesarchiv-pg -p 5434:5432 \
  -e POSTGRES_DB=bundesarchiv -e POSTGRES_PASSWORD=postgres bundesarchiv-postgres
uv run manage.py migrate
```

(With Docker instead: `docker compose up -d`, then `uv run manage.py migrate`.)

## Start the app

```sh
DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver
```

Open <http://localhost:8000>. To try the archive as different people, open
<http://localhost:8000/_dev/viewer/> and pick a role (archivist, member, public) —
this switcher exists only in development.

Optional, in a second terminal — the background worker (generates thumbnails,
retries failed index updates):

```sh
DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py procrastinate worker
```

## Tests

```sh
uv run pytest                          # full suite (needs the database from Setup)
BUNDESARCHIV_SKIP_PG=1 uv run pytest   # without a database (skips index + app tests)
pre-commit install                     # lint + type-check + tests on every commit
```

## Learn more

- [CONTEXT.md](CONTEXT.md) — what the domain words mean
- [docs/adr/](docs/adr/) — design decisions and why
- [docs/runbook.md](docs/runbook.md) — production/operations: media serving,
  thumbnails, the WebDAV mirror, worker and reconcile settings
- [docs/design/bundesarchiv-v1.md](docs/design/bundesarchiv-v1.md) — v1 design overview
- [docs/conventions.md](docs/conventions.md) — code conventions

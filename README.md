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

(With Docker instead: the same `build` and `run` commands with `docker` in place
of `container`. There is no dev compose file — `compose.yml` is the VPS stack.)

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

## Legacy import (local)

The old site's records are imported once, from a CSV export of its database plus
its media folder. `var/legacy/export_legacy.sh` is the script that made the
export; it is gitignored, like the export itself.

```sh
mise run legacy:import -- --dry-run   # reads everything, writes nothing, prints the report
mise run legacy:import                # writes the archive, then rebuilds the index
```

Read the dry run's report before the real one — the import runs once and the
source is deleted after it. It counts the Bestände, the records without a file,
the dates too free-form to read, the rows whose `date` text disagrees with the
`month`/`day` columns, the Medienarten and Dokumenttypen the edit form would
refuse to re-save, and the files it cannot find. The import refuses to run
twice, and it refuses a media path that is absent or holds not one of the
exported files. Its canonical root is its own (`var/legacy/canonical`), so the
dev archive's FILES are never touched. Point the app at the imported tree:

```sh
BUNDESARCHIV_CANONICAL_ROOT=var/legacy/canonical \
DJANGO_SETTINGS_MODULE=bundesarchiv.index.settings_dev uv run manage.py runserver
```

The search index is NOT isolated the same way: it is one Postgres table for
every canonical root, and the import rebuilds it from the imported tree. So keep
`BUNDESARCHIV_CANONICAL_ROOT=var/legacy/canonical` set while you browse — with
the default root you would search the legacy records and open dev ones. To hand
the index back to the dev archive (or to retry the import's own rebuild, which
the one-time refusal gives no second chance at):

```sh
uv run manage.py rebuild_index     # rebuilds from whatever BUNDESARCHIV_CANONICAL_ROOT points at
```

Both paths are overridable: `BUNDESARCHIV_LEGACY_MEDIA` for the media folder,
`BUNDESARCHIV_CANONICAL_ROOT` for where the archive lands.

## Tests

Tests run through [mise](https://mise.jdx.dev/) tasks; `mise.toml` is the single
source of what each one does.

```sh
mise run gate                # lint, types and the full suite (needs the database from Setup)
mise run check               # the fast subset: no database, no mypy
mise run test:nodb           # only the tests that run without a database
mise run test:db             # only the Postgres-backed tests
pre-commit install           # run the checks on every commit
```

## Learn more

- [CONTEXT.md](CONTEXT.md) — what the domain words mean
- [docs/adr/](docs/adr/) — design decisions and why
- [docs/runbook.md](docs/runbook.md) — production/operations: Keycloak login,
  media serving, thumbnails, the WebDAV mirror, worker and reconcile settings
- [docs/design/bundesarchiv-v1.md](docs/design/bundesarchiv-v1.md) — v1 design overview
- [docs/conventions.md](docs/conventions.md) — code conventions

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

Status: greenfield. Building the persistence layer first — see [docs/plans/part-1-persistence.md](docs/plans/part-1-persistence.md).

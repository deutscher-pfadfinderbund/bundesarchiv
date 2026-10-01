#!/bin/sh
# The `app` service's startup: bring the database and the derived index in step, then serve.
# The `worker` service overrides this command (compose.yml) — it must not migrate too.
set -eu

python manage.py migrate --noinput
python manage.py ensure_index_current

# ONE worker process (ADR 0013 single-app-process rule); concurrency is threads, and gthread is the
# right class for a fully synchronous WSGI app (ADR 0016). The timeout is generous because an
# archivist uploads scans measured in gigabytes. The config file sets the JSON error log and no
# access log (nginx keeps the one).
exec gunicorn bundesarchiv.index.wsgi:application \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 1 \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --config deploy/gunicorn.conf.py

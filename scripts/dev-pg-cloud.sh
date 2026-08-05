#!/bin/bash
# Idempotent Postgres bootstrap for sandboxes WITHOUT a container runtime (Claude Code on the
# web and similar). Local dev uses the container image instead (README); this script steps
# aside when a runtime is available. Safe to re-run any time — including mid-session when the
# sandbox reclaimed the server ("connection refused ... 5434" from the test guard).
#
# What it builds: the same thing docker/postgres/ builds — a Postgres with the German Hunspell
# dictionary installed as de_de.{affix,dict} — except from the distro Postgres (whatever major
# version the sandbox image ships) instead of the pinned 18.4 image. Good enough for tests;
# the pinned version is a VPS-deploy concern.
set -euo pipefail

PORT=5434
PGDATA=/var/lib/postgresql/bundesarchiv-pgdata

PGBIN=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)
if [ -z "$PGBIN" ]; then
    apt-get update -qq && apt-get install -y -qq postgresql hunspell-de-de
    PGBIN=$(ls -d /usr/lib/postgresql/*/bin | sort -V | tail -1)
fi

# Already serving? Done.
if "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PORT" -q 2>/dev/null; then
    echo "Postgres already serving on :$PORT"
    exit 0
fi

# A container runtime is the preferred path — don't shadow it with a local server.
if command -v container >/dev/null 2>&1 || docker info >/dev/null 2>&1; then
    echo "Container runtime available — start bundesarchiv-pg instead (see README)."
    exit 0
fi

# German Hunspell dictionary → Postgres tsearch_data (mirrors docker/postgres/Dockerfile).
if [ ! -f /usr/share/hunspell/de_DE.aff ]; then
    apt-get update -qq && apt-get install -y -qq hunspell-de-de
fi
SHAREDIR=$("$PGBIN/pg_config" --sharedir)
if [ ! -f "$SHAREDIR/tsearch_data/de_de.affix" ]; then
    cp /usr/share/hunspell/de_DE.aff "$SHAREDIR/tsearch_data/de_de.affix"
    cp /usr/share/hunspell/de_DE.dic "$SHAREDIR/tsearch_data/de_de.dict"
fi

as_postgres() {
    if [ "$(id -u)" = "0" ]; then su postgres -s /bin/bash -c "$1"; else bash -c "$1"; fi
}

if [ ! -f "$PGDATA/PG_VERSION" ]; then
    mkdir -p "$PGDATA"
    chown postgres:postgres "$PGDATA" 2>/dev/null || true
    PWFILE=$(mktemp)
    echo postgres > "$PWFILE"
    chmod 644 "$PWFILE"
    as_postgres "'$PGBIN/initdb' -D '$PGDATA' -U postgres --pwfile='$PWFILE' --locale=C.UTF-8" >/dev/null
    rm -f "$PWFILE"
fi

as_postgres "'$PGBIN/pg_ctl' -D '$PGDATA' -o '-p $PORT -k /tmp' -l '$PGDATA/log' start"

for _ in $(seq 1 20); do
    "$PGBIN/pg_isready" -h 127.0.0.1 -p "$PORT" -q && break
    sleep 0.5
done

PGPASSWORD=postgres "$PGBIN/createdb" -h 127.0.0.1 -p "$PORT" -U postgres bundesarchiv 2>/dev/null \
    || true  # already exists on re-runs
echo "Postgres serving on :$PORT (data: $PGDATA)"

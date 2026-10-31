# The app image: ghcr.io/deutscher-pfadfinderbund/bundesarchiv, built by
# .github/workflows/app-image.yml and run as both the `app` and the `worker` service (compose.yml).
#
# Two stages so the runtime carries no build tools, no uv and no uv cache. Everything stays exactly
# where the builder put it: the venv links to uv's Python under /python, and the settings derive
# STATICFILES_DIRS and the template dir from the package's own location on disk.

FROM debian:trixie-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# uv installs the Python that requires-python names: pyproject.toml is the one place for it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_CACHE_DIR=/root/.cache/uv/python

WORKDIR /app

# Dependencies first, keyed on the lockfile alone: a source-only change reuses this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# collectstatic runs at BUILD time (ADR 0016): WhiteNoise serves the hashed manifest at runtime, so
# the image must already contain it. It needs no database and no secrets.
ENV BUNDESARCHIV_STATIC_ROOT=/app/static
RUN /app/.venv/bin/python manage.py collectstatic --noinput --clear

FROM debian:trixie-slim AS runtime

# What python:*-slim used to bring: CA certificates for outgoing HTTPS, and /etc/services.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates netbase \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    BUNDESARCHIV_STATIC_ROOT=/app/static

# A fixed uid, because canonical/ and thumbnails/ arrive as host bind mounts: those folders have to
# be owned by this id for the app to write at all (docs/runbook.md, "Deploy"). /upload-staging is
# a named volume instead (compose.yml), which copies this folder's owner when Docker creates it.
RUN useradd --create-home --uid 1000 app \
    && install -d -o app -g app /upload-staging

WORKDIR /app
COPY --from=builder /python /python
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8000

CMD ["/app/deploy/entrypoint.sh"]

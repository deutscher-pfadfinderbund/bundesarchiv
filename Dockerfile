# The app image: ghcr.io/deutscher-pfadfinderbund/bundesarchiv, built by
# .github/workflows/app-image.yml and run as both the `app` and the `worker` service (compose.yml).
#
# Two stages so the runtime carries no build tools and no uv cache. The venv and the source tree
# both stay at /app in the runtime image, exactly where the builder put them: the settings derive
# STATICFILES_DIRS and the template dir from the package's own location on disk.

FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, keyed on the lockfile alone: a source-only change reuses this layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# collectstatic runs at BUILD time (ADR 0016): WhiteNoise serves the hashed manifest at runtime, so
# the image must already contain it. It needs no database and no secrets.
ENV BUNDESARCHIV_STATIC_ROOT=/app/static
RUN /app/.venv/bin/python manage.py collectstatic --noinput --clear

FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    BUNDESARCHIV_STATIC_ROOT=/app/static

# A fixed uid, because canonical/ and thumbnails/ arrive as host bind mounts: the deploy folder has
# to be owned by this id for the app to write at all (docs/runbook.md, "Deploy").
RUN useradd --create-home --uid 1000 app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

USER app
EXPOSE 8000

CMD ["/app/deploy/entrypoint.sh"]

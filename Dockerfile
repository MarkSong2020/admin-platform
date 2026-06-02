# syntax=docker/dockerfile:1.7

# ---- builder ----------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /uvx /usr/local/bin/

# Two-stage uv sync (v0.4.11+): install dependencies first against a stable
# pyproject.toml + uv.lock layer; copy the changing src/ tree afterwards and
# install the project itself. This keeps the heavy dep-resolution layer cached
# across src/ edits — CI image builds drop from minutes to seconds when only
# Python code changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime ----------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# tini is PID 1 — it reaps zombie processes (single-worker uvicorn doesn't
# fork, but any future shell-out / background subprocess would orphan
# otherwise) and forwards SIGTERM/SIGINT cleanly to the ASGI app for K8s
# graceful shutdown. `--no-install-recommends` keeps the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations

USER app

EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--"]
# uvicorn production flags (v0.4.14):
# --proxy-headers + --forwarded-allow-ips=*
#   K8s typically routes client → ingress → service. Without these, uvicorn
#   ignores X-Forwarded-{For,Proto} and request.client.host shows the ingress
#   IP / scheme defaults to http even when the public edge is https. The
#   wildcard is safe inside a pod because only ingress can reach this port.
# --no-access-log
#   We emit our own structured JSON access log via RequestIDMiddleware
#   (one record per request, with request_id / status / duration_ms). Leaving
#   uvicorn's default access log on produces a second redundant plain-text
#   line per request — doubles log volume and confuses aggregation.
CMD ["uvicorn", "admin_platform.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*", \
     "--no-access-log"]

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

# 本镜像是**生产产物**：默认激活 core.config 生产门禁（Settings._enforce_production_safety）。
# 缺 auth_enabled / 空 pepper / debug=true 等不安全配置时 startup 直接 fail-fast，不让脚手架默认值
# 裸奔到生产（Codex PK P1.1：门禁开关本身不能可漏配）。本地 dev / CI 不跑此镜像（host 直跑
# uvicorn / pytest，APP_ENVIRONMENT 未设 → 默认 local）；如需用本镜像跑非生产，显式覆盖
# APP_ENVIRONMENT=local。
ENV APP_ENVIRONMENT=production

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
# uvicorn proxy headers —— 默认不信任 X-Forwarded-*（PK 项1 安全收敛 2026-06-14）：
#   原 `--proxy-headers --forwarded-allow-ips=*` 让 uvicorn 无条件信任所有 peer 的 XFF、在请求到
#   应用前把 request.client.host 改写成客户端可控的 XFF 最左值，与应用层「直连 peer 不可伪造」的
#   审计 / 登录限流口径自相矛盾（可伪造 XFF 绕过 IP 维度撞库限流 / 污染审计 IP）。移除后
#   request.client.host = 真实直连 peer。
#   ⚠️ 上线前（client→ingress→service 拓扑）按实际可信代理重配，**绝不能用 wildcard**：
#     env FORWARDED_ALLOW_IPS=<ingress/proxy CIDR> + --proxy-headers，并接应用层统一 client-IP
#     resolver（trusted_proxy_cidrs，从右向左跳可信代理链）令审计 / login_guard 同口径。详见 NIGHT_LOG XFF 段。
# --no-access-log
#   We emit our own structured JSON access log via RequestIDMiddleware
#   (one record per request, with request_id / status / duration_ms). Leaving
#   uvicorn's default access log on produces a second redundant plain-text
#   line per request — doubles log volume and confuses aggregation.
CMD ["uvicorn", "admin_platform.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--no-access-log"]

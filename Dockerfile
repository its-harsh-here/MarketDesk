# syntax=docker/dockerfile:1
# Multi-stage build: compile the SPA, install pinned Python deps, ship a slim runtime.
# Base images can be overridden (e.g. a registry mirror) with --build-arg.
# Behind a TLS-intercepting proxy, pass its CA bundle as an optional build secret:
#   docker build --secret id=ca_bundle,src=/path/to/ca.crt .
ARG NODE_IMAGE=node:22-slim
ARG PYTHON_IMAGE=python:3.13-slim

# ---------------------------------------------------------------- web build
FROM ${NODE_IMAGE} AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; \
    npm ci --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------- python deps
FROM ${PYTHON_IMAGE} AS pydeps
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /src/apps/api
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir uv==0.11.32 && uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/api \
    MARKETDESK_ENV=production \
    DATA_PROVIDER=yahoo \
    DATA_DIR=/data \
    STATIC_DIR=/app/web \
    FIXTURES_DIR=/app/fixtures \
    STARTER_CONFIG_DIR=/app/config
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin marketdesk \
    && mkdir -p /data && chown marketdesk:marketdesk /data
COPY --from=pydeps /opt/venv /opt/venv
COPY apps/api/marketdesk /app/api/marketdesk
COPY apps/api/alembic /app/api/alembic
COPY apps/api/alembic.ini /app/api/alembic.ini
COPY fixtures /app/fixtures
COPY config /app/config
COPY --from=web /src/apps/web/dist /app/web
WORKDIR /app/api
# No VOLUME instruction: an anonymous volume would look like a disk but vanish with the container.
# Mount real persistent storage at /data (Compose named volume, Render disk, Fly volume).
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '8000'), timeout=3).status == 200 else 1)"]
# The entrypoint makes /data writable (platform disks mount root-owned) and drops to the unprivileged
# `marketdesk` user before running the command. Processes never run as root.
ENTRYPOINT ["python", "-m", "marketdesk.entrypoint"]
# Default: everything a single-container host needs — validate settings, migrate, then supervise one
# web server (on $PORT, default 8000) and one alert worker. Docker Compose overrides this per service.
CMD ["python", "-m", "marketdesk.serve"]

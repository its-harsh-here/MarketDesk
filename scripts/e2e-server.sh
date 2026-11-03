#!/usr/bin/env bash
# Starts a fresh fixture-mode MarketDesk (API serving the built SPA + alert worker) for Playwright.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA=${E2E_DATA_DIR:-$(mktemp -d -t marketdesk-e2e-XXXXXX)}
export DATA_DIR="$DATA" DATA_PROVIDER=fixture MARKETDESK_ENV=development DEV_AUTH_BYPASS=true
export ALERT_POLL_SECONDS=${ALERT_POLL_SECONDS:-2} WORKER_HEARTBEAT_STALE_SECONDS=60
PORT=${PORT:-8100}
cd "$ROOT/apps/api"
test -f "$ROOT/apps/web/dist/index.html" || { echo "Build the web app first: (cd apps/web && npm run build)" >&2; exit 1; }
uv run --quiet marketdesk migrate
uv run --quiet python -m marketdesk.worker &
WORKER=$!
uv run --quiet uvicorn marketdesk.main:app --host 127.0.0.1 --port "$PORT" &
WEB=$!
cleanup() { kill "$WORKER" "$WEB" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait -n "$WORKER" "$WEB"

#!/usr/bin/env bash
# Starts a fresh fixture-mode MarketDesk (API serving the built SPA + alert worker) for Playwright.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA=${E2E_DATA_DIR:-$(mktemp -d -t marketdesk-e2e-XXXXXX)}
# Deterministic journeys: never use real keys that happen to be in the shell.
unset FRED_API_KEY ALPACA_API_KEY_ID ALPACA_API_SECRET_KEY FINRA_CLIENT_ID FINRA_CLIENT_SECRET SEC_USER_AGENT XAI_API_KEY GROQ_API_KEY
export DATA_DIR="$DATA" DATA_PROVIDER=fixture MARKETDESK_ENV=development DEV_AUTH_BYPASS=true
export ALERT_POLL_SECONDS=${ALERT_POLL_SECONDS:-2} WORKER_HEARTBEAT_STALE_SECONDS=60
PORT=${PORT:-8100}
cd "$ROOT/apps/api"
test -f "$ROOT/apps/web/dist/index.html" || { echo "Build the web app first: (cd apps/web && npm run build)" >&2; exit 1; }
uv run --quiet marketdesk migrate
# AI research runs against a local fake provider endpoint (no key, no network, no cost). The key's gsk_ prefix
# selects the Groq path, as in production.
XAI_PORT=$((PORT + 50))
python3 "$ROOT/scripts/fake_xai.py" "$XAI_PORT" &
FAKE_XAI=$!
export GROK_API=gsk_e2e_fake_key GROQ_BASE_URL="http://127.0.0.1:$XAI_PORT/openai/v1" \
  XAI_BASE_URL="http://127.0.0.1:$XAI_PORT/v1"
uv run --quiet python -m marketdesk.worker &
WORKER=$!
uv run --quiet uvicorn marketdesk.main:app --host 127.0.0.1 --port "$PORT" &
WEB=$!
cleanup() { kill "$WORKER" "$WEB" "$FAKE_XAI" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
wait -n "$WORKER" "$WEB"

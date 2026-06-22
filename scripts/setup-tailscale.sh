#!/usr/bin/env bash
# Expose whisper-relay on the tailnet. Run after uvicorn is listening locally.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "${DEPLOY_ENV_FILE:-$ROOT/.env}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${DEPLOY_ENV_FILE:-$ROOT/.env}"
  set +a
fi

PORT="${VOICE_GATEWAY_PORT:-9788}"
HTTP_PORT="${TAILNET_HTTP_PORT:-8888}"
BACKEND="http://127.0.0.1:${PORT}"

# HTTPS on 443 — required for phone microphone (use TAILNET_HTTPS_URL from .env)
tailscale serve --bg "${BACKEND}"

# Plain HTTP on TAILNET_HTTP_PORT — page loads only; mic still needs HTTPS above
tailscale serve --bg --http="${HTTP_PORT}" "${BACKEND}"

echo "whisper-relay tailnet URLs:"
if [[ -n "${TAILNET_HTTPS_URL:-}" ]]; then
  echo "  HTTPS (mic): ${TAILNET_HTTPS_URL}"
  if [[ -n "${TAILNET_HTTP_PORT:-}" ]]; then
    host="${TAILNET_HTTPS_URL#https://}"
    echo "  HTTP (no mic): http://${host}:${HTTP_PORT}"
  fi
fi
tailscale serve status

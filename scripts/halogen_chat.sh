#!/usr/bin/env bash
# Manage Open WebUI and its stable OpenAI adapter, never the model backend.
# All backends must use API_HOST:API_PORT. No model ID is needed.
set -euo pipefail

REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
LAUNCHER=$REPO_DIR/scripts/halogen_open_webui.py
ENGINE=${ENGINE:-docker}
API_HOST=${API_HOST:-127.0.0.1}
API_PORT=${API_PORT:-8731}
WAIT_SECONDS=${WAIT_SECONDS:-900}
TAIL=${TAIL:-60}
PYTHON=${PYTHON:-python3}

action=${1:-up}
if [[ $# -gt 0 ]]; then
  shift
fi
case "$action" in
  -h | --help | help)
    cat <<'USAGE'
Usage: halogen_chat.sh [up|restart|down|ready|status|logs|urls|preview] [launcher options]

up/restart wait for any single loaded model, then launch UI and OpenAI adapter.
down stops both front-end containers, preserving accounts, chats, and model files.
ready checks the upstream OpenAI models listing without starting anything.
Client: http://10.0.0.170:8081/v1, model local-model, existing Open WebUI API key.
UI: http://10.0.0.170:8080. Underlying server: http://127.0.0.1:8731/v1.

Environment: ENGINE, API_HOST, API_PORT, WAIT_SECONDS, TAIL, ALLOW_SIGNUP,
UPSTREAM_API_KEY (only if backend requires authentication), PYTHON, DRY_RUN.
Extra options override environment defaults for both readiness and startup.
USAGE
    exit 0
    ;;
  up | restart | down | ready | status | logs | urls | preview) ;;
  *) echo "Unknown command: $action" >&2; exit 2 ;;
esac

flags=(--engine "$ENGINE" --api-host "$API_HOST" --api-port "$API_PORT"
       --wait-seconds "$WAIT_SECONDS" --tail "$TAIL")
if [[ ${ALLOW_SIGNUP:-0} != 1 ]]; then
  flags+=(--no-signup)
fi
if [[ ${DRY_RUN:-0} == 1 ]]; then
  printf 'DRY_RUN:'
  printf ' %q' "$PYTHON" "$LAUNCHER" "$action" "${flags[@]}" "$@"
  printf '\n'
  exit 0
fi
exec "$PYTHON" "$LAUNCHER" "$action" "${flags[@]}" "$@"

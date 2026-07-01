#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
BASE_URL="${BASE_URL:-http://${HOST}:${PORT}}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
APP_MODULE="${APP_MODULE:-ainulindale_api.main:app}"

# Important for src-layout repos when the project has not been installed
# editable into the venv.
export PYTHONPATH="${PYTHONPATH:-${repo_root}/src}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

mkdir -p .artifacts
log_file=".artifacts/smoke-local.log"
: > "$log_file"

"$PYTHON_BIN" -m uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT" >"$log_file" 2>&1 &
server_pid="$!"

cleanup() {
  if kill -0 "$server_pid" >/dev/null 2>&1; then
    kill "$server_pid" >/dev/null 2>&1 || true
    wait "$server_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

for _ in $(seq 1 50); do
  if curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1; then
    BASE_URL="$BASE_URL" scripts/smoke-url.sh
    echo "smoke-local passed"
    exit 0
  fi

  if ! kill -0 "$server_pid" >/dev/null 2>&1; then
    echo "Local server exited before becoming ready. Log follows:" >&2
    cat "$log_file" >&2
    exit 1
  fi

  sleep 0.1
done

echo "Timed out waiting for local server. Log follows:" >&2
cat "$log_file" >&2
exit 1

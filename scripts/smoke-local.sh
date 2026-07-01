#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8000}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT}}"
START_SERVER="${START_SERVER:-1}"

tmpdir="$(mktemp -d)"
server_pid=""
server_log="${tmpdir}/uvicorn.log"

cleanup() {
  if [[ -n "${server_pid}" ]]; then
    kill "${server_pid}" >/dev/null 2>&1 || true
    wait "${server_pid}" >/dev/null 2>&1 || true
  fi
  rm -rf "${tmpdir}"
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  if [[ -f "${server_log}" ]]; then
    echo "--- uvicorn log ---" >&2
    cat "${server_log}" >&2 || true
  fi
  exit 1
}

check_json_request() {
  local name="$1"
  local expected_status="$2"
  shift 2

  local body="${tmpdir}/${name}.body"
  local headers="${tmpdir}/${name}.headers"
  local status_code

  status_code="$(curl -sS -o "${body}" -D "${headers}" -w '%{http_code}' "$@")"

  if [[ "${status_code}" != "${expected_status}" ]]; then
    echo "--- response headers for ${name} ---" >&2
    cat "${headers}" >&2 || true
    echo "--- response body for ${name} ---" >&2
    cat "${body}" >&2 || true
    fail "${name}: expected HTTP ${expected_status}, got HTTP ${status_code}"
  fi

  if ! grep -qi '^content-type: application/json' "${headers}"; then
    echo "--- response headers for ${name} ---" >&2
    cat "${headers}" >&2 || true
    fail "${name}: response Content-Type was not application/json"
  fi

  jq -e . "${body}" >/dev/null || {
    echo "--- response body for ${name} ---" >&2
    cat "${body}" >&2 || true
    fail "${name}: response body was not valid JSON"
  }

  echo "ok - ${name}"
}

if [[ "${START_SERVER}" == "1" ]]; then
  .venv/bin/python -m uvicorn ainulindale_api.main:app \
    --host 127.0.0.1 \
    --port "${PORT}" \
    >"${server_log}" 2>&1 &

  server_pid="$!"

  ready=0
  for _ in $(seq 1 50); do
    if curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1; then
      ready=1
      break
    fi

    if ! kill -0 "${server_pid}" >/dev/null 2>&1; then
      break
    fi

    sleep 0.2
  done

  if [[ "${ready}" != "1" ]]; then
    fail "server did not become ready at ${BASE_URL}"
  fi
fi

check_json_request \
  healthz \
  200 \
  "${BASE_URL}/healthz"

check_json_request \
  readyz \
  200 \
  "${BASE_URL}/readyz"

check_json_request \
  echo_json \
  200 \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-binary '{"message":"hello"}' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  echo_json_with_charset \
  200 \
  -X POST \
  -H 'Content-Type: application/json; charset=utf-8' \
  --data-binary '{"message":"hello"}' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  invalid_json \
  422 \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-binary '{"message":' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  missing_content_type \
  415 \
  -X POST \
  -H 'Content-Type:' \
  --data-binary '{"message":"hello"}' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  wrong_content_type \
  415 \
  -X POST \
  -H 'Content-Type: text/plain' \
  --data-binary '{"message":"hello"}' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  validation_error \
  422 \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-binary '{"message":""}' \
  "${BASE_URL}/api/v1/echo"

check_json_request \
  not_found \
  404 \
  "${BASE_URL}/api/v1/does-not-exist"

check_json_request \
  root_not_found \
  404 \
  "${BASE_URL}/"

check_json_request \
  openapi \
  200 \
  "${BASE_URL}/openapi.json"

openapi_body="${tmpdir}/openapi.body"
curl -fsS "${BASE_URL}/openapi.json" -o "${openapi_body}"

jq -e '
  (.paths | keys | sort) == ["/api/v1/echo", "/healthz", "/readyz"]
' "${openapi_body}" >/dev/null || fail "OpenAPI paths are not exactly the intended set"

jq -e '
  (.paths["/api/v1/echo"] | keys | sort) == ["post"]
' "${openapi_body}" >/dev/null || fail "OpenAPI does not advertise exactly POST for /api/v1/echo"

echo "ok - openapi intended paths only"
echo "smoke-local passed"

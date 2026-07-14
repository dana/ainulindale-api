#!/usr/bin/env bash
set -Eeuo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
API_ECHO_PATH="${API_ECHO_PATH:-/api/v1/echo}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

pass() {
  printf 'ok - %s\n' "$1"
}

fail() {
  printf 'not ok - %s\n' "$1" >&2
  exit 1
}

request() {
  local name="$1"
  local method="$2"
  local path="$3"
  local body="${4:-}"
  local content_type="${5:-}"

  local headers="$tmpdir/${name}.headers"
  local output="$tmpdir/${name}.body"
  local url="${BASE_URL}${path}"

  if [[ -n "$body" && -n "$content_type" ]]; then
    curl -sS \
      -X "$method" \
      -H "Content-Type: ${content_type}" \
      -D "$headers" \
      -o "$output" \
      -w '%{http_code}' \
      --data "$body" \
      "$url"
  elif [[ -n "$body" ]]; then
    curl -sS \
      -X "$method" \
      -D "$headers" \
      -o "$output" \
      -w '%{http_code}' \
      --data "$body" \
      "$url"
  else
    curl -sS \
      -X "$method" \
      -D "$headers" \
      -o "$output" \
      -w '%{http_code}' \
      "$url"
  fi
}

assert_json_content_type() {
  local name="$1"
  local headers="$tmpdir/${name}.headers"

  grep -qi '^content-type: application/json' "$headers" \
    || fail "${name} response was not application/json"
}

assert_json_body() {
  local name="$1"
  local output="$tmpdir/${name}.body"

  python3 -m json.tool "$output" >/dev/null \
    || fail "${name} response body was not valid JSON"
}

assert_status() {
  local name="$1"
  local actual="$2"
  local expected="$3"

  [[ "$actual" == "$expected" ]] \
    || fail "${name} expected HTTP ${expected}, got HTTP ${actual}"
}

assert_4xx() {
  local name="$1"
  local actual="$2"

  [[ "$actual" =~ ^4[0-9][0-9]$ ]] \
    || fail "${name} expected a 4xx response, got HTTP ${actual}"
}

code="$(request healthz GET /healthz)"
assert_status healthz "$code" 200
assert_json_content_type healthz
assert_json_body healthz
pass healthz

code="$(request readyz GET /readyz)"
assert_status readyz "$code" 200
assert_json_content_type readyz
assert_json_body readyz
pass readyz

code="$(request echo_json POST "$API_ECHO_PATH" '{"message":"hello from container smoke"}' 'application/json')"
assert_status echo_json "$code" 200
assert_json_content_type echo_json
assert_json_body echo_json
pass echo_json

code="$(request echo_json_with_charset POST "$API_ECHO_PATH" '{"message":"hello with charset"}' 'application/json; charset=utf-8')"
assert_status echo_json_with_charset "$code" 200
assert_json_content_type echo_json_with_charset
assert_json_body echo_json_with_charset
pass echo_json_with_charset

code="$(request invalid_json POST "$API_ECHO_PATH" '{"message":' 'application/json')"
assert_4xx invalid_json "$code"
assert_json_content_type invalid_json
assert_json_body invalid_json
pass invalid_json

code="$(request missing_content_type POST "$API_ECHO_PATH" '{"message":"missing content type"}')"
assert_4xx missing_content_type "$code"
assert_json_content_type missing_content_type
assert_json_body missing_content_type
pass missing_content_type

code="$(request wrong_content_type POST "$API_ECHO_PATH" '{"message":"wrong content type"}' 'text/plain')"
assert_4xx wrong_content_type "$code"
assert_json_content_type wrong_content_type
assert_json_body wrong_content_type
pass wrong_content_type

code="$(request validation_error POST "$API_ECHO_PATH" '{"not_message":"bad"}' 'application/json')"
assert_4xx validation_error "$code"
assert_json_content_type validation_error
assert_json_body validation_error
pass validation_error

code="$(request not_found GET /api/v1/does-not-exist)"
assert_status not_found "$code" 404
assert_json_content_type not_found
assert_json_body not_found
pass not_found

code="$(request root_not_found GET /)"
assert_status root_not_found "$code" 404
assert_json_content_type root_not_found
assert_json_body root_not_found
pass root_not_found

code="$(request happy GET /api/v1/happy)"
assert_status happy "$code" 200
assert_json_content_type happy
assert_json_body happy
pass happy

code="$(request openapi GET /openapi.json)"
assert_status openapi "$code" 200
assert_json_content_type openapi
assert_json_body openapi
pass openapi

python3 - "$tmpdir/openapi.body" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as handle:
    spec = json.load(handle)

paths = set(spec.get("paths", {}))
required = {"/healthz", "/readyz", "/api/v1/echo", "/api/v1/happy-path", "/api/v1/happy"}
missing = required - paths

if missing:
    raise SystemExit(f"OpenAPI missing expected paths: {sorted(missing)}")

unexpected_public = [
    path for path in paths
    if path.startswith("/api/") and not path.startswith("/api/v1/")
]

if unexpected_public:
    raise SystemExit(f"OpenAPI exposes unexpected public API paths: {unexpected_public}")
PY
pass "openapi intended paths only"

code="$(request eridian_echo_page GET /eridian-echo/)"
assert_status eridian_echo_page "$code" 200
pass eridian_echo_page

code="$(request eridian_echo_css GET /assets/eridian-echo/eridian-echo.css)"
assert_status eridian_echo_css "$code" 200
pass eridian_echo_css

echo "smoke-url passed for ${BASE_URL}"

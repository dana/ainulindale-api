#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mkdir -p .artifacts/container-smoke

PORT="${PORT:-18080}"
IMAGE_REPO="${IMAGE_REPO:-localhost/ainulindale-api}"
FULL_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${FULL_SHA:0:12}"
IMAGE_TAG="${IMAGE_TAG:-local-${SHORT_SHA}}"
IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"
CONTAINER_NAME="${CONTAINER_NAME:-ainulindale-api-smoke-${SHORT_SHA}}"

echo "Building local image..."
IMAGE="$(scripts/build-image-local.sh | tail -n 1)"
echo "Built image: ${IMAGE}"

podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "Starting container ${CONTAINER_NAME} on 127.0.0.1:${PORT}..."
podman run \
  --detach \
  --name "$CONTAINER_NAME" \
  --publish "127.0.0.1:${PORT}:8000" \
  "$IMAGE" \
  > .artifacts/container-smoke/container-id.txt

cleanup() {
  podman rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

BASE_URL="http://127.0.0.1:${PORT}"

for _ in $(seq 1 100); do
  if curl -fsS "${BASE_URL}/healthz" >/dev/null 2>&1; then
    break
  fi

  state="$(podman inspect -f '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || true)"
  if [[ "$state" == "exited" || "$state" == "dead" ]]; then
    echo "Container exited before becoming ready. Logs follow:" >&2
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
  fi

  sleep 0.1
done

curl -fsS "${BASE_URL}/healthz" >/dev/null

BASE_URL="$BASE_URL" scripts/smoke-url.sh

podman inspect "$CONTAINER_NAME" > .artifacts/container-smoke/container-inspect-running.json

jq -e '.[0].Mounts | length == 0' .artifacts/container-smoke/container-inspect-running.json >/dev/null \
  || {
    echo "Container unexpectedly has host mounts:" >&2
    jq '.[0].Mounts' .artifacts/container-smoke/container-inspect-running.json >&2
    exit 1
  }

echo "ok - container started without host mounts"

echo "Stopping container with SIGTERM via podman stop..."
podman stop --time 10 "$CONTAINER_NAME" >/dev/null

podman inspect "$CONTAINER_NAME" > .artifacts/container-smoke/container-inspect-stopped.json

status="$(jq -r '.[0].State.Status' .artifacts/container-smoke/container-inspect-stopped.json)"
exit_code="$(jq -r '.[0].State.ExitCode' .artifacts/container-smoke/container-inspect-stopped.json)"
oom_killed="$(jq -r '.[0].State.OOMKilled' .artifacts/container-smoke/container-inspect-stopped.json)"

[[ "$status" == "exited" ]] || {
  echo "Expected stopped container status to be exited, got ${status}" >&2
  exit 1
}

[[ "$oom_killed" == "false" ]] || {
  echo "Container was OOM killed" >&2
  exit 1
}

case "$exit_code" in
  0|143)
    echo "ok - container exited after SIGTERM with exit code ${exit_code}"
    ;;
  *)
    echo "Unexpected container exit code after SIGTERM: ${exit_code}" >&2
    podman logs "$CONTAINER_NAME" >&2 || true
    exit 1
    ;;
esac

podman rm "$CONTAINER_NAME" >/dev/null
trap - EXIT

echo "container-smoke passed"

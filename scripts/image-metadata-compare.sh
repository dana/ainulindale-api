#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

mkdir -p .artifacts/container-image

IMAGE_REPO="${IMAGE_REPO:-localhost/ainulindale-api}"
FULL_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${FULL_SHA:0:12}"

IMAGE_A="${IMAGE_REPO}:metadata-${SHORT_SHA}-a"
IMAGE_B="${IMAGE_REPO}:metadata-${SHORT_SHA}-b"

SOURCE_URL="$(git config --get remote.origin.url || true)"

buildah bud \
  --format oci \
  --pull=missing \
  --label "org.opencontainers.image.title=ainulindale-api" \
  --label "org.opencontainers.image.source=${SOURCE_URL}" \
  --label "org.opencontainers.image.revision=${FULL_SHA}" \
  --label "org.opencontainers.image.created=local-build" \
  -f Containerfile \
  -t "$IMAGE_A" \
  .

buildah bud \
  --format oci \
  --pull=missing \
  --label "org.opencontainers.image.title=ainulindale-api" \
  --label "org.opencontainers.image.source=${SOURCE_URL}" \
  --label "org.opencontainers.image.revision=${FULL_SHA}" \
  --label "org.opencontainers.image.created=local-build" \
  -f Containerfile \
  -t "$IMAGE_B" \
  .

stable_metadata() {
  local image="$1"

  buildah inspect --type image "$image" | jq -S '
    {
      os: (.OCIv1.os // .Docker.os // null),
      architecture: (.OCIv1.architecture // .Docker.architecture // null),
      user: (.OCIv1.config.User // .Docker.Config.User // null),
      working_dir: (.OCIv1.config.WorkingDir // .Docker.Config.WorkingDir // null),
      exposed_ports: (.OCIv1.config.ExposedPorts // .Docker.Config.ExposedPorts // null),
      entrypoint: (.OCIv1.config.Entrypoint // .Docker.Config.Entrypoint // null),
      cmd: (.OCIv1.config.Cmd // .Docker.Config.Cmd // null),
      labels: (.OCIv1.config.Labels // .Docker.Config.Labels // null)
    }
  '
}

stable_metadata "$IMAGE_A" > .artifacts/container-image/metadata-a.json
stable_metadata "$IMAGE_B" > .artifacts/container-image/metadata-b.json

diff -u \
  .artifacts/container-image/metadata-a.json \
  .artifacts/container-image/metadata-b.json

echo "image metadata comparison passed"
echo "image A: $IMAGE_A"
echo "image B: $IMAGE_B"

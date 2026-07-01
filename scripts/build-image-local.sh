#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

IMAGE_REPO="${IMAGE_REPO:-localhost/ainulindale-api}"
FULL_SHA="$(git rev-parse HEAD)"
SHORT_SHA="${FULL_SHA:0:12}"
IMAGE_TAG="${IMAGE_TAG:-local-${SHORT_SHA}}"
IMAGE="${IMAGE_REPO}:${IMAGE_TAG}"

SOURCE_URL="$(git config --get remote.origin.url || true)"

buildah bud \
  --format oci \
  --pull=missing \
  --label "org.opencontainers.image.title=ainulindale-api" \
  --label "org.opencontainers.image.source=${SOURCE_URL}" \
  --label "org.opencontainers.image.revision=${FULL_SHA}" \
  --label "org.opencontainers.image.created=local-build" \
  -f Containerfile \
  -t "$IMAGE" \
  .

echo "$IMAGE"

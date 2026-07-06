#!/usr/bin/env bash
set -Eeuo pipefail

HEAD_SHA="${1:-}"

if ! [[ "$HEAD_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <40-char-pr-head-sha>" >&2
  exit 2
fi

BASE_URL="${BASE_URL:-https://diederich.ai}"
OUT_DIR="${OUT_DIR:-/tmp/chunk11-audit-${HEAD_SHA}}"
KUBECTL="${KUBECTL:-kubectl}"

mkdir -p "$OUT_DIR"

echo "Collecting Chunk 11 audit evidence in $OUT_DIR"

docker manifest inspect "ghcr.io/dana/ainulindale-api:${HEAD_SHA}" \
  > "$OUT_DIR/ghcr-manifest.json"

"$KUBECTL" -n argocd get application.argoproj.io ainulindale-api -o json \
  > "$OUT_DIR/argocd-application.json"

"$KUBECTL" -n ainulindale-api get deployment ainulindale-api -o json \
  > "$OUT_DIR/k8s-deployment.json"

"$KUBECTL" -n ainulindale-api get pods -l app.kubernetes.io/name=ainulindale-api -o wide \
  > "$OUT_DIR/k8s-pods.txt"

curl -fsS \
  -H 'Content-Type: application/json' \
  --data '{"message":"chunk 11 audit"}' \
  "${BASE_URL}/api/v1/happy-path" \
  | jq . \
  > "$OUT_DIR/public-happy-path.json"

running_image="$(
  jq -r '.spec.template.spec.containers[] | select(.name=="ainulindale-api") | .image' \
    "$OUT_DIR/k8s-deployment.json"
)"

argo_sync="$(jq -r '.status.sync.status' "$OUT_DIR/argocd-application.json")"
argo_health="$(jq -r '.status.health.status' "$OUT_DIR/argocd-application.json")"
argo_revision="$(jq -r '.status.sync.revision' "$OUT_DIR/argocd-application.json")"

cat > "$OUT_DIR/summary.txt" <<EOF
Chunk 11 audit summary
======================
Expected PR head SHA: ${HEAD_SHA}
Expected image: ghcr.io/dana/ainulindale-api:${HEAD_SHA}
Running image: ${running_image}
Argo CD sync: ${argo_sync}
Argo CD health: ${argo_health}
Argo CD revision: ${argo_revision}
Public endpoint response:
$(cat "$OUT_DIR/public-happy-path.json")
EOF

cat "$OUT_DIR/summary.txt"

test "$running_image" = "ghcr.io/dana/ainulindale-api:${HEAD_SHA}"
test "$argo_sync" = "Synced"
test "$argo_health" = "Healthy"

echo "PASS: Chunk 11 audit evidence is internally consistent"

#!/usr/bin/env bash
set -euo pipefail

workflow=".github/workflows/pr-ci.yml"

test -s "$workflow"

grep -q '^name: PR CI$' "$workflow"
grep -q '^  pull_request:$' "$workflow"
grep -q '^    branches:$' "$workflow"
grep -q '^      - main$' "$workflow"
grep -q '^    types:$' "$workflow"
grep -q '^      - opened$' "$workflow"
grep -q '^      - synchronize$' "$workflow"
grep -q '^      - reopened$' "$workflow"
grep -q '^permissions: {}$' "$workflow"
grep -q '^  quality-gate:$' "$workflow"
grep -q '^    name: quality-gate$' "$workflow"
grep -q '^    runs-on: arc-ainulindale-api$' "$workflow"
grep -q '^      contents: read$' "$workflow"
grep -q '^  build-and-push:$' "$workflow"
grep -q '^    name: build-and-push$' "$workflow"
grep -q '^    needs: quality-gate$' "$workflow"
grep -q '^      packages: write$' "$workflow"
grep -q 'github.event.pull_request.head.sha' "$workflow"
grep -q 'github.event.pull_request.head.repo.full_name == github.repository' "$workflow"
grep -q 'scripts/quality-gate.sh' "$workflow"
grep -q 'BUILDAH_ARGS' "$workflow"
grep -q -- '--storage-driver=vfs' "$workflow"
grep -q -- '--isolation=chroot' "$workflow"
grep -q 'buildah "${BUILDAH_ARGS\[@\]}" bud' "$workflow"
grep -q 'buildah "${BUILDAH_ARGS\[@\]}" push' "$workflow"
grep -q 'GHCR_TOKEN: \${{ github.token }}' "$workflow"

if grep -q 'pull_request_target' "$workflow"; then
  echo "FAIL: pull_request_target must not be used" >&2
  exit 1
fi

if grep -qE '\bworkflow_run\b|\bworkflow_dispatch\b' "$workflow"; then
  echo "FAIL: this workflow must not use privileged chaining or manual dispatch" >&2
  exit 1
fi

if grep -q 'secrets\.' "$workflow"; then
  echo "FAIL: do not reference user-defined secrets; use github.token only" >&2
  exit 1
fi

if grep -qE 'INFRA|infra|PAT|TOKEN_FOR_INFRA|kubeconfig|KUBECONFIG|kubectl|argocd|ARGO|kubeseal|SEALED|sealed-secrets|private[ _-]?key' "$workflow"; then
  echo "FAIL: workflow appears to reference deployment handoff or deployment secret material" >&2
  exit 1
fi

if grep -qE 'toJson\(|GITHUB_CONTEXT|cat .*GITHUB_EVENT_PATH|printenv|set -x' "$workflow"; then
  echo "FAIL: workflow appears to dump contexts, environment, or shell traces" >&2
  exit 1
fi

quality_line="$(grep -n '^  quality-gate:$' "$workflow" | cut -d: -f1 | head -n1)"
build_line="$(grep -n '^  build-and-push:$' "$workflow" | cut -d: -f1 | head -n1)"

if [ "$quality_line" -ge "$build_line" ]; then
  echo "FAIL: quality-gate must appear before build-and-push" >&2
  exit 1
fi

if awk '/^  quality-gate:/{in_quality=1; next} /^  build-and-push:/{in_quality=0} in_quality && /packages: write/{found=1} END{exit found ? 0 : 1}' "$workflow"; then
  echo "FAIL: quality-gate must not have packages: write" >&2
  exit 1
fi

echo "PASS: PR CI workflow is pull_request-only, same-repo gated, quality-before-image, GHCR-only, and deployment-secret-free."

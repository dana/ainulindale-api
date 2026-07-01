#!/usr/bin/env bash
set -euo pipefail

workflow=".github/workflows/arc-runner-proof.yml"

test -s "$workflow"

grep -q '^name: ARC Runner Proof$' "$workflow"
grep -q '^  pull_request:$' "$workflow"
grep -q 'runs-on: arc-ainulindale-api' "$workflow"
grep -q 'permissions: {}' "$workflow"

if grep -q 'pull_request_target' "$workflow"; then
  echo "FAIL: pull_request_target must not be used in this chunk" >&2
  exit 1
fi

if grep -q 'secrets\.' "$workflow"; then
  echo "FAIL: workflow must not reference repository secrets" >&2
  exit 1
fi

if grep -q 'actions/checkout' "$workflow"; then
  echo "FAIL: harmless ARC proof should not check out PR code" >&2
  exit 1
fi

if grep -qE 'pytest|ruff|bandit|pip-audit|buildah|podman|docker|ghcr|kubectl|kubeconfig|argocd|kubeseal' "$workflow"; then
  echo "FAIL: workflow contains work reserved for later chunks" >&2
  exit 1
fi

echo "PASS: ARC proof workflow is PR-only, harmless, and secret-free."

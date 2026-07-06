#!/usr/bin/env bash
set -euo pipefail

workflow=".github/workflows/merged-pr-deployment-handoff.yml"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

test -s "$workflow" || fail "missing or empty $workflow"

grep -q '^name: Merged PR Deployment Handoff$' "$workflow"
grep -q '^  pull_request:$' "$workflow"
grep -q '^    branches:$' "$workflow"
grep -q '^      - main$' "$workflow"
grep -q '^    types:$' "$workflow"
grep -q '^      - closed$' "$workflow"
grep -q '^permissions: {}$' "$workflow"

grep -q '^  deployment-handoff:$' "$workflow"
grep -q '^    name: deployment-handoff$' "$workflow"
grep -q 'github.event.pull_request.merged == true' "$workflow"
grep -q 'github.event.pull_request.head.repo.full_name == github.repository' "$workflow"
grep -q '^    runs-on: arc-ainulindale-api$' "$workflow"
grep -q '^      contents: read$' "$workflow"
grep -q '^      packages: write$' "$workflow"

grep -q 'HEAD_SHA: \${{ github.event.pull_request.head.sha }}' "$workflow"
grep -q 'INFRA_REPO: dana/ainulindale-infra' "$workflow"
grep -q 'INFRA_PATH: apps/ainulindale-api/overlays/prod' "$workflow"

grep -q 'skopeo login' "$workflow"
grep -q 'skopeo inspect' "$workflow"
grep -q 'skopeo copy' "$workflow"
grep -q 'docker://.*:main' "$workflow"
grep -q 'kustomize edit set image' "$workflow"
grep -q 'ghcr.io/dana/ainulindale-api.*HEAD_SHA' "$workflow"
grep -q 'git clone --depth 1 --branch main' "$workflow"
grep -q 'git push origin "HEAD:refs/heads/${deploy_branch}"' "$workflow"
grep -q 'api.github.com/repos/${INFRA_REPO}' "$workflow"
grep -q '/pulls' "$workflow"
grep -q '/merge' "$workflow"
grep -q 'secrets.AINULINDALE_INFRA_DEPLOY_TOKEN' "$workflow"

# Forbid dangerous or unintended GitHub Actions triggers.
# This intentionally checks for YAML trigger keys only, not words inside shell commands.
if grep -nE '^[[:space:]]*(pull_request_target|workflow_run|workflow_dispatch|push):[[:space:]]*($|#)' "$workflow"; then
  fail "workflow must use only pull_request closed, not pull_request_target/workflow_run/workflow_dispatch/push triggers"
fi

if grep -qE '\bkubectl\b|\bKUBECONFIG\b|\bargocd\b|ARGOCD|kubeseal|SEALED|sealed-secrets|PRIVATE KEY|private[ _-]?key' "$workflow"; then
  fail "workflow appears to reference cluster, Argo CD, kubeconfig, kubeseal, or private key material"
fi

if grep -qE 'toJson\(|GITHUB_CONTEXT|cat .*GITHUB_EVENT_PATH|printenv|set -x' "$workflow"; then
  fail "workflow appears to dump contexts, environment, event payload, or shell traces"
fi

secret_refs="$(
  grep -Roh 'secrets\.[A-Za-z0-9_]*' .github/workflows 2>/dev/null \
    | sort -u \
    || true
)"

if [ "$secret_refs" != "secrets.AINULINDALE_INFRA_DEPLOY_TOKEN" ]; then
  echo "Observed secret references:" >&2
  printf '%s\n' "$secret_refs" >&2
  fail "unexpected secret references found"
fi

if grep -R -n 'AINULINDALE_INFRA_DEPLOY_TOKEN' .github/workflows \
  | grep -v '.github/workflows/merged-pr-deployment-handoff.yml:'; then
  fail "infra deploy token is referenced outside Workflow 2"
fi

echo "PASS: merged PR deployment handoff workflow is pull_request-closed, merge-gated, same-repo-gated, Skopeo-based, infra-PAT isolated, and cluster-credential-free."

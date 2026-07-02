# PR CI without deployment handoff

This document records the Chunk 6 workflow.

## Workflow

File: `.github/workflows/pr-ci.yml`

Trigger:

- `pull_request`
- base branch: `main`
- activity types:
  - `opened`
  - `synchronize`
  - `reopened`

The workflow intentionally does not use:

- `pull_request_target`
- `workflow_run`
- `workflow_dispatch`
- repository secrets
- environment secrets
- personal access tokens
- kubeconfig
- kubectl
- Argo CD credentials
- kubeseal
- Sealed Secrets private keys
- infrastructure repository checkout or push

## Same-repository PR guard

Both jobs use:

```yaml
if: ${{ github.event.pull_request.head.repo.full_name == github.repository }}
```

This chunk only supports same-repository PRs.

## Jobs

### quality-gate

Runs on `arc-ainulindale-api`.

Permissions:

```yaml
contents: read
```

Runs the existing local quality gate:

```bash
scripts/quality-gate.sh
```

### build-and-push

Runs on `arc-ainulindale-api`.

Depends on:

```yaml
needs: quality-gate
```

Permissions:

```yaml
contents: read
packages: write
```

Builds with Buildah and pushes:

```text
ghcr.io/dana/ainulindale-api:${{ github.event.pull_request.head.sha }}
```

The image tag must exactly match the PR head SHA.

## Validation command

```bash
make validate-pr-ci-workflow
```

## Manual validation checklist

- Open or update a same-repository PR.
- Confirm the `PR CI` workflow runs from the `pull_request` event.
- Confirm `quality-gate` runs before `build-and-push`.
- Confirm `build-and-push` does not start when tests fail.
- Confirm the pushed GHCR image tag exactly equals the PR head SHA.
- Confirm workflow logs do not dump secrets, contexts, or environment variables.
- Confirm the workflow does not reference deployment handoff material.
- Confirm closing an unmerged PR does not trigger deployment behavior.
- Reboot `elwing`, update the PR branch, and confirm ARC still accepts the run.

## Deployment-separation rule

This workflow is validation and image publication only.

It must not deploy to Kubernetes, update Argo CD, commit to an infrastructure repository, run kubectl, read kubeconfig, use Sealed Secrets private keys, or access deployment-specific credentials.

# Merged PR deployment handoff

This is the Chunk 10 privileged workflow.

## Workflow

File:

~~~text
.github/workflows/merged-pr-deployment-handoff.yml
~~~

Trigger:

~~~yaml
pull_request:
  branches:
    - main
  types:
    - closed
~~~

Job guard:

~~~yaml
if: ${{ github.event.pull_request.merged == true && github.event.pull_request.head.repo.full_name == github.repository }}
~~~

This means closing a PR without merging may create a skipped workflow run, but it must not deploy.

## Security boundary

Workflow 1 validates PR code and pushes:

~~~text
ghcr.io/dana/ainulindale-api:${{ github.event.pull_request.head.sha }}
~~~

Workflow 2 does not build code and does not use cluster credentials. It only:

1. Authenticates to GHCR with `GITHUB_TOKEN`.
2. Verifies the PR-head-SHA image exists.
3. Uses Skopeo to copy that already-built image tag to `:main`.
4. Authenticates to `dana/ainulindale-infra` with `AINULINDALE_INFRA_DEPLOY_TOKEN`.
5. Runs `kustomize edit set image` in `apps/ainulindale-api/overlays/prod`.
6. Commits and pushes only the updated `kustomization.yaml`.

The `:main` GHCR tag is only a human-readable convenience alias. Argo CD must deploy the immutable PR head SHA from the infra repo.

## Secret

Repository secret in `dana/ainulindale-api`:

~~~text
AINULINDALE_INFRA_DEPLOY_TOKEN
~~~

The token should be a fine-grained PAT with access only to:

~~~text
dana/ainulindale-infra
~~~

Required repository permissions:

~~~text
Contents: Read and write
~~~

Do not grant this token access to `dana/ainulindale-api`.

Do not grant this token `Actions`, `Administration`, `Deployments`, `Pull requests`, `Secrets`, `Variables`, `Webhooks`, or `Workflows` permissions.

## Validation command

~~~bash
make validate-merged-pr-deployment-handoff-workflow
~~~

## Manual validation checklist

- Merge a tiny same-repository PR and verify this workflow runs.
- Close a PR unmerged and verify no infra commit is created.
- Verify the infra commit changes only `apps/ainulindale-api/overlays/prod/kustomization.yaml`.
- Verify the committed `newTag` equals the PR head SHA.
- Verify rendered Kustomize deploys the SHA tag, not `:main`.
- Verify GHCR `:main` has the same digest as the SHA tag.
- Verify Argo CD becomes `Synced` and `Healthy`.
- Reboot `elwing`, merge another tiny PR, and verify the full path still works.

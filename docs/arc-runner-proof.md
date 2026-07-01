# ARC runner proof

This document records the Chunk 5 proof that GitHub Actions jobs can land on
the local MicroK8s ARC runner scale set before it is trusted with tests, image
builds, registry pushes, or deployment handoff.

## Names

- Controller/listener namespace: `arc-systems`
- Runner namespace: `arc-runners`
- Runner scale set / workflow `runs-on`: `arc-ainulindale-api`
- Repository: `dana/ainulindale-api`

## Intended workflow constraints

The proof workflow must:

- use `pull_request`
- not use `pull_request_target`
- not use repository secrets
- not check out repository code
- not run pytest, linting, image builds, registry pushes, kubectl, Argo CD, or kubeseal
- print only harmless runner metadata
- fail unless `RUNNER_ENVIRONMENT=self-hosted`

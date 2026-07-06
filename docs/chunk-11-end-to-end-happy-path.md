
# Chunk 11 — End-to-end happy-path feature deployment

This chunk proves the full development loop with a deliberately tiny feature.

Feature endpoint:

`POST /api/v1/happy-path`

Example request:

```json
{"message":"chunk 11"}

Expected response:

JSON
￼

{
  "message": "chunk 11",
  "proof": "chunk-11-happy-path",
  "length": 8
}

Evidence to capture:

Before merge, https://diederich.ai/api/v1/happy-path is not live.

PR CI passes on the PR head SHA.

GHCR contains ghcr.io/dana/ainulindale-api:<PR_HEAD_SHA>.

The merged-PR deployment handoff workflow runs after merge.

The infra repo prod overlay is updated to newTag: <PR_HEAD_SHA>.

Argo CD reports the application Synced and Healthy.

Kubernetes Deployment runs ghcr.io/dana/ainulindale-api:<PR_HEAD_SHA>.

The public endpoint returns the expected JSON.

Negative JSON contract tests fail with JSON 4xx responses.

After rebooting elwing, the same public endpoint returns correctly without manual intervention.

The :main GHCR tag is only a convenience alias. Argo CD must deploy the immutable PR head SHA tag from the infra repository.



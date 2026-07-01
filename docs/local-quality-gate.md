# Local quality gate

This command sequence is the local version of the checks that Workflow 1 will
eventually run before building an image.

It does not require:

- GitHub Actions
- Kubernetes
- MicroK8s
- GHCR
- Argo CD
- Docker
- Buildah
- Skopeo
- kubeseal
- kubeconfig
- repository secrets
- environment secrets
- personal access tokens

## First-time setup from a checkout

```bash
python3 -m venv .venv
. .venv/bin/activate

python -m pip install --upgrade pip

if [ -f requirements.txt ]; then
    python -m pip install -r requirements.txt
fi

python -m pip install -r requirements-dev.lock

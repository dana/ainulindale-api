# ainulindale-api

Minimal FastAPI API service.

## Local development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
make test
make lint
make smoke

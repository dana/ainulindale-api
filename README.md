# ainulindale-api

Minimal FastAPI API service.

## Endpoints

- `GET /api/v1/happy`: Returns current UTC system time and system load averages.

## Local development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
make test
make lint
make smoke

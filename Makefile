.PHONY: dev test lint run smoke restart-check check clean image-build image-metadata-compare container-smoke image-smoke

dev:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -e ".[dev]"

test:
	.venv/bin/python -m pytest

lint:
	.venv/bin/python -m ruff check .

run:
	.venv/bin/python -m uvicorn ainulindale_api.main:app --host 127.0.0.1 --port 8000 --reload

smoke:
	scripts/smoke-local.sh

restart-check:
	scripts/restart-local.sh

check: lint test smoke restart-check

clean:
	rm -rf .pytest_cache .ruff_cache src/*.egg-info build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

image-build:
	scripts/build-image-local.sh

image-metadata-compare:
	scripts/image-metadata-compare.sh

container-smoke:
	scripts/container-smoke.sh

image-smoke: image-metadata-compare container-smoke

.PHONY: validate-pr-ci-workflow
validate-pr-ci-workflow:
	scripts/validate-pr-ci-workflow.sh

.PHONY: validate-merged-pr-deployment-handoff-workflow
validate-merged-pr-deployment-handoff-workflow:
	scripts/validate-merged-pr-deployment-handoff-workflow.sh

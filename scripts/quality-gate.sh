#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$repo_root"

if [ -d "src" ]; then
    export PYTHONPATH="$repo_root/src:${PYTHONPATH:-}"
fi

mkdir -p reports

failures=()

run_step() {
    local name="$1"
    shift

    echo
    echo "==> ${name}"
    if "$@"; then
        echo "PASS: ${name}"
    else
        local status=$?
        echo "FAIL: ${name} exited with status ${status}"
        failures+=("${name}")
    fi
}

run_step "pytest" \
    python -m pytest \
        --junitxml=reports/pytest-junit.xml \
        --cov=src \
        --cov-report=xml:reports/coverage.xml \
        --cov-report=term-missing

echo
echo "==> ruff lint"
python -m ruff check . || ruff_status=$?
python -m ruff check --output-format=junit . > reports/ruff-junit.xml || true

if [ "${ruff_status:-0}" -eq 0 ]; then
    echo "PASS: ruff lint"
else
    echo "FAIL: ruff lint exited with status ${ruff_status}"
    failures+=("ruff lint")
fi
unset ruff_status

echo
echo "==> ruff format check"
if python -m ruff format --check . | tee reports/ruff-format.txt; then
    echo "PASS: ruff format check"
else
    status=$?
    echo "FAIL: ruff format check exited with status ${status}"
    failures+=("ruff format check")
fi

run_step "bandit static security scan" \
    python -m bandit \
        -r src \
        -c bandit.yaml \
        -f json \
        -o reports/bandit.json

run_step "pip-audit dependency vulnerability scan" \
    python -m pip_audit \
        --local \
        -f json \
        -o reports/pip-audit.json \
        --progress-spinner off

echo
echo "Generated reports:"
find reports -maxdepth 1 -type f -printf '  %p\n' | sort

if [ "${#failures[@]}" -ne 0 ]; then
    echo
    echo "QUALITY GATE FAILED"
    printf '  - %s\n' "${failures[@]}"
    exit 1
fi

echo
echo "QUALITY GATE PASSED"

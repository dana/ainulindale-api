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

echo
echo "==> gitleaks secret scan"
if command -v gitleaks >/dev/null 2>&1; then
    run_step "gitleaks secret scan" \
        gitleaks detect --source . --report-format json --report-path reports/gitleaks.json --redact
elif [ -n "${CI:-}" ]; then
    echo "FAIL: gitleaks is required in CI environment"
    failures+=("gitleaks secret scan")
else
    echo "WARN: gitleaks not found in PATH; skipping local secret scan"
fi

echo
echo "==> semgrep SAST scan"
if command -v semgrep >/dev/null 2>&1; then
    run_step "semgrep SAST scan" \
        semgrep scan --config p/python --config p/owasp-top-ten --json --output reports/semgrep.json --error src/
elif [ -n "${CI:-}" ]; then
    echo "FAIL: semgrep is required in CI environment"
    failures+=("semgrep SAST scan")
else
    echo "WARN: semgrep not found in PATH; skipping local semgrep scan"
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

if [ -f "Containerfile" ]; then
    echo
    echo "==> hadolint Containerfile lint"
    if command -v hadolint >/dev/null 2>&1; then
        run_step "hadolint Containerfile lint" \
            hadolint Containerfile
    elif [ -n "${CI:-}" ]; then
        echo "FAIL: hadolint is required in CI environment"
        failures+=("hadolint Containerfile lint")
    else
        echo "WARN: hadolint not found in PATH; skipping Containerfile lint"
    fi
fi

echo
echo "==> trivy config scan and CycloneDX SBOM"
if command -v trivy >/dev/null 2>&1; then
    if [ -f "Containerfile" ]; then
        run_step "trivy config scan" \
            trivy config --severity HIGH,CRITICAL --format json --output reports/trivy-config.json Containerfile
    fi
    run_step "trivy CycloneDX SBOM generation" \
        trivy fs --format cyclonedx --output reports/cyclonedx.json .
elif [ -n "${CI:-}" ]; then
    echo "FAIL: trivy is required in CI environment"
    failures+=("trivy config & SBOM")
else
    echo "WARN: trivy not found in PATH; skipping trivy config scan & SBOM generation"
fi

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

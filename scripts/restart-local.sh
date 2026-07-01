#!/usr/bin/env bash
set -euo pipefail

for iteration in 1 2 3; do
  port="$((8000 + iteration))"
  echo "restart validation iteration ${iteration} on port ${port}"
  PORT="${port}" scripts/smoke-local.sh
done

echo "restart-local passed"

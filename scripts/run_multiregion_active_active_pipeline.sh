#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "[multiregion-pipeline] python not found"
    exit 1
  fi
fi

echo "[multiregion-pipeline] deploy two-region active-active simulation"
"$PYTHON_BIN" "$ROOT_DIR/scripts/deploy_multiregion_active_active.py" \
  --cluster-name ekb-multiregion \
  --region-a cn-north-1 \
  --region-b eu-central-1 \
  --namespace-prefix ekb \
  --replicas-per-deployment 1 \
  --timeout-seconds 900

echo "[multiregion-pipeline] run failover + load test"
"$PYTHON_BIN" "$ROOT_DIR/scripts/test_multiregion_failover_and_load.py" \
  --namespace-a ekb-region-a \
  --namespace-b ekb-region-b \
  --duration 45s \
  --vus 50 \
  --rollout-timeout-seconds 900

echo "[multiregion-pipeline] done"

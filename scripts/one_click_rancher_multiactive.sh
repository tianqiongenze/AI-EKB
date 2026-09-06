#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "[one-click] shutdown all partition deployments"
kubectl --request-timeout=30s -n ekb-control-plane scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-dev-region-a scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-dev-region-b scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-staging-region-a scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-staging-region-b scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-prod-region-a scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-prod-region-b scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-region-a scale deployment --all --replicas=0 || true
kubectl --request-timeout=30s -n ekb-region-b scale deployment --all --replicas=0 || true

echo "[one-click] install rancher desktop via homebrew cask"
brew install --cask rancher || true

echo "[one-click] deploy lightweight multi-env multi-active application planes"
. "$ROOT_DIR/.venv/bin/activate"
python "$ROOT_DIR/scripts/run_multi_env_multiactive_light.py" --environments dev,staging,prod --replicas 1

echo "[one-click] scale core region stores"
kubectl --request-timeout=30s -n ekb-region-a scale deployment --all --replicas=1
kubectl --request-timeout=30s -n ekb-region-b scale deployment --all --replicas=1

echo "[one-click] run region failover pressure test"
python "$ROOT_DIR/scripts/test_multiregion_failover_and_load.py" --namespace-a ekb-region-a --namespace-b ekb-region-b --duration 45s --vus 50 --rollout-timeout-seconds 900

echo "[one-click] run production parameterized dry-run"
python "$ROOT_DIR/scripts/run_production_param_dryrun.py" --namespace ekb-control-plane --flink-image ekb-mirror/yadea-ekb-flink-session:local --aws-access-key-id dryrun-ak --aws-secret-access-key dryrun-sk || true

echo "[one-click] finished"

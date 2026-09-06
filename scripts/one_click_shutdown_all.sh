#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

source "$ROOT_DIR/scripts/colima_runtime.sh"

ensure_colima_runtime
ensure_docker_compose

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[shutdown-all] compose command not found"
  exit 1
fi

echo "[shutdown-all] stopping phase3 stack"
"${COMPOSE_CMD[@]}" -f "$ROOT_DIR/infra/docker-compose.phase3.yml" down --remove-orphans --volumes || true
"${COMPOSE_CMD[@]}" -f "$ROOT_DIR/infra/docker-compose.phase3.colima.yml" down --remove-orphans --volumes || true

echo "[shutdown-all] stopping perf-local stack"
"${COMPOSE_CMD[@]}" -f "$ROOT_DIR/infra/docker-compose.perf.local.yml" down --remove-orphans --volumes || true

echo "[shutdown-all] cleaning dangling containers/networks"
docker container prune -f >/dev/null || true
docker network prune -f >/dev/null || true

echo "[shutdown-all] cleaning local k8s resources (best effort)"
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete ns ekb-control-plane --wait=false >/dev/null 2>&1 || true
  kubectl delete -k "$ROOT_DIR/infra/k8s/deps" >/dev/null 2>&1 || true
  kubectl delete -k "$ROOT_DIR/infra/kustomize/base" >/dev/null 2>&1 || true
fi

echo "[shutdown-all] done"
